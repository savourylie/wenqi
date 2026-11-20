"""TICKET-007，L1 案例庫、豁免及 Scanner 診斷契約。"""

import pytest

from engine import load_default_lexicons
from engine.ast_scanner import lint
from engine.rules.l5_preflight import preflight
from engine.state_manager import DEFAULT_PROFILES


WEAK = "L1_WEAK_VERB_NOMINALIZATION"
EVENT = "L1_EVENT_NOMINALIZATION"
JARGON = "L1_PSEUDO_JARGON"
PLURAL = "L1_REDUNDANT_PLURAL_ZHIYI"
INANIMATE = "L1_INANIMATE_SUBJECT"
PASSIVE = "L1_PASSIVE_BEI"


def scan(text, *, profile="essay", frozen=(), disabled=()):
    settings = {
        "effective_profile": profile,
        "profile_config": DEFAULT_PROFILES[profile],
        "whitelist": load_default_lexicons()["tech_whitelist"] + [
            {"term": term, "pos": "nz"} for term in frozen
        ],
        "disabled_rules": {"profile": DEFAULT_PROFILES[profile]["disabled_rules"], "document": list(disabled)},
    }
    return lint(text, settings, requested_layer="L1")


def issues(result):
    return [issue for sentence in result["diagnostics"] for issue in sentence["issues"]]


@pytest.mark.parametrize(("rule", "text", "fragments"), [
    (WEAK, "本校的校友對社會作出了重大的貢獻。", ("作出了重大的貢獻",)),
    (WEAK, "昨晚的聽眾對訪問教授作出了十分熱烈的反應。", ("作出了十分熱烈的反應",)),
    (WEAK, "我們對國際貿易的問題已經進行了詳細的研究。", ("進行了詳細的研究",)),
    (WEAK, "心理學家在老鼠的身上進行試驗。", ("進行試驗",)),
    (WEAK, "一架客機失事，造成九十八人死亡。", ("造成九十八人死亡",)),
    (EVENT, "橫貫公路的再度坍方，是今日的頭條新聞。", ("橫貫公路的再度坍方",)),
    (EVENT, "書籍的選購，只好委託你了。國語的推行，要靠大家的努力。", ("書籍的選購", "國語的推行")),
    (EVENT, "他們杯葛這種風俗的繼續。", ("這種風俗的繼續",)),
    (EVENT, "誤認這灰暗的淒冷的天空為夜色的來襲，或是也預感到風雨的將至……", ("夜色的來襲", "風雨的將至")),
    (EVENT, "金流閘道的頻繁逾時拖慢了整體結帳流程。", ("金流閘道的頻繁逾時",)),
    (EVENT, "由於講者的臨時請假，講座不得不延後。", ("講者的臨時請假",)),
    (JARGON, "他具有很高的知名度。", ("具有很高的知名度",)),
    (JARGON, "這本傳記的可讀性頗高。", ("可讀性頗高",)),
    (JARGON, "昨晚的演奏頗具可聽性，更具可看性。", ("頗具可聽性", "更具可看性")),
    (JARGON, "這項決策更具前瞻性。", ("更具前瞻性",)),
    (JARGON, "這是難度很高的技巧。", ("難度很高的",)),
    (JARGON, "他不愧為熱情型的人。太專業性的字眼。", ("熱情型的", "太專業性的")),
    (JARGON, "富於愛國主義的精神。", ("愛國主義的精神",)),
    (INANIMATE, "他的收入的減少改變了他的生活方式。", ("他的收入的減少",)),
    (PASSIVE, "我不會被你這句話嚇倒。", ("被你這句話嚇倒",)),
    (PASSIVE, "他被懷疑偷東西。", ("被懷疑",)),
    (PASSIVE, "他這意見不被人們接受。", ("不被人們接受",)),
    (PASSIVE, "他被升為營長。他被選為議長。", ("被升為", "被選為")),
    (PASSIVE, "他不被准許入學。", ("不被准許",)),
    (PASSIVE, "他被指出許多錯誤。他常被詢及該案的真相。", ("被指出", "被詢及")),
    (PLURAL, "人們、民眾們、聽眾們和球員們常說。", ("人們", "民眾們", "聽眾們", "球員們")),
    (PLURAL, "作為竹林七賢之一的劉伶以嗜酒聞名。", ("作為竹林七賢之一的",)),
    (PLURAL, "《紅樓夢》是中國文學的名著之一。李廣乃漢朝名將之一。", ("之一", "之一")),
    (PLURAL, "他是當代最有名氣的人物之一。", ("最有名氣的人物之一",)),
])
def test_case_study_issues(rule, text, fragments):
    result = scan(text)
    matches = [issue["span"] for issue in issues(result) if issue["rule_id"] == rule]
    assert len(matches) == len(fragments)
    assert all(fragment in span for fragment, span in zip(fragments, matches))
    for diagnostic in result["diagnostics"]:
        for issue in diagnostic["issues"]:
            start, span = issue["char_idx"], issue["span"]
            assert diagnostic["target_sentence"][start:start + len(span)] == span
            assert issue["layer"] == "L1"
            assert issue["priority"] > 0
            assert all(issue[field] for field in ("pos_pattern", "theoretical_basis", "instruction"))
            assert "_replaceable_token_starts" not in issue


