"""外部 36 題 L1 題庫的回歸基準（tests/fixtures/l1_question_bank.json）。

題庫原為外部複驗資產，收進 repo 後以 pytest 重跑：命中須規則、span、severity
全同，禁命中不得重疊，零診斷對照須全句無診斷。L1-17/18/29 是無靈主語子句主語
的已知缺口（#007 As-Built 2026-11-20），以 strict xfail 標記；規則擴充後若開始
通過，會強制移除標記。
"""

import json
import re
from pathlib import Path

import pytest

from engine import load_default_lexicons
from engine.ast_scanner import lint
from engine.state_manager import DEFAULT_PROFILES


BANK = json.loads(
    (Path(__file__).parent / "fixtures" / "l1_question_bank.json").read_text(encoding="utf-8")
)


def scan_case(case):
    # 對照 CLI 冷啟動：全域白名單即內建技術詞，暫用詞僅作用於本題。
    profile = case["profile"]
    settings = {
        "effective_profile": profile,
        "profile_config": DEFAULT_PROFILES[profile],
        "whitelist": load_default_lexicons()["tech_whitelist"] + [
            {"term": term, "pos": "nz"} for term in case["ephemeral_whitelist"]
        ],
        "disabled_rules": {"profile": DEFAULT_PROFILES[profile]["disabled_rules"], "document": []},
    }
    return lint(case["text"], settings, requested_layer="L1")


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
    assert len(BANK) == 36
    for case in BANK:
        marks = []
        if case.get("known_gap"):
            marks.append(pytest.mark.xfail(strict=True, reason=case["known_gap"]))
        yield pytest.param(case, id=case["id"], marks=marks)


@pytest.mark.parametrize("case", list(_params()))
def test_question_bank_case(case):
    text = case["text"]
    payload = scan_case(case)
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
