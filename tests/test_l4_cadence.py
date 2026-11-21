"""TICKET-010：L5 預檢、作者裁決與 L4 節奏診斷。"""

import pytest

from engine import state_manager as state
from engine.ast_scanner import lint
from engine.rules.l5_preflight import preflight


BREATH = "L4_CLAUSE_BREATH_OVERLOAD"
PRONOUNS = "L4_REDUNDANT_PRONOUNS"
BLOAT = "L4_EXISTENTIAL_COPULA_BLOAT"
ENDING = "L4_WEAK_ENDING_VERBOSE_IDIOM"
GOLDEN_CASE_3 = "由於他的收入的減少，使得他的生活方式被徹底改變了。"


@pytest.fixture
def scan_case(tmp_path):
    def scan(text, *, profile, ephemeral_whitelist=(), disabled=(), layer="L4"):
        initial = state.load_settings_for_stdin(text, state_dir=tmp_path)
        review = preflight(
            text, source_type="stdin", target_id="stdin", whitelist=initial["whitelist"],
            fallback_profile=initial["effective_profile"],
        )
        assert review["mode"] == "L5_PREFLIGHT"
        # 語體與暫用詞代表本題作者裁決，其他候選術語留待確認。
        settings = state.load_settings_for_stdin(
            text, profile_override=profile, ephemeral_terms=ephemeral_whitelist, state_dir=tmp_path,
        )
        settings["disabled_rules"]["document"] = list(disabled)
        assert settings["content_hash"] == review["content_hash"]
        result = lint(text, settings, requested_layer=layer)
        assert result["effective_profile"] == profile
        for diagnostic in result["diagnostics"]:
            sentence = diagnostic["target_sentence"]
            for issue in diagnostic["issues"]:
                if issue["layer"] != "L4":
                    continue
                start = issue["char_idx"]
                assert sentence[start:start + len(issue["span"])] == issue["span"]
                assert issue["priority"] == 2
                assert issue["pos_pattern"] and issue["instruction"] and issue["theoretical_basis"]
                assert "_replaceable_token_starts" not in issue
        return result

    return scan


def issues(result, rule=None):
    return [
        issue for diagnostic in result["diagnostics"] for issue in diagnostic["issues"]
        if issue["layer"] == "L4" and (rule is None or issue["rule_id"] == rule)
    ]


@pytest.mark.parametrize(("profile", "limit"), [("tech", 24), ("essay", 20), ("social", 16)])
def test_breath_counts_only_visible_han_characters(scan_case, profile, limit):
    suffix = " API 2026 \x60被遮罩的假句。它們\x60。"
    assert issues(scan_case("山" * limit + suffix, profile=profile)) == []
    issue, = issues(scan_case("山" * (limit + 1) + suffix, profile=profile), BREATH)
    assert issue["pos_pattern"] == f"漢字數 {limit + 1} > {limit}"
    assert "suggested_breakpoint" not in issue


def test_connector_breakpoint_and_span_use_original_sentence_coordinates(scan_case):
    clause = "團隊逐一核對各地服務節點的設定 API \x60然而它們藏在程式碼。🧪\x60 接著修正備援路由"
    sentence = f"🧪備註，{clause}。"
    result = scan_case(f"上一句。\n{sentence}", profile="essay", ephemeral_whitelist=("備援路由",))
    diagnostic, = result["diagnostics"]
    assert diagnostic["target_sentence"] == sentence
    assert diagnostic["line_number"] == 2
    issue, = issues(result)
    assert (issue["rule_id"], issue["span"]) == (BREATH, clause)
    assert issue["char_idx"] == sentence.index("團隊")
    assert issue["suggested_breakpoint"] == sentence.index("接著")
    assert diagnostic["frozen_whitelist_hits"] == ["備援路由"]
    assert "備援路由" in issue["instruction"]


@pytest.mark.parametrize(("clause", "action"), [
    ("工程師核對北部各地服務節點的路由紀錄刪除無效封包", "刪除"),
    ("調查小組逐一核對去年各縣市的校舍完工紀錄抽查補助款流向", "抽查"),
])
def test_breath_uses_second_action_without_connector(scan_case, clause, action):
    issue, = issues(scan_case(clause + "。", profile="essay"), BREATH)
    assert issue["suggested_breakpoint"] == clause.index(action)