@pytest.mark.parametrize("text", [
    "本校的校友對社會貢獻很大。",
    "昨晚的聽眾對訪問教授反應十分熱烈。",
    "我們深入研究了國際貿易問題。",
    "心理學家用老鼠做試驗。一架客機失事，死了九十八人。",
    "橫貫公路再度坍方，是今日的頭條新聞。",
    "選購書籍，只好委託你了。推行國語，要靠大家努力。",
    "他們反對保存這種風俗。這是我的建議。",
    "他申請的帳戶已開通。退款申請的處理流程需雙方確認。客服收到退款申請的處理進度。",
    "昨天剛上線的搜尋介面獲得不少好評。",
    "老師苦口婆心的勸了他半天。他看得很清楚。",
    "他很有名。這本傳記引人入勝。這是很難的技巧。",
    "這套架構具有很高的可用性與高可用性。",
    "工具具有可讀性測試功能。",
    "大家常說，劉伶是竹林七賢之一，以嗜酒聞名。",
    "這是三大瓶頸之一。文房四寶之一是硯。丹麥是北歐五國之一。水位達總高的三分之一。",
    "他因為收入減少而改變生活方式。",
    "你這句話嚇不倒我。他有偷東西的嫌疑。",
    "他未獲准入學。他當選為議長。",
    "他被殺。嫌犯被捕。房屋被毀。兩名球員被淘汰。",
])
def test_natural_and_exempt_prose(text):
    # 可用性視為作者已確認的技術用語，與內建的高可用性同受保護。
    assert not issues(scan(text, frozen=("可用性",)))


@pytest.mark.parametrize(("text", "frozen"), [
    ("我們進行了詳細的研究。", "研究"),
    ("我們進行研究。", "進行"),
    ("他具有很高的可讀性。", "可讀性"),
    ("系統具備較高的複雜度。", "複雜度"),
    ("國語的推行，需要大家幫忙。", "國語的推行"),
    ("觀眾們到了。", "觀眾們"),
    ("費用的增加迫使我們改變計畫。", "費用的增加"),
    ("他不被准許入學。", "准許"),
    ("他被選為議長。", "被選為"),
    ("我們進行 Fine-tuning。", "進行 Fine-tuning"),
    ("進行研究，太專業性的字眼常見。", "進行研究，太專業性"),
])
def test_frozen_match_is_exempt(text, frozen):
    assert not issues(scan(text, frozen=(frozen,)))


def test_frozen_phrase_does_not_change_segmentation_in_other_scans():
    text = "國語的推行，需要大家幫忙。"
    baseline, = issues(scan(text))
    assert baseline["rule_id"] == EVENT
    assert not issues(scan(text, frozen=("國語的推行",)))
    assert issues(scan(text)) == [baseline]


def test_golden_case_1_weak_verb_can_include_frozen_operand():
    text = "在系統遷移的過程當中，我們對有關檢索模組的高可用性的問題進行了詳細的研究。"
    diagnostic, = scan(text, profile="tech")["diagnostics"]
    issue, = diagnostic["issues"]
    assert issue["rule_id"] == WEAK
    assert issue["span"] == "對有關檢索模組的高可用性的問題進行了詳細的研究"
    assert "詳加研究" in issue["instruction"]
    assert diagnostic["frozen_whitelist_hits"] == ["高可用性"]
    assert {"高可用性", "研究"} <= set(diagnostic["must_keep_content_words"])


def test_golden_case_3_given_cause_and_passive_have_distinct_issues():
    text = "由於他的收入的減少，使得他的生活方式被徹底改變了。"
    result = scan(text)
    assert [(issue["rule_id"], issue["span"]) for issue in issues(result)] == [
        (EVENT, "他的收入的減少"),
        (PASSIVE, "被徹底改變了"),
    ]
    assert "他的收入減少" in issues(result)[0]["instruction"]
    assert result["summary"]["issue_counts"]["L1"] == 2


