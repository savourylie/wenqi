"""TICKET-008：修飾結構、語體閾值與 L0 詞性標記。"""

import pytest

from engine.ast_scanner import lint
from engine.l0_normalizer import DE_ATTR
from engine.rules import SentenceContext
from engine.rules.l2_branching import scan
from engine.state_manager import DEFAULT_PROFILES
from engine.tokenizer_adapter import Token


LEFT = "L2_LEFT_BRANCH_OVERLOAD"
CHAIN = "L2_DE_CHAIN_NOISE"
ADVERB = "L2_ADVERB_DI_OVERUSE"
GOLDEN_2 = "老師苦口婆心的勸了那個長得像你兄弟說話也有點像他的陌生男人半天，但他還是跑的很快。"
GOLDEN_4 = "這套架構比舊版起步更早及邁步更快，在灰暗的淒冷的天空下具有很高的可讀性。"


def settings(profile="essay", *, whitelist=(), disabled_rules=()):
    return {
        "effective_profile": profile,
        "profile_config": DEFAULT_PROFILES[profile],
        "disabled_rules": {"profile": [], "document": list(disabled_rules)},
        "whitelist": [{"term": term} for term in whitelist],
    }


def l2_issues(text, **options):
    result = lint(text, settings(**options), requested_layer="L2")
    issues = []
    for diagnostic in result["diagnostics"]:
        for issue in diagnostic["issues"]:
            start = issue["char_idx"]
            assert issue["layer"] == "L2"
            assert diagnostic["target_sentence"][start:start + len(issue["span"])] == issue["span"]
            assert issue["pos_pattern"] and issue["theoretical_basis"] and issue["instruction"]
            issues.append(issue)
    assert result["summary"]["issue_counts"]["L2"] == len(issues)
    return issues


@pytest.mark.parametrize(
    ("text", "rule", "span"),
    [
        ("我見到一個長得像你兄弟說話也有點像他的陌生男人。", LEFT,
         "長得像你兄弟說話也有點像他的陌生男人"),
        ("我遇見每天提早出門並且在車站等到傍晚的工程師。", LEFT,
         "每天提早出門並且在車站等到傍晚的工程師"),
        ("項籍是一個身高八尺，力能扛鼎，同時才氣過人的漢子。", LEFT,
         "身高八尺，力能扛鼎，同時才氣過人的漢子"),
        ("李廣是一個高個子，手臂長得好像猿臂，天性就會射箭的人。", LEFT,
         "高個子，手臂長得好像猿臂，天性就會射箭的人"),
        ("高處叢生的灌木，落下參差的斑駁的黑影……彎彎的楊柳的稀疏的倩影。", CHAIN,
         "參差的斑駁的黑影"),
        ("彎彎的楊柳的稀疏的倩影。", CHAIN, "彎彎的楊柳的稀疏的倩影"),
        ("白色的鴨也似有一點煩躁了，有不潔的顏色的都市的河溝裏傳出焦急的叫聲。", CHAIN,
         "白色的鴨"),
        ("白的鴨。", CHAIN, "白的鴨"),
        ("木頭的桌子。", CHAIN, "木頭的桌子"),
        ("一位衰老的、瘋狂的、瞎眼的、被人蔑視的、垂死的君王——", CHAIN,
         "一位衰老的、瘋狂的、瞎眼的、被人蔑視的、垂死的君王——"),
        ("他苦心孤詣地想出一套好辦法來。", ADVERB, "苦心孤詣地想出"),
        ("老師苦口婆心地勸了他半天。", ADVERB, "苦口婆心地勸"),
        ("大家苦中作樂地竟然大唱其民謠。", ADVERB, "苦中作樂地竟然大唱"),
        ("他知其不可為而為之地還是去赴了約。", ADVERB, "知其不可為而為之地還是去赴"),
        ("他知其不可為而為之的還是去赴了約。", ADVERB, "知其不可為而為之的還是去赴"),
        ("他非常仔細地檢查了內容。", ADVERB, "非常仔細地檢查"),
        ("他一步一步地拆開盒子。", ADVERB, "一步一步地拆開"),
        ("他盡心盡力地工作。", ADVERB, "盡心盡力地工作"),
        ("成功地推翻了滿清。", ADVERB, "成功地推翻"),
        ("成功地發明了相對論。", ADVERB, "成功地發明"),
        ("成功地泳渡了直布羅陀海峽。", ADVERB, "成功地泳渡"),
        ("團隊成功地完成計畫。", ADVERB, "成功地完成"),
        ("團隊成功地完成了計畫。", ADVERB, "成功地完成"),
        ("順利地突破了紀錄。", ADVERB, "順利地突破"),
        ("他們終於成功的解決問題。", ADVERB, "成功的解決"),
        ("若有疑慮可以再問，但團隊昨天成功地完成計畫。", ADVERB, "成功地完成"),
        ("他沒有外援就成功地解決問題。", ADVERB, "成功地解決"),
    ],
)
def test_examples_hit_expected_rule_and_original_span(text, rule, span):
    assert (rule, span) in {(issue["rule_id"], issue["span"]) for issue in l2_issues(text)}