@pytest.mark.parametrize(("clause", "next_phrase"), [
    ("系統在部署完成後會自動檢查設定並回報錯誤結果給團隊", "會自動檢查設定"),
    (
        "系統在部署完成後自動檢查所有設定並回報 \x60config，檢查\x60 錯誤結果給團隊看 version 2 on 3 machines",
        "自動檢查所有設定",
    ),
    ("系統在部署完成後三天自動檢查所有設定並回報錯誤結果", "並回報"),
])
def test_breath_keeps_time_phrase_and_action_modifiers_together(scan_case, clause, next_phrase):
    issue, = issues(scan_case(clause + "。", profile="tech"), BREATH)
    assert issue["span"] == clause
    assert issue["suggested_breakpoint"] == clause.index(next_phrase)


def test_breath_does_not_split_in_the_middle_of_an_attributive_time_frame(scan_case):
    text = "工程師仔細檢查在部署完成後自動產生的各區回報與設定差異。"
    issue, = issues(scan_case(text, profile="essay"), BREATH)
    assert issue.get("suggested_breakpoint") != text.index("自動產生")


def test_breath_recognizes_actions_with_objects_despite_adverb_tags(scan_case):
    text = "背景服務每小時同步遠端主機設定檔更新本機快取的內容。"
    issue, = issues(scan_case(text, profile="tech"), BREATH)
    assert issue["suggested_breakpoint"] == text.index("更新")

    frozen = scan_case(text, profile="tech", ephemeral_whitelist=("更新本機快取",))
    issue, = issues(frozen, BREATH)
    assert "suggested_breakpoint" not in issue


@pytest.mark.parametrize("clause", [
    "團隊先把所有還沒交付的設備校正紀錄整理成冊",
    "團隊遍查先前留存的完整設備校正紀錄彙整各區回報",
    "團隊逐一核對所有服務節點的設定調整整套備援路由",
    "團隊核對原本存放在舊倉庫的所有備品銷毀過期試劑",
    "背景服務每小時同步更新遠端主機設定檔的完整內容",
])
def test_breath_omits_breakpoint_when_only_candidates_split_phrases(scan_case, clause):
    issue, = issues(scan_case(clause + "。", profile="essay"), BREATH)
    assert issue["span"] == clause
    assert "suggested_breakpoint" not in issue
    assert "另找" in issue["instruction"]


@pytest.mark.parametrize(("text", "span"), [
    ("他的收入的減少改變了他的生活方式。", "他的"),
    ("河溝裏傳出它們焦急的叫聲。", "它們"),
    ("最後的鴿群……遂過早地飛回它們溫暖的木舍。", "它們"),
    ("他先讀報告，他再找同事協助。", "他"),
    ("我先備份，我再更新。", "我"),
    ("我們的目標很明確，我們的規劃也逐步成形。", "我們的"),
    ("王明向李華提到他的方案，接著補充他的估算。", "他的"),
    ("他拿起他的報告再檢查他的簽名。", "他的"),
])
def test_pronouns_mark_the_removable_occurrence(scan_case, text, span):
    issue, = issues(scan_case(text, profile="essay"), PRONOUNS)
    assert (issue["span"], issue["char_idx"]) == (span, text.rindex(span))
    if span != "它們":
        assert "確認" in issue["instruction"] and "指涉相同" in issue["instruction"]


@pytest.mark.parametrize("text", [
    "他因為收入減少，改變了生活方式。",
    "遂過早飛回溫暖的木舍。",
    "河溝裏傳出焦急的叫聲。",
    "工程師拿出他的紀錄，設計師也拿出他的報告。",
    "王明交出他的報告，李華交出他的報告。",
    "工程師拿出他的紀錄，另一位工程師也拿出他的報告。",
    "我讀過他的信，老師也讀過他的信。",
    "他讀完整份報告。他還想看看其他問題。",
    "我的計畫看似周詳，我的預算卻很有限。",
    "他們交換了意見，其他人只做筆記。",
])
def test_pronouns_respect_topic_switches_and_sentence_boundaries(scan_case, text):
    assert issues(scan_case(text, profile="essay"), PRONOUNS) == []


