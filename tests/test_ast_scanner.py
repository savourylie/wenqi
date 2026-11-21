"""TICKET-006：命令列、診斷座標與規則掛載。"""

import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from engine import state_manager as state
from engine.ast_scanner import lint
from engine.rules import l1_vitality, l3_logic


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = "在系統重構的過程當中，團隊對檢索模組的高可用性進行了詳細的評估。"


@pytest.fixture
def state_dir(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("USERPROFILE", str(fake_home))
    return fake_home / ".config" / "wenqi"


@pytest.fixture
def repo(tmp_path):
    repo_root = tmp_path / "articles"
    subprocess.run(["git", "init", "-q", str(repo_root)], check=True, capture_output=True)
    return repo_root


def run_cli(*args, text=None, cwd=ROOT, module=False):
    entry = ["-m", "engine.ast_scanner"] if module else [str(ROOT / "engine" / "ast_scanner.py")]
    return subprocess.run(
        [sys.executable, *entry, *map(str, args)],
        input=text.encode("utf-8") if text is not None else None,
        cwd=cwd,
        capture_output=True,
        timeout=20,
    )


def payload(result):
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    return json.loads(result.stdout)


def test_preflight_file_and_stdin(state_dir, repo):
    article = repo / "稿件.md"
    text = "我們對小模型進行 A/B testing，提升資料存取的局部性。"
    article.write_text(text, encoding="utf-8")

    file_result = payload(run_cli("--mode", "preflight", "--file", article, cwd=repo))
    assert set(file_result) == {
        "mode", "source_type", "target_id", "content_hash", "suggested_profile",
        "profile_reason", "active_whitelist_terms", "suspect_terms_for_review",
    }
    assert file_result["mode"] == "L5_PREFLIGHT"
    assert (file_result["source_type"], file_result["target_id"]) == ("file", "稿件.md")
    assert file_result["content_hash"] == state.content_hash(text)
    assert {item["term"] for item in file_result["suspect_terms_for_review"]} == {
        "局部性", "進行 A/B testing",
    }

    stdin_result = payload(run_cli(
        "--mode", "preflight", "--stdin", "--profile", "essay",
        "--ephemeral-whitelist", "局部性,進行 A/B testing", text=text, module=True,
    ))
    assert (stdin_result["source_type"], stdin_result["target_id"]) == ("stdin", "stdin")
    assert stdin_result["content_hash"] == file_result["content_hash"]
    assert stdin_result["suggested_profile"] == "essay"
    assert "--profile" in stdin_result["profile_reason"]
    assert set(stdin_result["active_whitelist_terms"]) == {"局部性", "進行 A/B testing"}
    assert stdin_result["suspect_terms_for_review"] == []
    assert not (state_dir / "workspaces").exists()
    assert not {"局部性", "進行 A/B testing"} & {
        item["term"] for item in state.load_global_config()["global_whitelist"]
    }


def test_update_state_writes_both_scopes_and_aligns_a_renamed_article(state_dir, repo):
    article = repo / "draft.md"
    text = "他跑的很快，接著進行 A/B testing。"
    original = text.encode("utf-8")
    article.write_bytes(original)
    args = (
        "--mode", "update-state", "--file", article,
        "--add-global-whitelist", "確認術語:nz,另一術語:n",
        "--add-local-whitelist", "進行 A/B testing:nz",
    )

    initial = payload(run_cli(*args))
    assert initial == {
        "mode": "UPDATE_STATE",
        "target_id": "draft.md",
        "updated_global_whitelist": [
            {"term": "確認術語", "pos": "nz"}, {"term": "另一術語", "pos": "n"},
        ],
        "updated_local_whitelist": [{"term": "進行 A/B testing", "pos": "nz"}],
    }
    assert payload(run_cli(*args)) == initial
    renamed = article.rename(repo / "published.md")
    payload(run_cli(
        "--mode", "update-state", "--file", renamed,
        "--add-local-whitelist", "單篇術語:nz",
    ))
    workspace = state.load_workspace(repo)
    assert set(workspace["documents"]) == {"published.md"}
    assert workspace["documents"]["published.md"]["content_hash"] == state.content_hash(text)
    assert workspace["documents"]["published.md"]["local_whitelist"] == [
        {"term": "進行 A/B testing", "pos": "nz"}, {"term": "單篇術語", "pos": "nz"},
    ]
    assert renamed.read_bytes() == original
    result = payload(run_cli("--mode", "lint", "--file", renamed))
    diagnostic, = result["diagnostics"]
    assert diagnostic["frozen_whitelist_hits"] == ["進行 A/B testing"]
    assert "進行 A/B testing" in diagnostic["must_keep_content_words"]


@pytest.mark.parametrize(
    "args",
    [
        ("--mode", "lint"),
        ("--mode", "lint", "--stdin", "--file", "any.md"),
        ("--mode", "preflight", "--stdin", "--add-global-whitelist", "不應寫入:nz"),
        ("--mode", "update-state", "--stdin", "--add-local-whitelist", "不應寫入:nz",
         "--add-global-whitelist", "也不應寫入:nz"),
        ("--mode", "update-state", "--add-global-whitelist", "缺詞性"),
        ("--mode", "update-state", "--add-global-whitelist", "重複:n,重複:nz"),
    ],
)
def test_invalid_requests_keep_stdout_and_state_empty(state_dir, args):
    result = run_cli(*args, text="")
    assert result.returncode == 2
    assert result.stdout == b""
    assert result.stderr
    assert not state_dir.exists()


def test_concurrent_global_updates_preserve_every_term(state_dir):
    terms = ["測試甲", "測試乙", "測試丙", "測試丁"]

    def update(term):
        return payload(run_cli("--mode", "update-state", "--add-global-whitelist", f"{term}:nz"))

    with ThreadPoolExecutor(max_workers=len(terms)) as pool:
        results = list(pool.map(update, terms))
    for term, result in zip(terms, results):
        assert result["target_id"] is None
        assert result["updated_global_whitelist"] == [{"term": term, "pos": "nz"}]
    assert set(terms) <= {item["term"] for item in state.load_global_config()["global_whitelist"]}
    assert not (state_dir / "workspaces").exists()


def test_lint_file_and_stdin_preserve_masked_document_coordinates(state_dir, repo):
    article = repo / "article.md"
    text = (
        "---\r\n標題: 前置設定。\r\n---\r\n"
        "我們先核對前文。\r\n"
        "~~~text\r\n跑的很快。這是程式碼！\r\n~~~\r\n"
        "這是同一行的前一句。高可用性很重要，\r\n"
        "他跑的很快 \x60略過。這是行內程式碼\x60。\r\n\r\n"
        "這是下一段"
    )
    # 傳送 bytes 可保留 Windows 格式的 CRLF。
    article.write_bytes(text.encode("utf-8"))
    file_result = payload(run_cli("--mode", "lint", "--file", article, "--profile", "social"))
    stdin_result = payload(run_cli("--mode", "lint", "--stdin", "--profile", "social", text=text))
    assert file_result == stdin_result
    assert file_result["mode"] == "LINT"
    assert file_result["requested_layer"] == "ALL"
    assert file_result["effective_profile"] == "social"
    assert file_result["thresholds_applied"] == {"max_pre_modifier_len": 12, "max_clause_len": 16}
    assert file_result["summary"] == {
        "total_sentences": 4, "flagged_sentences": 1,
        "issue_counts": {"L0": 1, "L1": 0, "L2": 0, "L3": 0, "L4": 0},
    }
    diagnostic, = file_result["diagnostics"]
    assert set(diagnostic) == {
        "sentence_id", "line_number", "context_before", "target_sentence", "context_after",
        "frozen_whitelist_hits", "must_keep_content_words", "de_normalization_map", "issues",
    }
    assert diagnostic["sentence_id"] == "L8_S2"
    assert diagnostic["line_number"] == 8
    assert diagnostic["target_sentence"] == text[text.index("高可用性"):text.index("\r\n\r\n這是")]
    assert diagnostic["context_before"] == "這是同一行的前一句。"
    assert diagnostic["context_after"] == "這是下一段"
    assert diagnostic["frozen_whitelist_hits"] == ["高可用性"]
    assert {"高可用性", "跑", "重要"} <= set(diagnostic["must_keep_content_words"])
    typo = diagnostic["target_sentence"].index("跑的") + 1
    assert diagnostic["de_normalization_map"] == [
        {"char_idx": typo, "surface": "的", "true_role": "DE_COMP"},
    ]
    issue, = diagnostic["issues"]
    assert issue["rule_id"] == "L0_TYPO_DE_COMP"
    assert issue["char_idx"] == typo
    assert issue["suggestion"] == "得"
    assert not (state_dir / "workspaces").exists()


def test_lint_profile_priority_and_empty_layer(state_dir, repo):
    article = repo / "draft.md"
    text = "他跑的很快。"
    article.write_text(text, encoding="utf-8")
    config = state.load_global_config()
    config["default_profile"] = "essay"
    config["profiles"]["tech"]["max_clause_len"] = 27
    state.save_global_config(config)
    workspace = state.add_local_whitelist(repo, "draft.md", [], state.content_hash(text))
    workspace["repo_defaults"]["profile"] = "social"
    workspace["documents"]["draft.md"]["profile"] = "tech"
    state.save_workspace(workspace, repo)
    args = ("--mode", "lint", "--layer", "L1", "--file", article)

    document = payload(run_cli(*args))
    assert document["effective_profile"] == "tech"
    assert document["thresholds_applied"]["max_clause_len"] == 27
    assert document["diagnostics"] == []
    assert document["summary"] == {
        "total_sentences": 1, "flagged_sentences": 0,
        "issue_counts": {"L1": 0, "L2": 0, "L3": 0, "L4": 0},
    }
    assert payload(run_cli(*args, "--profile", "essay"))["effective_profile"] == "essay"
    workspace["documents"]["draft.md"]["profile"] = None
    state.save_workspace(workspace, repo)
    assert payload(run_cli(*args))["effective_profile"] == "social"
    stdin_result = payload(run_cli("--mode", "lint", "--stdin", text=text))
    assert stdin_result["effective_profile"] == "essay"


def test_lint_registered_layers_share_one_diagnostic_and_filter_rules(state_dir, monkeypatch):
    text = "\n" * 12 + f"我們先從檢索層開始看起。\n{EXAMPLE}\n評估結果顯示延遲降低了三成。"
    settings = state.load_settings_for_stdin(text)
    settings["disabled_rules"]["document"] = ["L1_DISABLED_ON_DOCUMENT"]
    calls = []

    def make_issue(layer, rule_id, priority, span):
        return {
            "layer": layer, "rule_id": rule_id, "priority": priority, "span": span,
            "pos_pattern": "v + vn", "theoretical_basis": "測試用理論依據",
            "instruction": "測試用轉換指令",
        }

    def scan_l1(tokens, sentence_ctx, profile):
        calls.append("L1")
        if sentence_ctx.text != EXAMPLE:
            return []
        assert [sentence_ctx.text[start:end] for start, end in sentence_ctx.clause_spans] == [
            "在系統重構的過程當中", "團隊對檢索模組的高可用性進行了詳細的評估",
        ]
        assert all(sentence_ctx.text[token.start_char:token.end_char] == token.surface
                   for token in tokens)
        assert profile["disabled_rules"] == ["L3_SHORT_CAUSAL_DROP", "L1_DISABLED_ON_DOCUMENT"]
        span = "對檢索模組的高可用性進行了詳細的評估"
        return [make_issue("L1", "L1_WEAK_VERB_NOMINALIZATION", 2, span),
                make_issue("L1", "L1_DISABLED_ON_DOCUMENT", 1, span)]

    def scan_l3(tokens, sentence_ctx, profile):
        calls.append("L3")
        if sentence_ctx.text != EXAMPLE:
            return []
        span = "在系統重構的過程當中"
        return [make_issue("L3", "L3_PREPOSITIONAL_FRAME", 1, span),
                make_issue("L3", "L3_SHORT_CAUSAL_DROP", 1, span)]

    monkeypatch.setattr(l1_vitality, "scan", scan_l1, raising=False)
    monkeypatch.setattr(l3_logic, "scan", scan_l3, raising=False)
    result = lint(text, settings)
    diagnostic, = result["diagnostics"]
    assert diagnostic["sentence_id"] == "L14_S1"
    assert diagnostic["target_sentence"] == EXAMPLE
    assert diagnostic["context_before"] == "我們先從檢索層開始看起。"
    assert diagnostic["context_after"] == "評估結果顯示延遲降低了三成。"
    assert diagnostic["de_normalization_map"] == [
        {"char_idx": index, "surface": "的", "true_role": "DE_ATTR"} for index in (5, 18, 28)
    ]
    assert diagnostic["must_keep_content_words"] == [
        "系統", "重構", "團隊", "檢索", "模組", "高可用性", "評估",
    ]
    assert [issue["layer"] for issue in diagnostic["issues"]] == ["L3", "L1"]
    assert result["summary"] == {
        "total_sentences": 3, "flagged_sentences": 1,
        "issue_counts": {"L1": 1, "L2": 0, "L3": 1, "L4": 0},
    }
    calls.clear()
    l1_only = lint(EXAMPLE, settings, requested_layer="L1")
    assert calls == ["L1"]
    assert l1_only["summary"]["total_sentences"] == 1
    assert [issue["layer"] for issue in l1_only["diagnostics"][0]["issues"]] == ["L1"]


def test_lint_l1_cli_uses_rules_and_ephemeral_whitelist(state_dir):
    text = "他不被准許入學。團隊進行 Fine-tuning。"
    result = payload(run_cli("--mode", "lint", "--layer", "L1", "--stdin", text=text))
    first, second = result["diagnostics"]
    issue, = first["issues"]
    assert (issue["rule_id"], issue["char_idx"], issue["span"]) == ("L1_PASSIVE_BEI", 1, "不被准許")
    assert "未獲准" in issue["instruction"]
    assert first["must_keep_content_words"] == ["入學"]
    assert second["issues"][0]["severity"] == "info"
    assert result["summary"]["issue_counts"]["L1"] == 2

    protected = payload(run_cli(
        "--mode", "lint", "--layer", "L1", "--stdin",
        "--ephemeral-whitelist", "准許,進行 Fine-tuning", text=text,
    ))
    assert protected["diagnostics"] == []
    assert protected["summary"]["flagged_sentences"] == 0


def test_l5_preflight_then_lint_cli_golden_cases_with_l2_and_all(state_dir):
    text = (
        "老師苦口婆心的勸了那個長得像你兄弟說話也有點像他的陌生男人半天，但他還是跑的很快。\n"
        "這套架構比舊版起步更早及邁步更快，在灰暗的淒冷的天空下具有很高的可讀性。"
    )
    review = payload(run_cli("--mode", "preflight", "--stdin", text=text))
    assert review["mode"] == "L5_PREFLIGHT"
    assert review["content_hash"] == state.content_hash(text)
    assert "可讀性" in {item["term"] for item in review["suspect_terms_for_review"]}

    # Golden Cases 的作者裁決採散文語體，「可讀性」交給 L1 診斷。
    args = ("--mode", "lint", "--stdin", "--profile", "essay", "--layer")
    l2 = payload(run_cli(*args, "L2", text=text))
    combined = payload(run_cli(*args, "ALL", text=text))
    l2_rules = [
        "L2_ADVERB_DI_OVERUSE", "L2_LEFT_BRANCH_OVERLOAD", "L2_DE_CHAIN_NOISE",
    ]

    def issues_from(result):
        return [issue for diagnostic in result["diagnostics"] for issue in diagnostic["issues"]]

    assert l2["thresholds_applied"]["max_pre_modifier_len"] == 12
    assert l2["summary"]["issue_counts"] == {"L1": 0, "L2": 3, "L3": 0, "L4": 0}
    assert [issue["rule_id"] for issue in issues_from(l2)] == l2_rules
    all_issues = issues_from(combined)
    assert [issue for issue in all_issues if issue["layer"] == "L2"] == issues_from(l2)
    assert {"L0_TYPO_DE_COMP", "L1_PSEUDO_JARGON"} <= {issue["rule_id"] for issue in all_issues}


def test_l5_preflight_then_l2_applies_the_confirmed_title(state_dir):
    title = "大地的脈搏"
    text = f"他讀{title}的作者的文章。"
    review = payload(run_cli("--mode", "preflight", "--stdin", text=text))
    assert review["mode"] == "L5_PREFLIGHT"
    assert title not in review["active_whitelist_terms"]

    args = ("--mode", "lint", "--layer", "L2", "--stdin", "--profile", review["suggested_profile"])
    before = payload(run_cli(*args, text=text))
    confirmed = payload(run_cli(*args, "--ephemeral-whitelist", title, text=text))
    assert before["summary"]["issue_counts"]["L2"] == 1
    assert confirmed["summary"]["issue_counts"]["L2"] == 0
    assert confirmed["diagnostics"] == []


def test_l5_preflight_then_l4_cli_respects_the_authors_decisions(state_dir):
    golden = "由於他的收入的減少，使得他的生活方式被徹底改變了。"
    text = f"{golden}\n河溝裏傳出它們焦急的叫聲。"
    results = []
    for layer in ("L4", "ALL"):
        review = payload(run_cli("--mode", "preflight", "--stdin", text=text))
        assert review["mode"] == "L5_PREFLIGHT"
        assert review["content_hash"] == state.content_hash(text)
        # 本題採散文語體，作者核可「它們」暫時凍結。
        result = payload(run_cli(
            "--mode", "lint", "--stdin", "--layer", layer, "--profile", "essay",
            "--ephemeral-whitelist", "它們", text=text,
        ))
        assert result["effective_profile"] == "essay"
        assert result["summary"]["issue_counts"]["L4"] == 1
        results.append([
            (diagnostic["target_sentence"], issue)
            for diagnostic in result["diagnostics"] for issue in diagnostic["issues"]
            if issue["layer"] == "L4"
        ])

    assert results[0] == results[1]
    (sentence, issue), = results[0]
    assert sentence == golden
    assert (issue["rule_id"], issue["char_idx"], issue["span"]) == (
        "L4_REDUNDANT_PRONOUNS", golden.rindex("他的"), "他的",
    )


def test_lint_keeps_unpunctuated_prose_across_block_boundaries(state_dir):
    text = "> 引文應略過。\n第一段沒句號\n~~~\n略過！\n~~~\n第二段沒句號\n\n第三段。"
    result = payload(run_cli("--mode", "lint", "--stdin", text=text))
    assert result["summary"]["total_sentences"] == 3
    assert result["diagnostics"] == []