def test_golden_case_4_suggests_a_direct_predicate():
    text = "這套架構比舊版起步更早及邁步更快，在灰暗的淒冷的天空下具有很高的可讀性。"
    diagnostic, = scan(text, profile="tech")["diagnostics"]
    issue, = diagnostic["issues"]
    assert (issue["rule_id"], issue["span"]) == (JARGON, "具有很高的可讀性")
    assert "清晰易讀" in issue["instruction"]
    assert "架構" in diagnostic["must_keep_content_words"]
    assert not {"具有", "很高", "可讀性"} & set(diagnostic["must_keep_content_words"])


def test_technical_component_exemption_only_applies_to_tech_profile():
    text = "檢索模組的出現讓使用者更容易查找。"
    assert INANIMATE in {issue["rule_id"] for issue in issues(scan(text))}
    assert INANIMATE not in {issue["rule_id"] for issue in issues(scan(text, profile="tech"))}


def test_event_nominalization_uses_the_normalized_role_for_di():
    diagnostic, = scan("書籍地選購，只好委託你了。")["diagnostics"]
    assert diagnostic["de_normalization_map"] == [
        {"char_idx": 2, "surface": "地", "true_role": "DE_ATTR"},
    ]
    assert [issue["rule_id"] for issue in diagnostic["issues"]] == [EVENT]
    assert "選購書籍" in diagnostic["issues"][0]["instruction"]


@pytest.mark.parametrize("application", ("退款申請", "退費申請"))
def test_event_treats_application_as_a_complete_object(application):
    text = f"{application}的處理，需要客服和財務一起確認。"
    issue, = issues(scan(text, profile="tech"))
    assert (issue["rule_id"], issue["span"], issue["char_idx"]) == (EVENT, f"{application}的處理", 0)
    assert f"處理{application}" in issue["instruction"]
    assert not issues(scan(text, frozen=(application,)))


def test_commute_duration_is_a_complete_noun_phrase_in_both_rules():
    phrase = "通勤時間的增加"
    text = phrase + "讓我開始考慮搬家。"
    found = {issue["rule_id"]: issue for issue in issues(scan(text, profile="tech"))}
    assert found[EVENT]["span"] == phrase
    assert found[INANIMATE]["span"] == text.removesuffix("。")
    assert "以「我」作主詞" in found[INANIMATE]["instruction"]
    assert "因為通勤時間增加" in found[INANIMATE]["instruction"]

    object_issue, = issues(scan("我正在觀察通勤時間的增加。"))
    assert (object_issue["rule_id"], object_issue["span"]) == (EVENT, phrase)


@pytest.mark.parametrize("text", ["公司正在評估通勤時間的增加。", "我評估通勤時間的增加。"])
def test_event_as_object_leaves_the_outer_predicate_outside_the_span(text):
    issue, = issues(scan(text, profile="tech"))
    assert (issue["rule_id"], issue["span"]) == (EVENT, "通勤時間的增加")
    assert "短句「通勤時間增加」" in issue["instruction"]


def test_inanimate_subject_uses_an_affected_person_in_the_current_clause():
    text = "同事最近在找房子。通勤時間的增加讓交通成本上升。"
    issue, = issues(scan(text, profile="tech"))
    assert (issue["rule_id"], issue["span"]) == (EVENT, "通勤時間的增加")


def test_event_retains_the_action_head_and_the_full_object():
    text = "由於主倉的臨時盤點，物流組只能順延本批預購商品的統一出貨。"
    cause, delivery = issues(scan(text, profile="tech"))
    assert [(issue["rule_id"], issue["span"]) for issue in (cause, delivery)] == [
        (EVENT, "主倉的臨時盤點"),
        (EVENT, "本批預購商品的統一出貨"),
    ]
    assert "主倉臨時盤點" in cause["instruction"]
    assert "本批預購商品統一出貨" in delivery["instruction"]


def test_degree_and_adjacent_negation_survive_direct_rewrite():
    text = "舊版推薦模型並不具備足夠的準確度，點擊率也呈現出偏低的穩定性。"
    accuracy, stability = issues(scan(text, profile="tech"))
    assert (accuracy["rule_id"], accuracy["span"]) == (JARGON, "並不具備足夠的準確度")
    assert "並不夠準確" in accuracy["instruction"]
    assert (stability["rule_id"], stability["span"]) == (JARGON, "呈現出偏低的穩定性")
    assert "不太穩定" in stability["instruction"]