def test_pronouns_keep_the_person_affected_by_a_causative(scan_case):
    text = "他原本想直接回家然而巷口麵包香讓他停下腳步。"
    issue, = issues(scan_case(text, profile="essay"))
    assert issue["rule_id"] == BREATH
    assert issue["suggested_breakpoint"] == text.index("然而")


def test_whitelisted_rewrite_targets_are_exempt(scan_case):
    text = "河溝裏傳出它們焦急的叫聲。總的來說，問題不大。"
    unprotected = scan_case(text, profile="essay")
    assert {issue["rule_id"] for issue in issues(unprotected)} == {PRONOUNS, ENDING}
    result = scan_case(text, profile="essay", ephemeral_whitelist=("它們", "總的來說"))
    assert issues(result) == []


def test_inanimate_possessive_span_includes_de(scan_case):
    issue, = issues(scan_case("這些資料讓人看見它們的細節。", profile="essay"), PRONOUNS)
    assert issue["span"] == "它們的"
    assert "省略「它們的」" in issue["instruction"]


@pytest.mark.parametrize(("text", "span", "suggestion"), [
    ("有很多問題存在。", "有很多問題存在", "問題很多"),
    ("有兩起事故發生。", "有兩起事故發生", "發生"),
    ("有新的錯誤出現。", "有新的錯誤出現", "出現"),
    ("留言區有好多鼓勵出現。", "有好多鼓勵出現", "好多鼓勵"),
    ("基於這個原因，我們調整了計畫。", "基於這個原因", "因此"),
    ("基於上述的理由，我們調整了計畫。", "基於上述的理由", "為此"),
    ("這套架構是很穩定的。", "是很穩定的", "很穩定"),
    ("這套架構是可靠的。", "是可靠的", "可靠"),
    ("這個功能是很好用的。", "是很好用的", "很好用"),
    ("這件事是相當困難的。", "是相當困難的", "相當困難"),
    ("他認為「這是非常好的。」", "是非常好的", "非常好"),
])
def test_bloat_subtypes_preserve_meaning(scan_case, text, span, suggestion):
    issue, = issues(scan_case(text, profile="essay"), BLOAT)
    assert issue["span"] == span
    assert suggestion in issue["instruction"]


@pytest.mark.parametrize(("text", "qualifier", "span"), [
    ("梅雨季的山區午後，常有零星落石事件發生。", "常", "有零星落石事件發生"),
    ("目前已有新的錯誤出現。", "已", "有新的錯誤出現"),
])
def test_bloat_preserves_qualifier_of_fused_existential_head(scan_case, text, qualifier, span):
    result = scan_case(text, profile="essay")
    issue, = issues(result, BLOAT)
    assert issue["span"] == span
    assert issue["char_idx"] == text.index(span)
    assert f"保留「{qualifier}」" in issue["instruction"]

    frozen = scan_case(text, profile="essay", ephemeral_whitelist=(qualifier + "有",))
    assert issues(frozen, BLOAT) == []


@pytest.mark.parametrize("text", [
    "問題很多。",
    "因此，我們調整了計畫。",
    "這套架構很穩定。",
    "舊架構不夠安全，新架構才是可靠的。",
    "這個版本相較之下是安全的。",
    "新架構並不是可靠的。",
    "這套架構總是可靠的。",
    "目前有很多問題不存在。",
    "這是設備常有的問題發生時應遵守的流程。",
    "本研究有證據顯示更多問題正在出現。",
    "他有一次開車發生車禍。",
    "這個功能是工程師完成的。",
])
def test_bloat_exempts_natural_contrast_and_nonmatching_structures(scan_case, text):
    assert issues(scan_case(text, profile="essay"), BLOAT) == []


