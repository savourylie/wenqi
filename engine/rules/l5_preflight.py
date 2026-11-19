"""第五層預檢：疑似專有名詞抽取與語體自動推測。

規格：zh_polish_skill_spec_v2.md §2.5、§4.2 模式一（TICKET-005）。
"""

from __future__ import annotations

import re
from bisect import bisect_right
from itertools import accumulate
from typing import Iterable, Iterator, Literal, Sequence, TypedDict

from .. import load_default_lexicons
from ..l0_normalizer import normalize, visible_prose
from ..state_manager import DEFAULT_PROFILE, content_hash, resolve_profile
from ..tokenizer_adapter import LATIN_WORD_CHAR, Token, TokenizerAdapter, whitelist_matches

_SUFFIXES = ("性", "度", "化")
_SUFFIX_REASON = "SUFFIX_XING_UNREGISTERED (帶有『~性/~度/~化』後綴但未登錄於白名單)"
_CODE_SWITCH_REASON = "CODE_SWITCH_WEAK_VERB (弱動詞後接英文專有動作)"
_HAN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
_SUFFIX_WORD = re.compile(r"[A-Za-z0-9\u3400-\u4dbf\u4e00-\u9fff]+")
_NON_PREFIX_POS = {"p", "c", "u", "uj", "x", "m", "mq", "q"}
_NUMERAL = r"(?:\d+|[〇零一二兩三四五六七八九十百千萬億兆幾數]+)"
_DEGREE_QUANTITY = re.compile(rf"{_NUMERAL}度")
_SENTENCE_BREAK = re.compile(r"[。！？!?]+|\.(?![A-Za-z0-9])|[\r\n]+")
_ENGLISH_WORD = r"[A-Za-z][A-Za-z0-9]*(?:[-‐‑/][A-Za-z0-9]+)*"
_ENGLISH_WORDS = re.compile(rf"(?<!{LATIN_WORD_CHAR}){_ENGLISH_WORD}(?!{LATIN_WORD_CHAR})")
_HORIZONTAL_SPACE = r"[ \t\u3000]"
_TEMPORAL_CONNECTOR = rf"(?i:before|after){_HORIZONTAL_SPACE}"
_BEFORE_AND_AFTER = (
    rf"(?i:before{_HORIZONTAL_SPACE}+and{_HORIZONTAL_SPACE}+after)(?!{LATIN_WORD_CHAR})"
)
_ENGLISH_PHRASE = (
    rf"(?:{_BEFORE_AND_AFTER}|{_ENGLISH_WORD})"
    rf"(?:{_HORIZONTAL_SPACE}+(?!{_TEMPORAL_CONNECTOR}){_ENGLISH_WORD})*"
)
_ASPECT = rf"(?:{_HORIZONTAL_SPACE}*[了過著])?"
_REPETITIONS = rf"(?:{_HORIZONTAL_SPACE}*{_NUMERAL}次)?"

_TECH_TERM_SHARE = 0.04
_TECH_ENGLISH_SHARE = 0.20
# 系統元件、執行行為、維運變更。各類詞互相佐證技術語體。
_ZH_TECH_PROFILE_GROUPS = (
    ("資料庫", "佇列", "快取", "資料表", "節點"),
    ("併發", "非同步", "逾時", "指數退避", "重試"),
    ("部署", "回滾", "索引", "遷移"),
)
_EMOJI_RANGE = r"\U0001f300-\U0001faff"
_EMOJI = re.compile(rf"[{_EMOJI_RANGE}]")
_SOCIAL_PARTICLE = re.compile(rf"[啦欸喔耶吧嘛呀](?=$|[。！？!?,，\s{_EMOJI_RANGE}])")
_MIN_HAN_CHARACTERS = 8
_SOCIAL_SENTENCE_LENGTH = 16
_ESSAY_SENTENCE_LENGTH = 20


class SuspectTerm(TypedDict):
    term: str
    count: int
    sample_sentence: str
    reason: str


class PreflightPayload(TypedDict):
    mode: Literal["L5_PREFLIGHT"]
    source_type: Literal["file", "stdin"]
    target_id: str
    content_hash: str
    suggested_profile: str
    profile_reason: str
    active_whitelist_terms: list[str]
    suspect_terms_for_review: list[SuspectTerm]