def test_whitelisted_compound_measure_preserves_the_other_rule_hit():
    text = "新版評測框架呈現出極高的語意保真度，研究組昨天已對抽樣腳本加以全面翻修。"
    measure, action = issues(scan(text, profile="tech"))
    assert (measure["rule_id"], measure["span"]) == (JARGON, "呈現出極高的語意保真度")
    assert "語意保真度極高" in measure["instruction"]
    assert (action["rule_id"], action["span"]) == (WEAK, "對抽樣腳本加以全面翻修")
    protected_issue, = issues(scan(text, profile="tech", frozen=("語意保真度",)))
    assert protected_issue == action


def test_ranked_group_keeps_the_relative_rank_and_membership():
    issue, = issues(scan("這場市集是今年河岸祭最受歡迎的活動之一。"))
    assert issue["rule_id"] == PLURAL
    assert "位居前列" in issue["instruction"]
    assert "受歡迎的活動" in issue["instruction"]
    assert "其中一個成員" in issue["instruction"]


@pytest.mark.parametrize("text", [
    "這是去年最受歡迎的三場講座之一。",
    "這是去年最受歡迎的 3 場講座之一。",
    "這是今年最暢銷的五本書之一。",
])
def test_counted_events_and_objects_remain_one_of_a_group(text):
    assert not issues(scan(text, profile="tech"))


@pytest.mark.parametrize(("text", "suggestion"), [
    ("書籍的選購，只好委託你了。", "選購書籍"),
    ("橫貫公路的再度坍方，是頭條新聞。", "橫貫公路再度坍方"),
    ("他們杯葛這種風俗的繼續。", "保存這種風俗"),
    ("一架客機失事，造成九十八人死亡。", "死了九十八人"),
    ("心理學家在老鼠的身上進行試驗。", "用老鼠試驗"),
    ("他具有不可忽視的嚴重性。", "嚴重"),
    ("模型呈現出很低的敏感性。", "不太敏感"),
    ("系統具有很高的可觀察性。", "很容易觀察"),
    ("他具有不高的知名度。", "名氣不大"),
    ("原案的知名度低。", "名氣不大"),
    ("昨晚的消息不被接受。", "大家都不接受"),
    ("他被指導員指出許多錯誤。", "施事「指導員」"),
    ("他被嚴重懷疑偷東西。", "有偷東西的嫌疑"),
    ("他從不被拒絕入場。", "有人拒絕"),
    ("他是數位領域最有名的人物之一。", "位居前列"),
    ("三位讀者都認為這是今年最值得看的傳記之一。", "位居前列"),
    ("趙雲是三國名將之一。", "省去「之一」"),
    ("這是他三個月內最期待的講座之一。", "位居前列"),
    ("客服團隊對退費流程作出全面檢討。", "全面檢討"),
])
def test_instruction_names_the_concrete_rewrite(text, suggestion):
    assert any(suggestion in issue["instruction"] for issue in issues(scan(text)))


def test_position_specific_replacement_and_disabled_rules():
    text = "他不被准許入學，他們進行分析。"
    diagnostic, = scan(text)["diagnostics"]
    passive = next(issue for issue in diagnostic["issues"] if issue["rule_id"] == PASSIVE)
    assert "未獲准" in passive["instruction"]
    assert "准許" not in diagnostic["must_keep_content_words"]
    assert "入學" in diagnostic["must_keep_content_words"]

    diagnostic, = scan(text, disabled=(PASSIVE,))["diagnostics"]
    assert [issue["rule_id"] for issue in diagnostic["issues"]] == [WEAK]
    assert {"入學", "准許"} <= set(diagnostic["must_keep_content_words"])

    diagnostic, = scan("他不被准許入學，但校方准許他旁聽。")["diagnostics"]
    assert {"入學", "准許"} <= set(diagnostic["must_keep_content_words"])
    assert "保留「准許」" in diagnostic["issues"][0]["instruction"]


def test_code_switch_is_an_info_suggestion_below_structural_issues():
    text = "先進行 A/B testing before release，再進行了詳細的研究。"
    chinese, english = issues(scan(text))
    assert chinese["rule_id"] == english["rule_id"] == WEAK
    assert english["span"] == "進行 A/B testing"
    assert english["priority"] > chinese["priority"]
    assert english["severity"] == "info"
    assert "保留英文原詞" in english["instruction"]


def test_masked_and_repeated_text_keeps_sentence_offsets():
    text = "前文。🙂進行`研究`，進行分析，進行分析。"
    diagnostic, = scan(text)["diagnostics"]
    source = diagnostic["target_sentence"]
    assert diagnostic["sentence_id"] == "L1_S2"
    assert [(issue["span"], issue["char_idx"]) for issue in diagnostic["issues"]] == [
        ("進行分析", source.index("進行分析")),
        ("進行分析", source.rindex("進行分析")),
    ]


