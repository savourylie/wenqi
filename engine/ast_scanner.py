"""wenqi 的 preflight、lint 和 update-state 命令列入口。"""

from __future__ import annotations

import argparse
import json
import re
import sys
from bisect import bisect_left, bisect_right
from collections import Counter
from dataclasses import dataclass, replace
from itertools import chain
from pathlib import Path
from typing import Iterator, Sequence

if not __package__:
    # §7 同時支援 python engine/ast_scanner.py 和模組呼叫。
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine import LexiconError, load_default_lexicons
from engine import state_manager as state
from engine.l0_normalizer import L0Error, L0Issue, MaskRegion, normalize, visible_prose
from engine.rules import LAYERS, Issue, RuleProfile, SentenceContext, load_scanners
from engine.rules.l5_preflight import preflight
from engine.tokenizer_adapter import JiebaPosAdapter, Token, TokenizerError


_LINE_BREAK = re.compile(r"\r\n|\r|\n")
_PARAGRAPH_BREAK = re.compile(r"\r?\n(?:[ \t]*\r?\n)+")
_SENTENCE = re.compile(r"[^。！？]+(?:[。！？]+[」』”’）》】）\]]*)?")
_CLAUSE = re.compile(r"[^，。！？；：]+")
_HAS_TEXT = re.compile(r"[^\s\0。！？；：，、,.!?;:]")
_FRAME_HEAD = re.compile(
    r"的(?P<noun>過程|背景|情況|前提|角度|層面|基礎)"
    r"(?:當中|中|之下|下|來看|上)(?=[，。！？；：]|$)"
)


class ScannerError(ValueError):
    """掃描或更新請求無法完成。"""


@dataclass(frozen=True)
class _Sentence:
    start: int
    end: int
    is_paragraph_end: bool


def _paragraph_spans(prose: str, masks: Sequence[MaskRegion]) -> Iterator[tuple[int, int]]:
    start = 0
    blocks = (region for region in masks if region.is_block)
    for block in chain(blocks, (None,)):
        end = block.original_start if block is not None else len(prose)
        for blank_line in _PARAGRAPH_BREAK.finditer(prose, start, end):
            yield start, blank_line.start()
            start = blank_line.end()
        yield start, end
        if block is not None:
            start = block.original_end


def _sentences(text: str, prose: str, masks: Sequence[MaskRegion]) -> Iterator[_Sentence]:
    for start, end in _paragraph_spans(prose, masks):
        matches = [
            match
            for match in _SENTENCE.finditer(prose, start, end)
            if _HAS_TEXT.search(match[0])
        ]
        for index, match in enumerate(matches):
            raw = text[match.start():match.end()]
            yield _Sentence(
                start=match.end() - len(raw.lstrip()),
                end=match.start() + len(raw.rstrip()),
                is_paragraph_end=index == len(matches) - 1,
            )


def _rule_profile(settings: dict) -> RuleProfile:
    disabled = settings["disabled_rules"]
    return {
        **settings["profile_config"],
        "name": settings["effective_profile"],
        "disabled_rules": list(dict.fromkeys(disabled["profile"] + disabled["document"])),
    }


def _must_keep_words(
    tokens: Sequence[Token], text: str, replaceable_words: set[str], replacements: set[int]
) -> list[str]:
    frame_heads = {match.start("noun") for match in _FRAME_HEAD.finditer(text)}
    return list(dict.fromkeys(
        token.surface
        for token in tokens
        if token.is_frozen or (
            (token.pos.startswith(("n", "v")) or token.pos in {"a", "an"})
            and token.surface not in replaceable_words
            and token.start_char not in frame_heads
            and token.start_char not in replacements
        )
    ))


class _L0Diagnostic(Issue):
    suggestion: str


def _l0_diagnostic(issue: L0Issue, sentence_start: int) -> _L0Diagnostic:
    original, suggestion = issue["surface"], issue["suggestion"]
    return {
        "layer": "L0",
        "rule_id": issue["rule_id"],
        "priority": 0,
        "span": original,
        "pos_pattern": "DE_COMP",
        "theoretical_basis": issue["theoretical_basis"],
        "instruction": f"將補語位置的「{original}」改為「{suggestion}」。",
        "char_idx": issue["char_idx"] - sentence_start,
        "suggestion": suggestion,
    }


