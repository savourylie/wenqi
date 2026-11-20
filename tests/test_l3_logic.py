"""TICKET-009，L3 案例庫、豁免及 Scanner 診斷契約。

每案先跑 L5 預檢，明寫的語體與暫用白名單代表作者裁決。
短句因果屬 L3_CAUSAL_MALFORMED，停用鍵為 L3_SHORT_CAUSAL_DROP。
"""

import pytest

from engine import load_default_lexicons
from engine.ast_scanner import lint
from engine.rules.l5_preflight import preflight
from engine.state_manager import DEFAULT_PROFILES


FRAME = "L3_PREPOSITIONAL_FRAME"
CAUSAL = "L3_CAUSAL_MALFORMED"
SHORT_DISABLED = "L3_SHORT_CAUSAL_DROP"
CONJ = "L3_CONJUNCTION_MISUSE"


def scan(text, *, profile="essay", frozen=(), disabled=(), layer="L3"):
    assert l5_handoff(text)["mode"] == "L5_PREFLIGHT"
    settings = {
        "effective_profile": profile,
        "profile_config": DEFAULT_PROFILES[profile],
        "whitelist": load_default_lexicons()["tech_whitelist"] + [
            {"term": term, "pos": "nz"} for term in frozen
        ],
        "disabled_rules": {"profile": DEFAULT_PROFILES[profile]["disabled_rules"], "document": list(disabled)},
    }
    return lint(text, settings, requested_layer=layer)


def issues(result):
    return [issue for sentence in result["diagnostics"] for issue in sentence["issues"]]