def test_verification_action_only_hits_the_visible_repetition():
    span = "對設定檔進行驗證"
    text = f"日誌顯示 `{span}`；我們仍須{span}。"
    issue, = issues(scan(text, profile="tech"))
    assert (issue["rule_id"], issue["span"], issue["char_idx"]) == (WEAK, span, text.rindex(span))


def test_weak_verb_can_span_a_soft_line_break():
    text = "我們進行\r\n詳細的研究。"
    issue, = issues(scan(text))
    assert (issue["char_idx"], issue["span"]) == (2, "進行\r\n詳細的研究")


@pytest.mark.parametrize(("text", "span", "suggestion"), [
    ("新版退貨規範更具合理性。", "更具合理性", "更合理"),
    ("這份操作手冊頗具實用性。", "頗具實用性", "頗實用"),
])
def test_degree_heads_take_bare_property_nouns(text, span, suggestion):
    issue, = issues(scan(text))
    assert (issue["rule_id"], issue["span"]) == (JARGON, span)
    assert suggestion in issue["instruction"]


def test_degree_heads_skip_non_property_nouns_and_frozen_terms():
    assert not issues(scan("這場演出頗具規模，更具觀賞價值。"))
    assert not issues(scan("扣款 API 更具高可用性。", profile="tech"))
    assert not issues(scan("這道堤防具備足夠的高度。", profile="tech"))


@pytest.mark.parametrize(("text", "phrase"), [
    ("這間獨立書店頗具知名度。", "頗有名"),
    ("新版說明書頗具可讀性。", "頗好讀"),
    ("整體架構比舊版更具前瞻性。", "更有遠見"),
    ("這份提案不具有前瞻性。", "沒有遠見"),
    ("這份提案並不具有前瞻性。", "並沒有遠見"),
    ("這項設計呈現出極低的穩定度。", "極不穩定"),
])
def test_jargon_rewrites_preserve_degree_negation_and_comparison(text, phrase):
    issue, = issues(scan(text))
    assert issue["rule_id"] == JARGON
    assert f"「{phrase}」" in issue["instruction"]


@pytest.mark.parametrize(("text", "profile", "span"), [
    ("這筆異常退款申請昨天已被風控專員駁回。", "tech", "這筆異常退款申請昨天已被風控專員駁回"),
    ("這項展場改建案至今仍未被核准。", "social", "至今仍未被核准"),
    ("上個月才被推選為籌備會主委的林小姐只好先暫停發包。", "social", "被推選為籌備會主委"),
    ("但新版表單至今仍未被法務組核准。", "tech", "新版表單至今仍未被法務組核准"),
    ("該帳號已於十分鐘前被管理員鎖定。", "tech", "該帳號已於十分鐘前被管理員鎖定"),
])
def test_passive_covers_new_verbs_negation_and_cues(text, profile, span):
    issue, = issues(scan(text, profile=profile))
    assert (issue["rule_id"], issue["span"]) == (PASSIVE, span)


def test_passive_negation_and_cues_survive_the_rewrite():
    issue, = issues(scan("這項展場改建案至今仍未被核准。", profile="social"))
    assert "保留「至今」" in issue["instruction"]
    assert "仍未獲核准" in issue["instruction"]
    issue, = issues(scan("他從不被拒絕入場。"))
    assert "保留「從」" in issue["instruction"]
    assert "沒有人拒絕" in issue["instruction"]


def test_temporary_lock_preserves_the_time_and_unknown_agent():
    text = "您好，由於偵測到異常登入，您的帳號已被暫時鎖定，請依指示重新驗證身分。"
    issue, = issues(scan(text, profile="social"))
    assert (issue["rule_id"], issue["span"]) == (PASSIVE, "已被暫時鎖定")
    assert "保留「已」" in issue["instruction"]
    assert "「暫時鎖定」" in issue["instruction"]
    assert "施事者維持未明" in issue["instruction"]


def test_temporary_lock_with_an_agent_preserves_the_modifier():
    text = "這個帳號已被管理員暫時鎖定。"
    issue, = issues(scan(text, profile="tech"))
    assert (issue["rule_id"], issue["span"]) == (PASSIVE, text.removesuffix("。"))
    assert "施事「管理員」" in issue["instruction"]
    assert "「暫時鎖定」" in issue["instruction"]


def test_passive_title_object_is_protected_in_must_keep():
    text = "上個月才被推選為籌備會主委的林小姐只好先暫停發包。"
    diagnostic, = scan(text, profile="social")["diagnostics"]
    assert {"籌備會", "主委"} <= set(diagnostic["must_keep_content_words"])
    assert "推選" not in diagnostic["must_keep_content_words"]