def _suffix_spans(prose: str, tokens: Sequence[Token]) -> Iterator[tuple[int, int]]:
    starts_by_end: dict[int, int] = {}
    for index, token in enumerate(tokens):
        term = token.surface
        if token.is_frozen or not term.endswith(_SUFFIXES):
            continue
        if not _SUFFIX_WORD.fullmatch(term):
            continue
        start = token.start_char
        if len(term) == 1:
            if index == 0:
                continue
            previous = tokens[index - 1]
            # 分詞器有時將後綴切成單字，如「延遲／度」。
            if (
                previous.end_char != start
                or previous.pos in _NON_PREFIX_POS
                or not _SUFFIX_WORD.fullmatch(previous.surface)
            ):
                continue
            start = previous.start_char
            term = previous.surface + term
            # 保留「可／觀察／性」之中連續而完整的術語。
            if token.surface == "性" and previous.pos in {"v", "vn"} and index >= 2:
                prefix = tokens[index - 2]
                if prefix.surface == "可" and prefix.end_char == start:
                    start = prefix.start_char
                    term = prefix.surface + term
        # 「一度」「十度」的「度」是量詞，詞性標籤會隨上下文變動。
        if _DEGREE_QUANTITY.fullmatch(term):
            continue
        starts_by_end[token.end_char] = start

    # 同篇辨認過的完整詞可補回被切碎的候選。只延伸到同一個後綴終點。
    terms = (prose[start:end] for end, start in starts_by_end.items())
    for hit in whitelist_matches(prose, terms):
        end = hit.end()
        if end in starts_by_end:
            starts_by_end[end] = min(starts_by_end[end], hit.start())
    for end, start in starts_by_end.items():
        yield start, end


def _code_switch_hits(
    prose: str, tokens: Sequence[Token], weak_verbs: Iterable[str]
) -> list[re.Match[str]]:
    # 「做」見於 §2.5 的「做一次 Benchmark」，也屬 L5 的候選起點。
    verbs = "|".join(map(re.escape, (*weak_verbs, "做")))
    pattern = re.compile(
        rf"(?:{verbs}){_ASPECT}{_REPETITIONS}{_HORIZONTAL_SPACE}*"
        rf"{_ENGLISH_PHRASE}(?!{LATIN_WORD_CHAR})"
    )
    token_starts = {token.start_char for token in tokens}
    return [match for match in pattern.finditer(prose) if match.start() in token_starts]


def _sentence_ends(prose: str) -> list[int]:
    ends = [match.end() for match in _SENTENCE_BREAK.finditer(prose)]
    if not ends or ends[-1] < len(prose):
        ends.append(len(prose))
    return ends


def _review_terms(
    text: str,
    prose: str,
    tokens: Sequence[Token],
    code_switch_hits: list[re.Match[str]],
    whitelist_hits: list[re.Match[str]],
    sentence_ends: list[int],
) -> list[SuspectTerm]:
    candidates = [(start, end, _SUFFIX_REASON) for start, end in _suffix_spans(prose, tokens)]
    candidates.extend((hit.start(), hit.end(), _CODE_SWITCH_REASON) for hit in code_switch_hits)
    candidates.sort(key=lambda candidate: candidate[0])

    protected = [(hit.start(), hit.end()) for hit in whitelist_hits]
    protected.extend((token.start_char, token.end_char) for token in tokens if token.is_frozen)
    protected.sort()
    protected_starts = [start for start, _ in protected]
    # 白名單可重疊，保留各起點之前的最大終點以判斷候選是否完全受保護。
    protected_ends = list(accumulate((end for _, end in protected), max))

    suspects: dict[tuple[str, str], SuspectTerm] = {}
    for start, end, reason in candidates:
        protection_index = bisect_right(protected_starts, start) - 1
        if protection_index >= 0 and end <= protected_ends[protection_index]:
            continue
        term = text[start:end]
        key = (term, reason)
        if key in suspects:
            suspects[key]["count"] += 1
            continue
        sentence_index = bisect_right(sentence_ends, start)
        sentence_start = sentence_ends[sentence_index - 1] if sentence_index else 0
        sentence_end = sentence_ends[sentence_index]
        suspects[key] = {
            "term": term,
            "count": 1,
            "sample_sentence": text[sentence_start:sentence_end].strip(),
            "reason": reason,
        }
    return list(suspects.values())


def _technical_profile_reason(
    prose: str,
    tokens: Sequence[Token],
    tech_terms: Iterable[str],
    code_switch_count: int,
) -> str | None:
    han_words = sum(_HAN.search(token.surface) is not None for token in tokens)
    english_words = len(_ENGLISH_WORDS.findall(prose))
    word_count = han_words + english_words
    tech_count = len(whitelist_matches(prose, tech_terms))
    tech_share = tech_count / word_count if word_count else 0
    if tech_share >= _TECH_TERM_SHARE:
        return f"正文命中 {tech_count} 次內建技術詞，約佔詞數 {tech_share:.0%}。"
    if code_switch_count:
        return f"正文有 {code_switch_count} 處弱動詞接英文詞。"
    if han_words and english_words >= 2:
        english_share = english_words / word_count
        if english_share >= _TECH_ENGLISH_SHARE:
            return f"中英夾雜的正文中，英文詞約佔詞數 {english_share:.0%}。"

    matched_terms = []
    for terms in _ZH_TECH_PROFILE_GROUPS:
        term = next((term for term in terms if term in prose), None)
        if term is not None:
            matched_terms.append(term)
    if len(matched_terms) >= 2:
        evidence = "、".join(f"「{term}」" for term in matched_terms)
        return f"正文使用{evidence}等多類技術詞。"
    return None