@pytest.mark.parametrize(("rule", "text", "fragments"), [
    (FRAME, "在系統遷移的過程當中，我們對有關檢索模組的高可用性的問題進行了詳細的研究。",
     ("在系統遷移的過程當中", "有關檢索模組的高可用性的問題")),
    (FRAME, "歡迎王教授今天來到我們的中間，在有關環境污染的各種問題上，為我們作一次學術性的演講。",
     ("來到我們的中間", "有關環境污染的各種問題")),
    (FRAME, "有關文革的種種，令人不能置信。", ("有關文革的種種",)),
    (FRAME, "今天我們討論有關臺灣交通的問題。", ("有關臺灣交通的問題",)),
    (FRAME, "關於他的申請，你看過了沒有？", ("關於他的申請",)),
    (FRAME, "關於一個河堤孩子的成長故事", ("關於一個河堤孩子的成長故事",)),
    (FRAME, "在系統重構的過程當中，我們遇到了瓶頸。", ("在系統重構的過程當中",)),
    (FRAME, "從使用者體驗的角度來看，這是好的設計。", ("從使用者體驗的角度來看",)),
    (FRAME, "在資料完整的前提下，我們才動手。", ("在資料完整的前提下",)),
    (FRAME, "關於計畫，我懂。對於這件事，他有意見。針對異常狀況，系統會發出警告。",
     ("關於計畫", "對於這件事", "針對異常狀況")),
    (CAUSAL, "由於他的家境貧窮，使得他只好休學。", ("由於他的家境貧窮，使得",)),
    (CAUSAL, "因為下雨，也使得他動彈不得。", ("因為下雨，也使得",)),
    (CAUSAL, "由於昨夜暴雨，到了傍晚，使得活動取消。", ("由於昨夜暴雨，到了傍晚，使得",)),
    (CAUSAL, "鑑於經費縮減，終於令計畫停擺。", ("鑑於經費縮減，終於令",)),
    (CAUSAL, "因為下雨，使得表演取消，鑑於經費縮減，終於令計畫停擺。",
     ("因為下雨，使得", "鑑於經費縮減，終於令")),
    (CAUSAL, "由於好奇心的驅使，我向窗內看了一眼。", ("由於好奇心的驅使",)),
    (CAUSAL, "受到責任感的影響，他留了下來。因為興趣的緣故，他繼續研究。",
     ("受到責任感的影響", "因為興趣的緣故")),
    (CAUSAL, "由於秦末天下大亂，所以群雄四起。", ("由於秦末天下大亂，所以群雄四起",)),
    (CAUSAL, "因為下雨，因此活動取消。", ("因為下雨，因此活動取消",)),
    (CONJ, "這套架構比舊版起步更早及邁步更快。", ("起步更早及邁步更快",)),
    (CONJ, "慢及可靠。緩慢與有把握。", ("慢及可靠", "緩慢與有把握")),
    (CONJ, "更深及更廣。越省力及越耐用。", ("更深及更廣", "越省力及越耐用")),
    (CONJ, "本系統的角色有管理員、編輯者、審核者及訪客。", ("管理員、編輯者、審核者及訪客",)),
    (CONJ, "這裏有盆栽、書本、茶杯和水壺。", ("盆栽、書本、茶杯和水壺",)),
    (CONJ, "接待老朋友、小朋友、老師及家長。", ("老朋友、小朋友、老師及家長",)),
    (CONJ, "清單有 A、B、C 及 D。", ("A、B、C 及 D",)),
    (CONJ, "致在政經體制改革的觀念、行動、範圍及對象，更為深廣更具實質。",
     ("觀念、行動、範圍及對象",)),
    (CONJ, "系統角色包括管理員、編輯者及訪客。", ("管理員、編輯者及訪客",)),
    (CONJ, "試用僅限三天，角色有管理員、編輯者、審核者及訪客。", ("管理員、編輯者、審核者及訪客",)),
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
            assert issue["layer"] == "L3"
            assert issue["priority"] in {0, 1}
            assert all(issue[field] for field in ("pos_pattern", "theoretical_basis", "instruction"))
            assert "_replaceable_token_starts" not in issue


@pytest.mark.parametrize("text", [
    "清風徐來，水波不興。",
    "歡迎王教授今天光臨，為我們講述環境污染的各種問題。",
    "文革的種種，令人不能置信。",
    "今天我們討論臺灣的交通問題。",
    "他的申請，你看過了沒有？",
    "河堤孩子的成長",
    "系統重構時，我們遇到了瓶頸。",
    "他家境貧窮，只好休學。",
    "出於好奇，我向窗內看了一眼。",
    "秦末天下大亂，群雄四起。",
    "慢而可靠。緩慢而有把握。起步早而邁步快。",
    "在政治民主化、經濟自由化的發展道路上，臺北顯然比北京起步更早，邁步更快。",
    "這堂課涵蓋閱讀與寫作。",
    "課程涵蓋核對數字以及驗證資料。",
    "閱讀與寫作是他的興趣。",
    "請處理與帳號有關的問題。這是一份有關使用者身分的說明。",
    "有關部門已經介入調查。",
    "現在系統遷移的過程中，我們遇到瓶頸。",
    "由於版本更新，使用者須重新登入，命令列介面保持不變。",
    "老師及家長都收到了通知。",
    "機器能自動驗證和修正資料。",
    "整理資料以及核對數字。",
    "在政治民主化與經濟自由化的發展道路，臺北顯然比北京起步更早。",
    "來得及。涉及多個模組。波及更廣的層面。",
])
def test_natural_and_exempt_prose(text):
    assert not issues(scan(text))


@pytest.mark.parametrize("profile", ["tech", "social", "essay"])
@pytest.mark.parametrize("text", [
    "由於上游逾時，重試機制導致流量翻倍。",
    "由於上游逾時，重試機制導致流量翻倍，造成服務中斷。",
    "由於排程衝突，逾時導致請求失敗。",
    "因為路滑，他跌倒，導致腳踝扭傷。",
])
def test_causal_clauses_with_their_own_subject_are_exempt(profile, text):
    assert not issues(scan(text, profile=profile))


@pytest.mark.parametrize(("text", "span"), [
    ("請先檢查及核對現有資料。", "檢查及核對現有資料"),
    ("操作員可以檢查與核對資料。", "檢查與核對資料"),
    ("他能自動分析和驗證資料。", "分析和驗證資料"),
    ("團隊將驗證資料以及核對帳目。", "驗證資料以及核對帳目"),
    ("核對數字以及驗證資料。", "核對數字以及驗證資料"),
    ("本人和朋友一起閱讀與寫作。", "閱讀與寫作"),
])
def test_parallel_action_phrases_are_detected(text, span):
    issue, = issues(scan(text))
    assert (issue["rule_id"], issue["span"]) == (CONJ, span)


@pytest.mark.parametrize(("text", "span", "rewrite"), [
    ("他在週末痛快地攀岩與盡情地溯溪，把整週的工作壓力一次釋放。",
     "痛快地攀岩與盡情地溯溪", "痛快地攀岩，盡情地溯溪"),
    ("她認真地核對帳目及仔細地檢查單據。",
     "認真地核對帳目及仔細地檢查單據", "認真地核對帳目，仔細地檢查單據"),
])
def test_parallel_actions_with_manner_markers(text, span, rewrite):
    diagnostic, = scan(text, profile="social")["diagnostics"]
    issue, = diagnostic["issues"]
    assert (issue["rule_id"], issue["span"], issue["char_idx"]) == (CONJ, span, text.index(span))
    assert rewrite in issue["instruction"]


@pytest.mark.parametrize("text", [
    "這座戶外中心暑假開設的體驗課程包含攀岩與溯溪，名額非常搶手。",
    "她認真地核對帳目及仔細地檢查單據的模樣，令人難忘。",
])
def test_activity_names_and_manner_attributes_are_exempt(text):
    assert not issues(scan(text, profile="social"))


@pytest.mark.parametrize(("text", "span", "rewrite"), [
    ("本屆文學獎的投稿類別包含推理、科幻、歷史及散文。",
     "推理、科幻、歷史及散文", "推理、科幻、歷史、散文"),
    ("本屆文學獎僅限在學學生報名，現場書展則陳列推理、科幻、歷史及散文。",
     "推理、科幻、歷史及散文", "推理、科幻、歷史、散文"),
    ("她列出來自臺灣的芒果、蜜棗及鳳梨。",
     "來自臺灣的芒果、蜜棗及鳳梨", "來自臺灣的芒果、蜜棗、鳳梨"),
    ("包含糖的點心有餅乾、蛋糕及糖果。",
     "餅乾、蛋糕及糖果", "餅乾、蛋糕、糖果"),
    ("僅限會員報名的課程包含攀岩、溯溪及滑雪。",
     "攀岩、溯溪及滑雪", "攀岩、溯溪、滑雪"),
    ("僅限會員報名的課程包含適合新手的攀岩、溯溪及滑雪。",
     "適合新手的攀岩、溯溪及滑雪", "適合新手的攀岩、溯溪、滑雪"),
])
def test_list_introducer_is_outside_the_diagnostic(text, span, rewrite):
    issue, = issues(scan(text))
    assert (issue["rule_id"], issue["span"], issue["char_idx"]) == (CONJ, span, text.index(span))
    assert rewrite in issue["instruction"]


@pytest.mark.parametrize("text", [
    "本系統角色僅限四種：管理員、編輯者、審核者及訪客。",
    "本系統的角色定義為管理員、編輯者、審核者及訪客。",
    "本系統角色共四種：管理員、編輯者、審核者及訪客。",
    "系統支援三種格式：JSON、XML 及 CSV。",
    "角色只有兩類：管理員及訪客。",
    "本屆文學獎的投稿類別僅限推理、科幻、歷史及散文共四種。",
    "本屆文學獎的投稿類別包含推理、科幻、歷史及散文共四種。",
    "本屆文學獎的投稿類別包含推理、科幻、歷史及散文，共四種。",
    "課程僅限適合新手的攀岩、溯溪及滑雪。",
    "系統的角色定義為有審核權限的管理員、編輯者及訪客。",
])
def test_strict_set_definition_is_exempt(text):
    assert not issues(scan(text))


def test_golden_case_1_frames_protect_the_frozen_term():
    text = "在系統遷移的過程當中，我們對有關檢索模組的高可用性的問題進行了詳細的研究。"
    diagnostic, = scan(text, profile="tech")["diagnostics"]
    assert [(issue["rule_id"], issue["span"]) for issue in diagnostic["issues"]] == [
        (FRAME, "在系統遷移的過程當中"),
        (FRAME, "有關檢索模組的高可用性的問題"),
    ]
    assert diagnostic["frozen_whitelist_hits"] == ["高可用性"]
    assert {"高可用性", "問題"} <= set(diagnostic["must_keep_content_words"])
    assert not {"有關", "過程"} & set(diagnostic["must_keep_content_words"])
    assert "保留凍結詞「高可用性」原樣" in diagnostic["issues"][1]["instruction"]


def test_golden_case_3_subject_annihilation_restores_the_subject():
    text = "由於他的收入的減少，使得他的生活方式被徹底改變了。"
    issue, = issues(scan(text))
    assert (issue["rule_id"], issue["span"]) == (CAUSAL, "由於他的收入的減少，使得")
    assert issue["priority"] == 0
    assert "還原主語" in issue["instruction"]
    assert "他的收入的減少" in issue["instruction"]
    assert "主語湮沒" in issue["theoretical_basis"]


def test_golden_case_4_symmetric_comparatives_use_a_comma():
    text = "這套架構比舊版起步更早及邁步更快，在灰暗的淒冷的天空下具有很高的可讀性。"
    issue, = issues(scan(text, profile="tech"))
    assert (issue["rule_id"], issue["span"], issue["char_idx"]) == (CONJ, "起步更早及邁步更快", 7)
    assert "起步更早，邁步更快" in issue["instruction"]
    assert "詞性邊界" in issue["theoretical_basis"]


def test_short_causal_is_disabled_in_tech_only():
    text = "由於秦末天下大亂，所以群雄四起。"
    assert not issues(scan(text, profile="tech"))
    for profile in ("essay", "social"):
        issue, = issues(scan(text, profile=profile))
        assert issue["rule_id"] == CAUSAL
        assert "秦末天下大亂，群雄四起" in issue["instruction"]
    # 主語湮沒型不受 tech 豁免影響，仍須修復。
    issue, = issues(scan("由於上游逾時，使得服務中斷。", profile="tech"))
    assert issue["rule_id"] == CAUSAL


def test_short_causal_respects_the_eight_character_limit():
    assert issues(scan("由於雨大，所以路滑。"))
    assert not issues(scan("由於上游服務逾時超過三十秒，所以重試機制啟動。"))
    assert not issues(scan("由於雨大，所以整個城區的道路都積水了。"))


def test_document_can_disable_short_causal_or_the_whole_rule():
    text = "由於他的家境貧窮，使得他只好休學。由於雨大，所以路滑。"
    assert [issue["rule_id"] for issue in issues(scan(text))] == [CAUSAL, CAUSAL]
    issue, = issues(scan(text, disabled=(SHORT_DISABLED,)))
    assert (issue["rule_id"], issue["span"]) == (CAUSAL, "由於他的家境貧窮，使得")
    assert not issues(scan(text, disabled=(CAUSAL,)))


@pytest.mark.parametrize(("text", "frozen"), [
    ("慢及可靠。", "慢及可靠"),
    ("慢及可靠。", "及"),
    ("起步更早及邁步更快。", "及"),
    ("有關文革的種種，令人不能置信。", "有關"),
    ("關於高齡照護補助的申請事項，明天確認。", "申請事項"),
    ("在系統重構的過程當中，我們遇到了瓶頸。", "過程當中"),
    ("由於他的家境貧窮，使得他只好休學。", "使得"),
    ("由於好奇心的驅使，我向窗內看了一眼。", "好奇心"),
    ("管理員、編輯者、審核者及訪客。", "及"),
])
def test_frozen_match_is_exempt(text, frozen):
    assert not issues(scan(text, frozen=(frozen,)))


def test_frozen_term_inside_the_frame_core_does_not_exempt_the_frame():
    text = "今天我們討論有關高可用性的問題。"
    issue, = issues(scan(text, profile="tech"))
    assert (issue["rule_id"], issue["span"]) == (FRAME, "有關高可用性的問題")
    assert "高可用性" in issue["instruction"]


@pytest.mark.parametrize(("text", "suggestion"), [
    ("在系統重構的過程當中，我們遇到了瓶頸。", "系統重構時，"),
    ("從使用者體驗的角度來看，這是好的設計。", "就使用者體驗而言，"),
    ("在資料完整的前提下，我們才動手。", "就資料完整而言，"),
    ("歡迎王教授今天來到我們的中間。", "光臨"),
    ("有關文革的種種，令人不能置信。", "文革的種種"),
    ("關於一個河堤孩子的成長故事", "河堤孩子的成長"),
    ("今天我們討論有關臺灣交通的問題。", "保留「問題」"),
    ("由於好奇心的驅使，我向窗內看了一眼。", "出於好奇"),
    ("受到責任感的影響，他留了下來。", "出於責任感"),
    ("因為興趣的緣故，他繼續研究。", "出於興趣"),
    ("慢及可靠。", "慢而可靠"),
    ("緩慢與有把握。", "緩慢而有把握"),
    ("更深及更廣。", "更深而更廣"),
    ("管理員、編輯者、審核者及訪客。", "管理員、編輯者、審核者、訪客"),
    ("由於秦末天下大亂，所以群雄四起。", "秦末天下大亂，群雄四起"),
])
def test_instruction_names_the_concrete_rewrite(text, suggestion):
    assert any(suggestion in issue["instruction"] for issue in issues(scan(text)))


def test_deleted_frame_words_leave_must_keep():
    diagnostic, = scan("今天我們討論有關臺灣交通的問題。")["diagnostics"]
    assert {"臺灣", "交通", "討論", "問題"} <= set(diagnostic["must_keep_content_words"])
    assert "有關" not in diagnostic["must_keep_content_words"]
    diagnostic, = scan("由於他的家境貧窮，使得他只好休學。")["diagnostics"]
    assert "使得" not in diagnostic["must_keep_content_words"]
    assert "家境" in diagnostic["must_keep_content_words"]


@pytest.mark.parametrize("frozen", [(), ("問題",)])
def test_unclear_problem_meaning_preserves_problem_word(frozen):
    text = "有關訂單同步的問題，明天再討論。"
    diagnostic, = scan(text, frozen=frozen)["diagnostics"]
    issue, = diagnostic["issues"]
    assert (issue["rule_id"], issue["span"]) == (FRAME, "有關訂單同步的問題")
    assert "只刪去「有關」" in issue["instruction"]
    assert "「訂單同步的問題」" in issue["instruction"]
    assert "問題" in diagnostic["must_keep_content_words"]


@pytest.mark.parametrize(("text", "topic", "keep"), [
    ("有關故事結構的問題，明天再討論。", "故事結構的問題", "問題"),
    ("有關地方故事形式的問題，明天再討論。", "地方故事形式的問題", "問題"),
    ("有關垃圾分類的問題已經有人提出處理事項。", "垃圾分類的問題", "問題"),
    ("關於地方傳說故事的查證事項，明天確認。", "地方傳說故事的查證事項", "地方傳說故事的查證"),
])
def test_frame_shell_leaves_attributive_nouns_in_the_core(text, topic, keep):
    issue, = issues(scan(text))
    assert (issue["rule_id"], issue["span"], issue["char_idx"]) == (FRAME, text[:2] + topic, 0)
    assert f"「{keep}」" in issue["instruction"]
    if keep == "問題":
        assert "只刪去「有關」" in issue["instruction"]
        assert f"「{topic}」" in issue["instruction"]


def test_masked_text_keeps_sentence_offsets():
    text = "前句。請處理`有關程式碼的問題`，再討論有關訂單同步的問題。"
    diagnostic, = scan(text)["diagnostics"]
    source = diagnostic["target_sentence"]
    issue, = diagnostic["issues"]
    assert (issue["rule_id"], issue["span"], issue["char_idx"]) == (
        FRAME, "有關訂單同步的問題", source.index("有關訂單同步的問題"),
    )


def test_frame_can_span_a_soft_line_break():
    text = "在系統\r\n遷移的過程當中，我們遇到瓶頸。"
    issue, = issues(scan(text))
    assert (issue["char_idx"], issue["span"]) == (0, "在系統\r\n遷移的過程當中")


def test_subject_loss_sorts_before_l3_frames_and_l1_in_all_layer_scan():
    text = "在系統遷移的過程當中，由於他的收入的減少，使得他的生活方式被徹底改變了。"
    result = scan(text, layer="ALL")
    first, second, *later = issues(result)
    assert (first["rule_id"], second["rule_id"]) == (CAUSAL, FRAME)
    assert first["char_idx"] > second["char_idx"]
    assert first["priority"] < second["priority"]
    assert any(issue["layer"] == "L1" for issue in later)
    assert result["summary"]["issue_counts"]["L3"] == 2


@pytest.mark.parametrize("layer", ["L3", "ALL"])
def test_merged_frame_shell_and_later_causal_issue(layer):
    text = "關於高齡照護補助的申請事項，由於地方窗口人力不足，導致審核進度明顯延宕。"
    diagnostic, = scan(text, layer=layer)["diagnostics"]
    causal, frame = [issue for issue in diagnostic["issues"] if issue["layer"] == "L3"]
    assert (causal["rule_id"], causal["span"], causal["priority"]) == (
        CAUSAL, "由於地方窗口人力不足，導致", 0,
    )
    assert (frame["rule_id"], frame["span"], frame["char_idx"], frame["priority"]) == (
        FRAME, "關於高齡照護補助的申請事項", 0, 1,
    )
    assert "「高齡照護補助的申請」" in frame["instruction"]
    assert "申請事項" not in diagnostic["must_keep_content_words"]


def test_merged_frame_shell_preserves_a_frozen_core_term():
    text = "關於高齡照護補助的申請事項，明天確認。"
    term = "高齡照護補助"
    diagnostic, = scan(text, frozen=(term,))["diagnostics"]
    issue, = diagnostic["issues"]
    assert (issue["rule_id"], issue["span"]) == (FRAME, "關於高齡照護補助的申請事項")
    assert f"「{term}的申請」" in issue["instruction"]
    assert term in diagnostic["frozen_whitelist_hits"]
    assert term in diagnostic["must_keep_content_words"]


def l5_handoff(text):
    """真實使用順序：先跑 L5 預檢，作者確認白名單後才交給 L3。"""
    return preflight(
        text,
        source_type="stdin",
        target_id="stdin",
        whitelist=load_default_lexicons()["tech_whitelist"],
    )


def test_l5_handoff_precedes_l3_and_frozen_core_still_frames():
    text = "從使用者體驗的角度來看，新版介面的可讀性很高。"
    payload = l5_handoff(text)
    assert [item["term"] for item in payload["suspect_terms_for_review"]] == ["角度", "可讀性"]
    before, = issues(scan(text, profile=payload["suggested_profile"]))
    assert (before["rule_id"], before["span"]) == (FRAME, "從使用者體驗的角度來看")
    # 作者核可或拒絕候選詞，都不影響外框診斷；核可時凍結詞留在核心 NP 內。
    for frozen in ((), ("可讀性",)):
        issue, = issues(scan(text, profile=payload["suggested_profile"], frozen=frozen))
        assert (issue["rule_id"], issue["span"]) == (FRAME, "從使用者體驗的角度來看")


def test_l5_handoff_confirms_profile_before_short_causal_scan():
    text = "由於雨大，所以路滑。"
    payload = l5_handoff(text)
    result = scan(text, profile=payload["suggested_profile"])
    if payload["suggested_profile"] == "tech":
        assert not issues(result)
    else:
        assert issues(result)[0]["rule_id"] == CAUSAL