@pytest.mark.parametrize("text", [
    "法務組已正式核准這份合約。",
    "管理員鎖定了該帳號。",
    "風控專員駁回這筆異常退款申請。",
    "他獲推選為籌備會主委。",
])
def test_new_passive_verbs_do_not_fire_on_active_prose(text):
    assert not issues(scan(text, profile="tech"))


def test_frozen_phrase_exempts_the_new_passive_span():
    assert not issues(scan("新版表單至今仍未被法務組核准。", profile="tech", frozen=("未被法務組核准",)))


@pytest.mark.parametrize(("text", "span"), [
    ("並對冷啟動路徑加以觀察。", "對冷啟動路徑加以觀察"),
    ("董事會給予了初步肯定。", "給予了初步肯定"),
    ("業務團隊作出更完整的說明。", "作出更完整的說明"),
])
def test_weak_verb_covers_mistagged_action_words(text, span):
    issue, = issues(scan(text, profile="tech"))
    assert (issue["rule_id"], issue["span"]) == (WEAK, span)


def test_compound_nominal_action_keeps_the_count_and_object():
    text = "本次迭代針對推薦服務進行了三輪壓力測試。"
    issue, = issues(scan(text, profile="tech"))
    assert issue["span"] == "針對推薦服務進行了三輪壓力測試"
    assert "做" in issue["instruction"]
    assert "三輪壓力測試" in issue["instruction"]


def test_ceremony_name_is_not_a_weak_verb_target():
    assert not issues(scan("主辦單位於開幕式上進行了剪綵儀式。", profile="social"))


@pytest.mark.parametrize(("text", "span"), [
    ("系統延遲的改善是本季最主要的成果。", "系統延遲的改善"),
    ("客服回應速度的提升，是本季關鍵進展。", "客服回應速度的提升"),
    ("第一組的部署已經完成。", "第一組的部署"),
    ("新版 API 的使用已經開放。", "新版 API 的使用"),
    ("長期的等待讓使用者感到不耐。", "長期的等待"),
])
def test_event_np_covers_mistagged_heads(text, span):
    found = [i["span"] for i in issues(scan(text, profile="tech")) if i["rule_id"] == EVENT]
    assert found == [span]


def test_event_span_does_not_swallow_the_predicate_verb():
    issue, = issues(scan("維運團隊完成資料庫的遷移。", profile="tech"))
    assert (issue["rule_id"], issue["span"]) == (EVENT, "資料庫的遷移")


def test_successive_modifier_is_not_the_event_head():
    text = "關鍵工程師的接連離職，迫使專案時程大幅壓縮。"
    issue, = issues(scan(text, profile="tech"))
    assert (issue["rule_id"], issue["span"]) == (EVENT, "關鍵工程師的接連離職")


def test_inanimate_covers_change_verbs_and_modified_person():
    text = "流程的突然變動讓一線客服感到相當挫折。"
    found = {i["rule_id"]: i for i in issues(scan(text, profile="social"))}
    assert found[INANIMATE]["span"] == "流程的突然變動讓一線客服感到相當挫折"
    assert "一線客服" in found[INANIMATE]["instruction"]


@pytest.mark.parametrize("text", ["長者們對新的動線安排反應良好。", "工作人員們改以電話個別通知。"])
def test_plural_covers_more_collective_nouns(text):
    assert any(i["rule_id"] == PLURAL for i in issues(scan(text)))


@pytest.mark.parametrize(("text", "span"), [
    ("候補名單並沒有被公告。", "並沒有被公告"),
    ("試行方案被否決。", "被否決"),
    ("專案被延後了。", "被延後了"),
    ("這批抱怨被歸類為高優先案件。", "被歸類為高優先案件"),
])
def test_passive_covers_new_verbs_and_meiyou_negation(text, span):
    issue, = issues(scan(text, profile="social"))
    assert (issue["rule_id"], issue["span"]) == (PASSIVE, span)


def test_meiyou_negation_is_preserved_in_the_rewrite():
    issue, = issues(scan("候補名單並沒有被公告。", profile="social"))
    assert "還沒有人公告" in issue["instruction"]
    assert "保留「並」" in issue["instruction"]


@pytest.mark.parametrize(("text", "span", "example"), [
    ("專案被延後了兩週，理由是關鍵零件尚未到貨。", "被延後了", "延後了兩週"),
    ("這次導覽並沒有被延後半小時。", "並沒有被延後", "並沒有延後半小時"),
])
def test_agentless_delay_instruction_preserves_duration(text, span, example):
    issue, = issues(scan(text, profile="social"))
    assert (issue["rule_id"], issue["span"]) == (PASSIVE, span)
    assert f"「{example}」" in issue["instruction"]
    assert "有人" not in issue["instruction"]