@pytest.mark.parametrize(
    "text",
    [
        "我見到一個陌生男人，長得像你兄弟，說話也有點像他。",
        "籍長八尺餘，力能扛鼎，才氣過人。",
        "廣為人長，猿臂，其善射亦天性也。",
        "一位既老且瘋，瞎了眼，為人蔑視，奄奄一息的君王——",
        "我見到一個長得像你兄弟；說話也有點像他的陌生男人。",
        "我遇見一個喜歡測試 \x60每天提早出門並且在車站等到傍晚\x60 的工程師。",
        "落下參差而斑駁的黑影……彎彎的楊柳，投下稀疏的倩影。",
        "白鴨也似有一點煩躁了，顏色不潔的都市河溝裏傳出焦急的叫聲。",
        "都市的髒河溝裏傳出焦急的叫聲。",
        "他苦心孤詣，想出一套好辦法來。老師苦口婆心，勸了他半天。",
        "大家苦中作樂，竟然大唱其民謠。",
        "他知其不可為而為之，還是去赴了約。",
        "推翻了滿清。發明了相對論。泳渡了直布羅陀海峽。",
        "他漸漸地走遠，她悄悄地離開。",
        "我還沒成功地解決問題。",
        "團隊從未真正成功地解決問題。",
        "她會順利地完成計畫。她希望開發者最終成功地解決問題。",
        "明天我們成功地完成計畫。預備在明天成功地完成任務。",
        "如果進展順利，團隊成功地完成計畫後就會發佈。",
        "這是一個成功的發明家。",
        "橫貫公路的再度坍方，是今日的頭條新聞。",
    ],
)
def test_natural_and_incomplete_examples_pass(text):
    assert l2_issues(text) == []


@pytest.mark.parametrize("profile", ["essay", "social", "tech"])
def test_golden_cases_and_profile_switch(profile):
    expected = [ADVERB] if profile == "tech" else [ADVERB, LEFT]
    assert [issue["rule_id"] for issue in l2_issues(GOLDEN_2, profile=profile)] == expected
    assert [issue["rule_id"] for issue in l2_issues(GOLDEN_4, profile=profile)] == [CHAIN]
    assert l2_issues(GOLDEN_4, profile=profile, disabled_rules=[CHAIN]) == []


def test_de_count_stops_at_clause_boundaries_and_ignores_frozen_markers():
    text = "他讀城市的夜的故事，談村子的歷史。"
    assert l2_issues(text) == []
    text = "他讀大地的脈搏的作者的文章。"
    assert [issue["rule_id"] for issue in l2_issues(text)] == [CHAIN]
    assert l2_issues(text, whitelist=["大地的脈搏"]) == []


def test_masked_spans_and_other_success_occurrences_stay_protected():
    text = "\x60成功地推翻了滿清\x60。團隊的成功來自合作，團隊成功地完成計畫。成功地完成計畫。"
    result = lint(text, settings(), requested_layer="L2")
    repeated, standalone = result["diagnostics"]
    first_issue, = repeated["issues"]
    second_issue, = standalone["issues"]
    assert first_issue["span"] == second_issue["span"] == "成功地完成"
    assert first_issue["char_idx"] == repeated["target_sentence"].rindex("成功")
    assert "成功" in repeated["must_keep_content_words"]
    assert "保留「成功」" in first_issue["instruction"]
    assert "成功" not in standalone["must_keep_content_words"]
    assert "_replaceable_token_starts" not in second_issue
    assert l2_issues("團隊成功地完成計畫。", whitelist=["成功地"]) == []


@pytest.mark.parametrize(
    ("limit", "length", "verb_pos", "expected"),
    [(12, 12, "v", []), (12, 13, "v", [LEFT]), (18, 18, "v", []), (18, 19, "vn", [LEFT]),
     (12, 19, "a", []), (16, 17, "v", [LEFT])],
)
def test_threshold_counts_han_only_and_excludes_frozen_de(limit, length, verb_pos, expected):
    # 讀（一字）、甲的乙（兩字）、填充字、定語助詞（一字）是錨點間的字數。
    parts = [
        ("見到", "v", False, ""), ("一個", "m", False, ""),
        ("讀", verb_pos, False, ""), ("veryLongTechnicalIdentifier", "eng", False, ""),
        ("甲的乙", "nz", True, ""), ("文" * (length - 4), "n", False, ""),
        ("的", "uj", False, DE_ATTR), ("人", "n", False, ""),
    ]
    tokens = []
    text = ""
    for surface, pos, frozen, role in parts:
        tokens.append(Token(surface, pos, len(text), len(text) + len(surface), frozen, role))
        text += surface
    context = SentenceContext(text, ((0, len(text)),), True)
    profile = {**DEFAULT_PROFILES["essay"], "name": "essay", "max_pre_modifier_len": limit}

    issues = scan(tokens, context, profile)
    assert [issue["rule_id"] for issue in issues] == expected
    if issues:
        assert issues[0]["span"] == text[len("見到一個"):]