def _social_profile_reason(prose: str, tokens: Sequence[Token]) -> str | None:
    particles = list(
        dict.fromkeys(
            token.surface
            for token in tokens
            if len(token.surface) == 1 and _SOCIAL_PARTICLE.match(prose, token.start_char)
        )
    )
    if len(particles) >= 2:
        evidence = "、".join(f"「{particle}」" for particle in particles)
        return f"正文使用{evidence}等句尾語氣詞。"
    emoji = _EMOJI.search(prose)
    if particles and emoji:
        return f"正文有表情符號 {emoji[0]} 和句尾語氣詞「{particles[0]}」。"
    return None


def _suggest_profile(
    prose: str,
    tokens: Sequence[Token],
    sentence_ends: list[int],
    tech_terms: Iterable[str],
    code_switch_count: int,
    profile_override: str | None,
    fallback_profile: str,
) -> tuple[str, str]:
    configured = resolve_profile({"default_profile": fallback_profile}, override=profile_override)
    if profile_override is not None:
        return configured, f"依 --profile 指定採用 {configured}。"

    tech_reason = _technical_profile_reason(prose, tokens, tech_terms, code_switch_count)
    social_reason = _social_profile_reason(prose, tokens)
    if tech_reason and social_reason:
        return configured, f"{tech_reason}{social_reason}兩種線索並存，採用設定值 {configured}。"
    if tech_reason:
        return "tech", tech_reason
    if social_reason:
        return "social", social_reason

    lengths = []
    start = 0
    for end in sentence_ends:
        length = len(_HAN.findall(prose, start, end))
        if length:
            lengths.append(length)
        start = end
    total = sum(lengths)
    if total >= _MIN_HAN_CHARACTERS:
        average = total / len(lengths)
        if average <= _SOCIAL_SENTENCE_LENGTH:
            return "social", f"正文偏短句，平均每句 {average:.1f} 個中文字。"
        if average >= _ESSAY_SENTENCE_LENGTH:
            return "essay", f"正文偏長句，平均每句 {average:.1f} 個中文字。"
    return configured, f"正文的語體線索不足，採用設定值 {configured}。"


def preflight(
    text: str,
    *,
    source_type: Literal["file", "stdin"],
    target_id: str,
    whitelist: Sequence[dict],
    profile_override: str | None = None,
    fallback_profile: str = DEFAULT_PROFILE,
    tokenizer: TokenizerAdapter | None = None,
) -> PreflightPayload:
    """分析原文與已合併白名單，產生 §4.2 的預檢資料。

    由呼叫端提供來源識別（例如 repo 相對路徑或 stdin）、明確的 CLI 語體
    覆寫與設定層解析出的備援語體。以原文範圍套用白名單，讓暫用詞也能豁免，
    並避免將單篇保護詞註冊到 Jieba 的共用詞典。
    """
    normalized = normalize(text, tokenizer)
    prose = visible_prose(text, normalized.mask_regions)
    lexicons = load_default_lexicons()
    whitelist_hits = whitelist_matches(prose, (entry["term"] for entry in whitelist))
    code_switch_hits = _code_switch_hits(
        prose, normalized.tokens, (entry["term"] for entry in lexicons["weak_verbs"])
    )
    sentence_ends = _sentence_ends(prose)
    profile, reason = _suggest_profile(
        prose,
        normalized.tokens,
        sentence_ends,
        (entry["term"] for entry in lexicons["tech_whitelist"]),
        len(code_switch_hits),
        profile_override,
        fallback_profile,
    )
    return {
        "mode": "L5_PREFLIGHT",
        "source_type": source_type,
        "target_id": target_id,
        "content_hash": content_hash(text),
        "suggested_profile": profile,
        "profile_reason": reason,
        "active_whitelist_terms": list(dict.fromkeys(hit[0] for hit in whitelist_hits)),
        "suspect_terms_for_review": _review_terms(
            text, prose, normalized.tokens, code_switch_hits, whitelist_hits, sentence_ends
        ),
    }