def test_agentless_veto_instruction_preserves_review_context():
    text = "試行方案在第二輪審查中被否決，理由是成本估算不足。"
    issue, = issues(scan(text, profile="social"))
    assert (issue["rule_id"], issue["span"]) == (PASSIVE, "被否決")
    assert "用「遭否決」代替「被否決」" in issue["instruction"]
    assert "審查輪次與理由" in issue["instruction"]
    assert "施事者維持未明" in issue["instruction"]


def test_veto_with_explicit_agent_can_still_use_active_voice():
    issue, = issues(scan("試行方案在第二輪審查中被委員會否決。", profile="social"))
    assert issue["rule_id"] == PASSIVE
    assert "讓施事「委員會」作主詞" in issue["instruction"]


def test_lidi_rewrite_is_a_real_word():
    issue, = issues(scan("數據佐證頗具力度。", profile="tech"))
    assert "頗有力" in issue["instruction"]


def test_physical_measure_nouns_are_not_pseudo_jargon():
    assert not issues(scan("這套設備具有穩定的溫度。", profile="tech"))


def l5_handoff(text):
    """真實使用順序：先跑 L5 預檢，作者確認白名單後才交給 L1。"""
    return preflight(
        text,
        source_type="stdin",
        target_id="stdin",
        whitelist=load_default_lexicons()["tech_whitelist"],
    )


def test_l5_handoff_confirms_compound_measure_before_l1():
    text = "新版評測框架呈現出極高的語意保真度，研究組昨天已對抽樣腳本加以全面翻修。"
    payload = l5_handoff(text)
    candidates = [item["term"] for item in payload["suspect_terms_for_review"]]
    assert candidates == ["保真度"]
    before = issues(scan(text, profile=payload["suggested_profile"]))
    assert [(issue["rule_id"], issue["span"]) for issue in before] == [
        (JARGON, "呈現出極高的語意保真度"),
        (WEAK, "對抽樣腳本加以全面翻修"),
    ]
    # 作者核可 L5 原樣候選或補齊完整複合詞，L1 都只留弱動詞診斷；
    # 握手時改判 tech 語體也不影響結果。
    for accepted in (candidates, ["語意保真度"]):
        for profile in (payload["suggested_profile"], "tech"):
            result = scan(text, profile=profile, frozen=accepted)
            issue, = issues(result)
            assert (issue["rule_id"], issue["span"]) == (WEAK, "對抽樣腳本加以全面翻修")
            assert result["diagnostics"][0]["frozen_whitelist_hits"] == accepted


def test_l5_handoff_confirms_code_switch_phrase_as_a_whole():
    text = "成長組本週將針對新戶引導頁進行 A/B testing，收集滿一萬筆樣本後再結案。"
    payload = l5_handoff(text)
    assert payload["suggested_profile"] == "tech"
    assert [item["term"] for item in payload["suspect_terms_for_review"]] == ["進行 A/B testing"]
    before, = issues(scan(text, profile=payload["suggested_profile"]))
    assert before["severity"] == "info"
    confirmed = ("進行 A/B testing",)
    assert not issues(scan(text, profile=payload["suggested_profile"], frozen=confirmed))


def test_l5_handoff_rejected_candidate_keeps_the_l1_diagnosis():
    text = "這份操作手冊具有很高的可讀性，新同事看一遍就能上手。"
    payload = l5_handoff(text)
    assert [item["term"] for item in payload["suspect_terms_for_review"]] == ["可讀性"]
    # 作者判定不是專有名詞：不豁免，L1 照常診斷。
    issue, = issues(scan(text, profile=payload["suggested_profile"]))
    assert (issue["rule_id"], issue["span"]) == (JARGON, "具有很高的可讀性")
    # 若作者改判豁免，同一句即放行。
    assert not issues(scan(text, profile=payload["suggested_profile"], frozen=("可讀性",)))


@pytest.mark.parametrize(("text", "person"), [
    ("資金的長期缺乏迫使獨立書店老闆縮減營業時間。", "獨立書店老闆"),
    ("排班表的臨時變動帶給門市人員不小困擾。", "門市人員"),
    ("轉機櫃檯的漫長等待讓現場旅客感到精疲力竭。", "現場旅客"),
    ("月台班次的臨時變動讓候車乘客感到相當無奈。", "候車乘客"),
    ("推薦引擎的突然變動讓內容編輯連夜重排首頁專題。", "內容編輯"),
])
def test_inanimate_person_object_keeps_attributive_modifiers(text, person):
    found = [i for i in issues(scan(text)) if i["rule_id"] == INANIMATE]
    assert found, f"未命中無靈主語：{text}"
    assert person in found[0]["instruction"]


