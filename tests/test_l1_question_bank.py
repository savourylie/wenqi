"""原外部 L1 題庫與 A/B/R 批的回歸基準。

每題先跑 L5 預檢，再依題庫記錄的作者裁決執行 L1。命中須規則、span、severity 全同。
禁命中不得重疊，零診斷對照須全句無診斷。
各題的 known_gap 記錄已知缺口，採 strict xfail，通過時需要移除標記。
"""

import json
import re
from pathlib import Path

import pytest

from engine import state_manager as state
from engine.ast_scanner import lint
from engine.rules.l5_preflight import preflight


FIXTURES = Path(__file__).parent / "fixtures"
BANK_SIZES = {
    "l1_question_bank.json": 36,
    "l1_question_bank_a.json": 36,
    "l1_question_bank_b.json": 60,
    "l1_question_bank_r.json": 60,
}


@pytest.fixture(scope="module")
def review_state_dir(tmp_path_factory):
    return tmp_path_factory.mktemp("l1-question-bank")


def scan_case(case, state_dir):
    text = case["text"]
    before_review = state.load_settings_for_stdin(text, state_dir=state_dir)
    review = preflight(
        text,
        source_type="stdin",
        target_id="stdin",
        whitelist=before_review["whitelist"],
        fallback_profile=before_review["effective_profile"],
    )
    assert review["mode"] == "L5_PREFLIGHT"

    # 題庫的語體與暫用詞是作者裁決。L5 提出的其他候選仍待確認。
    settings = state.load_settings_for_stdin(
        text,
        profile_override=case["profile"],
        ephemeral_terms=case["ephemeral_whitelist"],
        state_dir=state_dir,
    )
    assert settings["content_hash"] == review["content_hash"]
    return lint(text, settings, requested_layer="L1")


def document_issues(text, payload):
    line_starts = [0] + [match.end() for match in re.finditer(r"\r\n|\r|\n", text)]
    cursor = 0
    records = []
    for diagnostic in payload["diagnostics"]:
        sentence = diagnostic["target_sentence"]
        line_start = line_starts[diagnostic["line_number"] - 1]
        base = text.index(sentence, max(line_start, cursor))
        cursor = base + len(sentence)
        for issue in diagnostic["issues"]:
            start = base + issue["char_idx"]
            assert text[start:start + len(issue["span"])] == issue["span"]
            records.append(dict(issue, document_start=start, document_end=start + len(issue["span"])))
    assert len(records) == payload["summary"]["issue_counts"]["L1"]
    return records


def locate(text, check):
    match = list(re.finditer(re.escape(check["span"]), text))[check["occurrence"] - 1]
    return match.start(), match.end()


def overlaps(issue, start, end):
    return issue["document_start"] < end and start < issue["document_end"]


def _params():
    for name, size in BANK_SIZES.items():
        bank = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
        assert len(bank) == size
        for case in bank:
            marks = []
            if case.get("known_gap"):
                marks.append(pytest.mark.xfail(strict=True, reason=case["known_gap"]))
            yield pytest.param(case, id=case["id"], marks=marks)


@pytest.mark.parametrize("case", list(_params()))
def test_question_bank_case(case, review_state_dir):
    text = case["text"]
    payload = scan_case(case, review_state_dir)
    assert payload["effective_profile"] == case["profile"]
    actual = document_issues(text, payload)

    for check in case["must_hit"]:
        start, end = locate(text, check)
        overlapping = [
            issue for issue in actual
            if issue["rule_id"] == check["rule_id"] and overlaps(issue, start, end)
        ]
        assert overlapping, f"未命中 {check['rule_id']}「{check['span']}」"
        exact = next(
            (issue for issue in overlapping
             if (issue["document_start"], issue["document_end"]) == (start, end)),
            None,
        )
        assert exact is not None, (
            f"span 不符：預期「{check['span']}」，實際「{overlapping[0]['span']}」"
        )
        assert exact.get("severity") == check["severity"]

    for check in case["must_skip"]:
        start, end = locate(text, check)
        violations = [
            issue["span"] for issue in actual
            if issue["rule_id"] == check["rule_id"] and overlaps(issue, start, end)
        ]
        assert not violations, f"誤報 {check['rule_id']}：{violations}"

    if not case["must_hit"]:
        assert not actual, f"零診斷對照出現診斷：{[issue['span'] for issue in actual]}"