def lint(text: str, settings: dict, *, requested_layer: str = "ALL") -> dict:
    """以 state_manager 解析出的設定掃描文章，回傳 §4.2 的句級診斷。"""
    profile = _rule_profile(settings)
    disabled = set(profile["disabled_rules"])
    scanners = tuple(load_scanners(requested_layer))
    normalized = normalize(text, JiebaPosAdapter(settings["whitelist"]))
    prose = visible_prose(text, normalized.mask_regions)
    sentences = list(_sentences(text, prose, normalized.mask_regions))
    sentence_texts = [text[span.start:span.end] for span in sentences]
    line_starts = [0] + [match.end() for match in _LINE_BREAK.finditer(text)]
    token_starts = [token.start_char for token in normalized.tokens]
    l0_starts = [issue["char_idx"] for issue in normalized.issues]
    lexicons = load_default_lexicons()
    replaceable_words = {"是", "有"} | {
        item["term"] for table in ("weak_verbs", "pseudo_jargon") for item in lexicons[table]
    }
    line_sentences: Counter[int] = Counter()
    issue_counts = dict.fromkeys(LAYERS, 0)
    diagnostics = []

    for index, span in enumerate(sentences):
        line = bisect_right(line_starts, span.start)
        line_sentences[line] += 1
        scanned_text = prose[span.start:span.end]
        context = SentenceContext(
            text=scanned_text,
            clause_spans=tuple(
                match.span() for match in _CLAUSE.finditer(scanned_text) if _HAS_TEXT.search(match[0])
            ),
            is_paragraph_end=span.is_paragraph_end,
            original_text=sentence_texts[index],
        )
        token_start = bisect_left(token_starts, span.start)
        token_end = bisect_left(token_starts, span.end, lo=token_start)
        tokens = tuple(
            replace(
                token,
                start_char=token.start_char - span.start,
                end_char=token.end_char - span.start,
            )
            for token in normalized.tokens[token_start:token_end]
            if token.end_char <= span.end
        )
        issues: list[Issue] = []
        if requested_layer == "ALL":
            l0_start = bisect_left(l0_starts, span.start)
            l0_end = bisect_left(l0_starts, span.end, lo=l0_start)
            issues.extend(
                _l0_diagnostic(issue, span.start) for issue in normalized.issues[l0_start:l0_end]
            )
        for layer, scan in scanners:
            for issue in scan(tokens, context, profile):
                if issue["layer"] != layer:
                    raise ScannerError(f"{layer} 規則回傳了 {issue['layer']} 的診斷")
                issues.append(issue)

        issues = [issue for issue in issues if issue["rule_id"] not in disabled]
        if not issues:
            continue
        issues.sort(key=lambda issue: issue["priority"])
        replacements = {
            start for issue in issues for start in issue.get("_replaceable_token_starts", ())
        }
        must_keep = _must_keep_words(tokens, scanned_text, replaceable_words, replacements)
        preserved = set(must_keep)
        kept_replacements = {
            token.start_char: token.surface for token in tokens
            if token.start_char in replacements and token.surface in preserved
        }
        public_issues: list[Issue] = []
        for issue in issues:
            layer = issue["layer"]
            issue_counts[layer] = issue_counts.get(layer, 0) + 1
            # 若同一原詞在句中其他位置仍須保留，改用可遵守的指令。
            if "_replaceable_token_starts" in issue:
                issue = issue.copy()
                blocked = dict.fromkeys(
                    kept_replacements[start] for start in issue.pop("_replaceable_token_starts")
                    if start in kept_replacements
                )
                if blocked:
                    words = "、".join(f"「{word}」" for word in blocked)
                    issue["instruction"] = f"保留{words}的原字，可調整「{issue['span']}」的語序。"
            public_issues.append(issue)

        diagnostics.append({
            "sentence_id": f"L{line}_S{line_sentences[line]}",
            "line_number": line,
            "context_before": sentence_texts[index - 1] if index else "",
            "target_sentence": sentence_texts[index],
            "context_after": sentence_texts[index + 1] if index + 1 < len(sentences) else "",
            "frozen_whitelist_hits": list(dict.fromkeys(
                token.surface for token in tokens if token.is_frozen
            )),
            "must_keep_content_words": must_keep,
            "de_normalization_map": [
                {
                    "char_idx": token.start_char,
                    "surface": token.surface,
                    "true_role": token.true_de_role,
                }
                for token in tokens
                if token.true_de_role
            ],
            "issues": public_issues,
        })

    return {
        "mode": "LINT",
        "requested_layer": requested_layer,
        "effective_profile": profile["name"],
        "thresholds_applied": {
            "max_pre_modifier_len": profile["max_pre_modifier_len"],
            "max_clause_len": profile["max_clause_len"],
        },
        "summary": {
            "total_sentences": len(sentences),
            "flagged_sentences": len(diagnostics),
            "issue_counts": issue_counts,
        },
        "diagnostics": diagnostics,
    }


def _comma_terms(raw: str) -> list[str]:
    terms = [term.strip() for term in raw.split(",")]
    if not all(terms):
        raise argparse.ArgumentTypeError("白名單須為逗號分隔的非空詞條")
    return terms