def test_inanimate_person_scan_stops_at_the_predicate_boundary():
    # 「上升」已是謂語，其後的「員工」不是使動動詞的受詞。
    text = "流程的突然變動讓交通成本上升影響員工。"
    assert INANIMATE not in {i["rule_id"] for i in issues(scan(text))}


@pytest.mark.parametrize(("text", "span"), [
    ("由於多區域備援節點的緊急部署，週末例行備份任務順延兩小時才啟動。", "多區域備援節點的緊急部署"),
    ("推薦引擎的突然變動讓內容編輯連夜重排首頁專題。", "推薦引擎的突然變動"),
    ("帳務組將核心帳本的夜間盤點排在每週日凌晨三點執行。", "核心帳本的夜間盤點"),
    ("颱風的提早來襲打亂了離島船班表。", "颱風的提早來襲"),
    ("金流閘道的頻繁逾時拖慢了整體結帳流程。", "金流閘道的頻繁逾時"),
])
def test_event_covers_compound_nps_temporal_modifiers_and_dictionary_heads(text, span):
    found = [i["span"] for i in issues(scan(text, profile="tech")) if i["rule_id"] == EVENT]
    assert span in found


def test_jargon_compound_measure_with_verb_prefix():
    text = "這套音訊壓縮演算法呈現出極低的計算複雜度，在低階穿戴裝置上也能即時運作。"
    issue, = issues(scan(text, profile="tech"))
    assert (issue["rule_id"], issue["span"]) == (JARGON, "呈現出極低的計算複雜度")
    assert "計算複雜度" in issue["instruction"]
    assert not issues(scan(text, profile="tech", frozen=("計算複雜度",)))


def test_passive_classification_object_includes_mistagged_tail():
    text = "這起冷鏈貨櫃失溫客訴在週會上被歸類為重大品質異常，倉儲部須於三日內提交改善計畫。"
    issue, = issues(scan(text))
    assert (issue["rule_id"], issue["span"]) == (PASSIVE, "被歸類為重大品質異常")


def test_weak_verb_recovers_merged_preposition():
    text = "文件組昨天也已對錯誤碼章節進行了全面翻修。"
    issue, = issues(scan(text, profile="tech"))
    assert (issue["rule_id"], issue["span"]) == (WEAK, "對錯誤碼章節進行了全面翻修")


@pytest.mark.parametrize(("rule", "text", "span"), [
    (WEAK, "維運團隊針對舊訂單表進行了兩次完整備份。", "針對舊訂單表進行了兩次完整備份"),
    (WEAK, "值班人員仍需對舊資料進行清理。", "對舊資料進行清理"),
    (WEAK, "客服已針對補助條款進行了查詢。", "針對補助條款進行了查詢"),
    (WEAK, "團隊對這起異常作出正式回應。", "對這起異常作出正式回應"),
    (EVENT, "病患個資的未授權匯出已經違反院內資安規範。", "病患個資的未授權匯出"),
    (EVENT, "承辦人聽說法務部門的臨時退件。", "法務部門的臨時退件"),
    (EVENT, "海溫的持續上升讓珊瑚礁大面積白化。", "海溫的持續上升"),
    (PLURAL, "圍觀的群眾們也跟著倒數歡呼。", "群眾們"),
    (PASSIVE, "合併請求已經被審核團隊擱置了。", "合併請求已經被審核團隊擱置了"),
])
def test_final_round_vocabulary_coverage(rule, text, span):
    found = [i["span"] for i in issues(scan(text, profile="tech")) if i["rule_id"] == rule]
    assert span in found


@pytest.mark.parametrize("text", [
    "雲端費率大幅調漲迫使維運工程師連夜重設快取規則。",
    "雲端費率連番調漲讓財務主管不得不重新核定預算。",
    "機房過熱迫使值班工程師緊急切斷備援主機的電源。",
    "收單銀行臨時限額迫使金流工程師連夜切換備援通道。",
])
def test_clausal_subject_is_not_inanimate_nominalization(text):
    # 規格裁決（2026-11-20）：事理子句主語（無「的」）非名物化病灶，
    # 無靈主語規則只認 NP+的+VN 主語，不擴及子句主語。
    assert INANIMATE not in {i["rule_id"] for i in issues(scan(text))}