def test_copula_switch_is_local_to_one_subtype(scan_case):
    text = "這套架構是很穩定的。有很多問題存在。基於上述原因，我們調整了計畫。"
    shells = ["有很多問題存在", "基於上述原因"]
    for profile in ("tech", "essay"):
        assert [issue["span"] for issue in issues(scan_case(text, profile=profile), BLOAT)] == [
            "是很穩定的", *shells,
        ]
    assert [issue["span"] for issue in issues(scan_case(text, profile="social"), BLOAT)] == shells
    disabled = scan_case(text, profile="essay", disabled=("L4_COPULA_SHI_DE",))
    assert [issue["span"] for issue in issues(disabled, BLOAT)] == shells
    assert issues(scan_case(text, profile="essay", disabled=(BLOAT,)), BLOAT) == []


def test_frozen_noun_is_preserved_inside_existence_issue(scan_case):
    result = scan_case("有很多跨區問題存在。", profile="tech", ephemeral_whitelist=("跨區問題",))
    issue, = issues(result, BLOAT)
    assert "跨區問題很多" in issue["instruction"]
    diagnostic, = result["diagnostics"]
    assert "跨區問題" in diagnostic["must_keep_content_words"]
    assert "存在" not in diagnostic["must_keep_content_words"]


@pytest.mark.parametrize(("phrase", "suggestion"), [
    ("不是一句話就能說清楚的", "一言難盡"),
    ("不是一句話就能夠說得清楚的", "一言難盡"),
    ("不是一句話就能說得清楚的", "一言難盡"),
    ("總的來說", "總而言之"),
    ("在很大程度上", "大幅"),
])
def test_verbose_idioms_are_detected_even_before_the_paragraph_end(scan_case, phrase, suggestion):
    result = scan_case(f"原文寫了「{phrase}」。下面還有一段話。", profile="essay")
    issue, = issues(result, ENDING)
    assert issue["span"] == phrase
    assert suggestion in issue["instruction"]


def test_tech_prefers_a_plain_idiom_replacement(scan_case):
    text = "這件事不是一句話就能夠說得清楚的。"
    issue, = issues(scan_case(text, profile="tech"), ENDING)
    assert "很難簡短說清楚" in issue["instruction"]
    assert "一言難盡" not in issue["instruction"]


def test_weak_ending_only_matches_paragraph_final_sentence(scan_case):
    stem = "權限是我們需要注意的一個地方。"
    text = f"{stem}\n接下來看案例。\r\n \r\n{stem}\n\n這項差異是值得去思考的一件事情。"
    result = scan_case(text, profile="tech", ephemeral_whitelist=("注意",))
    ending, closing = issues(result, ENDING)
    assert [diagnostic["line_number"] for diagnostic in result["diagnostics"]] == [4, 6]
    assert ending["span"] == "是我們需要注意的一個地方"
    assert "須注意" in ending["instruction"]
    assert closing["span"] == "是值得去思考的一件事情"
    assert "值得思考" in closing["instruction"]
    assert "注意" in result["diagnostics"][0]["must_keep_content_words"]
    assert "地方" not in result["diagnostics"][0]["must_keep_content_words"]


@pytest.mark.parametrize("text", ["總而言之。", "簡言之。", "這件事一言難盡。", "這項差異值得思考。"])
def test_natural_short_endings_do_not_trigger(scan_case, text):
    assert issues(scan_case(text, profile="essay")) == []


def test_golden_case_3_l4_issue_is_shared_by_single_layer_and_all(scan_case):
    single = scan_case(GOLDEN_CASE_3, profile="essay")
    combined = scan_case(GOLDEN_CASE_3, profile="essay", layer="ALL")
    issue, = issues(single)
    assert issues(combined) == [issue]
    assert (issue["rule_id"], issue["span"], issue["char_idx"]) == (
        PRONOUNS, "他的", GOLDEN_CASE_3.rindex("他的"),
    )
    diagnostic, = combined["diagnostics"]
    assert any(item["rule_id"] == "L3_CAUSAL_MALFORMED" for item in diagnostic["issues"])
    assert combined["summary"]["issue_counts"]["L4"] == 1