def _tagged_terms(raw: str) -> list[dict]:
    entries = []
    for pair in _comma_terms(raw):
        term, separator, pos = pair.rpartition(":")
        if not separator or not term.strip() or not pos.strip():
            raise argparse.ArgumentTypeError("白名單詞條格式為 TERM:POS")
        entries.append({"term": term.strip(), "pos": pos.strip()})
    return entries


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="掃描 wenqi 中文稿件並輸出 JSON")
    parser.add_argument("--mode", required=True, choices=("preflight", "lint", "update-state"))
    parser.add_argument("--layer", choices=(*LAYERS, "ALL"))
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--file", type=Path, metavar="FILE_PATH")
    source.add_argument("--stdin", action="store_true")
    parser.add_argument("--profile", choices=tuple(state.DEFAULT_PROFILES))
    parser.add_argument(
        "--ephemeral-whitelist", type=_comma_terms, action="extend",
        default=[], metavar="TERM1,TERM2,...",
    )
    for scope in ("global", "local"):
        parser.add_argument(
            f"--add-{scope}-whitelist", type=_tagged_terms, action="extend",
            default=[], metavar="TERM:POS,...",
        )
    return parser


def _validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.layer is not None and args.mode != "lint":
        parser.error("--layer 只適用於 lint")
    if args.mode == "update-state":
        if args.profile is not None or args.ephemeral_whitelist:
            parser.error("--profile 與 --ephemeral-whitelist 只適用於 preflight 或 lint")
        if not (args.add_global_whitelist or args.add_local_whitelist):
            parser.error("update-state 須指定要更新的白名單")
        if args.add_local_whitelist and args.file is None:
            parser.error("--add-local-whitelist 須搭配 Git Repo 內的 --file")
        for entries in (args.add_global_whitelist, args.add_local_whitelist):
            if len({entry["term"] for entry in entries}) != len(entries):
                parser.error("同一白名單的更新請求含重複詞條")
    else:
        if args.file is None and not args.stdin:
            parser.error(f"{args.mode} 須指定 --file 或 --stdin")
        if args.add_global_whitelist or args.add_local_whitelist:
            parser.error("--add-*-whitelist 只適用於 update-state")


def _updated_entries(whitelist: list[dict], entries: Sequence[dict]) -> list[dict]:
    requested = {entry["term"] for entry in entries}
    return [entry for entry in whitelist if entry["term"] in requested]


def _update_state(args: argparse.Namespace) -> dict:
    global_terms, local_terms = args.add_global_whitelist, args.add_local_whitelist
    target_id = None
    updated_global, updated_local = [], []
    file = args.file.resolve() if local_terms else None
    if file is not None:
        text = file.read_bytes().decode("utf-8")
        if state.find_repo_root(file) is None:
            raise ScannerError("--add-local-whitelist 須搭配 Git Repo 內的 --file")

    with state.state_lock():
        if file is not None:
            settings = state.load_settings_for_file(file, text=text)
            if settings["repo_root"] is None:
                raise ScannerError("--add-local-whitelist 須搭配 Git Repo 內的 --file")
            target_id = settings["rel_path"]
            workspace = state.add_local_whitelist(
                Path(settings["repo_root"]), target_id, local_terms, settings["content_hash"]
            )
            updated_local = _updated_entries(
                workspace["documents"][target_id]["local_whitelist"], local_terms
            )
        if global_terms:
            try:
                config = state.add_global_whitelist(global_terms)
            except (state.StateError, OSError) as exc:
                if updated_local:
                    raise ScannerError(f"單篇白名單已更新。全域白名單更新失敗（{exc}）。") from exc
                raise
            updated_global = _updated_entries(config["global_whitelist"], global_terms)

    return {
        "mode": "UPDATE_STATE",
        "target_id": target_id,
        "updated_global_whitelist": updated_global,
        "updated_local_whitelist": updated_local,
    }


def _scan_input(args: argparse.Namespace) -> dict:
    file = args.file.resolve() if args.file is not None else None
    text = (file.read_bytes() if file is not None else sys.stdin.buffer.read()).decode("utf-8")
    with state.state_lock():
        if file is None:
            settings = state.load_settings_for_stdin(text, args.profile, args.ephemeral_whitelist)
            source_type, target_id = "stdin", "stdin"
        else:
            settings = state.load_settings_for_file(
                file, args.profile, args.ephemeral_whitelist, text=text
            )
            source_type, target_id = "file", settings["rel_path"] or str(file)
    if args.mode == "preflight":
        return preflight(
            text,
            source_type=source_type,
            target_id=target_id,
            whitelist=settings["whitelist"],
            profile_override=args.profile,
            fallback_profile=settings["effective_profile"],
        )
    return lint(text, settings, requested_layer=args.layer or "ALL")


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    _validate_args(parser, args)
    try:
        payload = _update_state(args) if args.mode == "update-state" else _scan_input(args)
    except (ScannerError, state.StateError, L0Error, LexiconError, TokenizerError,
            OSError, UnicodeError) as exc:
        parser.exit(1, f"{parser.prog}: {exc}\n")
    output = json.dumps(payload, ensure_ascii=False) + "\n"
    sys.stdout.buffer.write(output.encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
