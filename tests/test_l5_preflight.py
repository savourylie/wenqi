"""TICKET-005 的術語預檢、語體判斷與輸出契約。"""

import json
import subprocess
from dataclasses import replace

import pytest

from engine.rules.l5_preflight import preflight
from engine.state_manager import (
    SCHEMA_VERSION,
    add_local_whitelist,
    content_hash,
    load_settings_for_file,
    load_settings_for_stdin,
    save_workspace,
)
from engine.tokenizer_adapter import JiebaPosAdapter


def _preflight_stdin(text, whitelist=(), **options):
    return preflight(
        text, source_type="stdin", target_id="stdin", whitelist=whitelist, **options
    )


def test_file_payload_and_confirmed_phrase_use_effective_whitelist(tmp_path):
    repo = tmp_path / "blog"
    article = repo / "posts" / "2026-11-agent-memory.md"
    article.parent.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    text = (
        "高可用性與冪等性是 MemFuse 的特色。"
        "透過快取提升資料存取的局部性。\n改善局部性。\n"
        "我們對小模型進行 Fine-tuning。"
    )
    article.write_text(text, encoding="utf-8")
    state_dir = tmp_path / "state"
    save_workspace(
        {
            "schema_version": SCHEMA_VERSION,
            "repo_root": str(repo),
            "repo_defaults": {"whitelist": [{"term": "MemFuse"}, {"term": "FlowDance"}]},
        },
        repo,
        state_dir,
    )

    def analyze():
        settings = load_settings_for_file(article, state_dir=state_dir)
        return preflight(
            text,
            source_type=settings["source_type"],
            target_id=settings["rel_path"],
            whitelist=settings["whitelist"],
            fallback_profile=settings["effective_profile"],
        )

    result = json.loads(json.dumps(analyze(), ensure_ascii=False))
    assert result.keys() == {
        "mode", "source_type", "target_id", "content_hash", "suggested_profile",
        "profile_reason", "active_whitelist_terms", "suspect_terms_for_review",
    }
    assert result["mode"] == "L5_PREFLIGHT"
    assert result["source_type"] == "file"
    assert result["target_id"] == "posts/2026-11-agent-memory.md"
    assert result["content_hash"] == content_hash(text)
    assert result["suggested_profile"] == "tech"
    assert "內建技術詞" in result["profile_reason"]
    assert result["active_whitelist_terms"] == ["高可用性", "冪等性", "MemFuse"]
    assert result["suspect_terms_for_review"] == [
        {
            "term": "局部性",
            "count": 2,
            "sample_sentence": "透過快取提升資料存取的局部性。",
            "reason": "SUFFIX_XING_UNREGISTERED (帶有『~性/~度/~化』後綴但未登錄於白名單)",
        },
        {
            "term": "進行 Fine-tuning",
            "count": 1,
            "sample_sentence": "我們對小模型進行 Fine-tuning。",
            "reason": "CODE_SWITCH_WEAK_VERB (弱動詞後接英文專有動作)",
        },
    ]

    add_local_whitelist(
        repo,
        result["target_id"],
        [{"term": "進行 Fine-tuning"}],
        content_hash=result["content_hash"],
        state_dir=state_dir,
    )
    reviewed = analyze()
    assert reviewed["active_whitelist_terms"] == [
        "高可用性", "冪等性", "MemFuse", "進行 Fine-tuning",
    ]
    assert reviewed["suspect_terms_for_review"] == result["suspect_terms_for_review"][:1]
    assert article.read_bytes() == text.encode("utf-8")


def test_suffixes_and_code_switch_keep_original_boundaries():
    text = (
        "做一次 Benchmark，進行了 Fine-tuning。進行 Fine-tuning-next。"
        "系統的延遲度、局部性和模組化。MemFuseX 用於向量化。"
    )
    result = _preflight_stdin(
        text, [{"term": "MemFuse"}, {"term": "進行 Fine-tuning"}, {"term": "向量化"}]
    )
    assert result["active_whitelist_terms"] == ["向量化"]
    assert [item["term"] for item in result["suspect_terms_for_review"]] == [
        "做一次 Benchmark", "進行了 Fine-tuning", "進行 Fine-tuning-next",
        "延遲度", "局部性", "模組化",
    ]


def test_degree_quantities_are_ignored_while_suffix_terms_are_reviewed():
    text = (
        "今天氣溫一度降到十度，出門前記得加件外套。"
        "氣溫從零下三度回升到 3.5 度。"
        "攝氏二十度與複雜度、滿意度無關。兩度測量後變成３度。"
    )
    result = _preflight_stdin(text)
    assert [item["term"] for item in result["suspect_terms_for_review"]] == [
        "複雜度", "滿意度",
    ]


def test_repeated_suffix_term_is_counted_across_different_tokenization():
    sentence = "提升資料存取的局部性後，再量測局部性。"
    text = sentence + "先記錄速度，再量測加速度與速度。"
    result = _preflight_stdin(text)
    suspects = result["suspect_terms_for_review"]
    assert [(item["term"], item["count"]) for item in suspects] == [
        ("局部性", 2), ("速度", 2), ("加速度", 1),
    ]
    assert suspects[0]["sample_sentence"] == sentence

    reviewed = _preflight_stdin(text, [{"term": "局部性"}])
    assert reviewed["active_whitelist_terms"] == ["局部性"]
    assert reviewed["suspect_terms_for_review"] == suspects[1:]


def test_suffix_term_keeps_adjacent_ke_prefix_on_a_single_verb():
    sentence = "這套查詢引擎在大型資料表上的可觀察性仍然不足，排錯時很難定位瓶頸。"
    text = (
        sentence + "我們打算補齊追蹤指標，讓整體的可觀察性達到上線標準。"
        "這份設定可提高系統的穩定性，維護時段也可彈性調整。"
    )
    result = _preflight_stdin(text)
    suspects = result["suspect_terms_for_review"]
    assert [(item["term"], item["count"]) for item in suspects] == [
        ("可觀察性", 2), ("穩定性", 1), ("彈性", 1),
    ]
    assert suspects[0]["sample_sentence"] == sentence

    reviewed = _preflight_stdin(text, [{"term": "可觀察性"}])
    assert reviewed["active_whitelist_terms"] == ["可觀察性"]
    assert reviewed["suspect_terms_for_review"] == suspects[1:]


def test_multiword_code_switch_is_reviewed_and_protected_as_a_complete_phrase():
    sentence = "我們先進行 A/B testing，再做一次 load testing。"
    text = sentence + "\n明天再進行 A/B testing\nBenchmark 另記。"
    result = _preflight_stdin(text, [{"term": "進行 A"}])
    assert [
        (item["term"], item["count"], item["sample_sentence"])
        for item in result["suspect_terms_for_review"]
    ] == [
        ("進行 A/B testing", 2, sentence),
        ("做一次 load testing", 1, sentence),
    ]
    assert result["active_whitelist_terms"] == []

    reviewed = _preflight_stdin(text, [{"term": "進行 A/B testing"}])
    assert reviewed["active_whitelist_terms"] == ["進行 A/B testing"]
    assert [item["term"] for item in reviewed["suspect_terms_for_review"]] == [
        "做一次 load testing",
    ]


def test_code_switch_ends_before_temporal_context():
    sentence = "我們明天進行 A/B testing before release，然後公佈結果。"
    text = (
        sentence + "做一次 load testing After deployment，接著做 before-and-after testing。"
        "最後進行 before and after testing。"
    )
    result = _preflight_stdin(text)
    suspects = result["suspect_terms_for_review"]
    assert [item["term"] for item in suspects] == [
        "進行 A/B testing", "做一次 load testing", "做 before-and-after testing",
        "進行 before and after testing",
    ]
    assert suspects[0]["sample_sentence"] == sentence

    reviewed = _preflight_stdin(
        text, [{"term": "進行 A/B testing"}, {"term": "做一次 load testing"}]
    )
    assert reviewed["active_whitelist_terms"] == ["進行 A/B testing", "做一次 load testing"]
    assert reviewed["suspect_terms_for_review"] == suspects[2:]


def test_frozen_tokens_are_exempt_and_longer_terms_can_be_suspects(monkeypatch):
    adapter = JiebaPosAdapter()
    tokenize = adapter.tokenize

    def tokenize_frozen(text):
        return [
            replace(token, is_frozen=True) if token.surface in {"局部性", "延遲"} else token
            for token in tokenize(text)
        ]

    monkeypatch.setattr(adapter, "tokenize", tokenize_frozen)
    result = _preflight_stdin("我們改善了局部性與延遲度。", tokenizer=adapter)
    assert [item["term"] for item in result["suspect_terms_for_review"]] == ["延遲度"]


def test_preflight_masks_markdown_before_matching_and_keeps_original_sentence():
    sample = "把[局部性](https://example.test/高可用性)記下來。"
    text = (
        "---\r\ntitle: 高可用性 MemFuse\r\n---\r\n"
        "```python\r\n進行 Fine-tuning。\r\n```\r\n"
        "> 引文包含模組化與冪等性。\r\n"
        "進行`略過的區塊` Benchmark。\r\n" + sample
    )
    result = _preflight_stdin(text, [{"term": "高可用性"}, {"term": "MemFuse"}])
    assert result["active_whitelist_terms"] == []
    assert result["suggested_profile"] == "social"
    assert result["content_hash"] == content_hash(text)
    assert [item["term"] for item in result["suspect_terms_for_review"]] == ["局部性"]
    assert result["suspect_terms_for_review"][0]["sample_sentence"] == sample


def test_stdin_ephemeral_whitelist_lasts_one_run_and_profile_can_be_overridden(tmp_path):
    text = "為了提升高可用性與局部性，我們進行 Fine-tuning。"
    settings = load_settings_for_stdin(
        text, ephemeral_terms=["局部性", "進行 Fine-tuning"], state_dir=tmp_path
    )
    result = _preflight_stdin(
        text,
        settings["whitelist"],
        profile_override="essay",
        fallback_profile=settings["effective_profile"],
    )
    assert result["source_type"] == result["target_id"] == "stdin"
    assert result["content_hash"] == settings["content_hash"]
    assert result["suggested_profile"] == "essay"
    assert "--profile" in result["profile_reason"]
    assert result["active_whitelist_terms"] == ["高可用性", "局部性", "進行 Fine-tuning"]
    assert result["suspect_terms_for_review"] == []
    assert not (tmp_path / "workspaces").exists()

    later_settings = load_settings_for_stdin(text, state_dir=tmp_path)
    later = _preflight_stdin(text, later_settings["whitelist"])
    assert later["active_whitelist_terms"] == ["高可用性"]
    assert [item["term"] for item in later["suspect_terms_for_review"]] == [
        "局部性", "進行 Fine-tuning",
    ]


@pytest.mark.parametrize(
    ("text", "profile", "reason"),
    [
        ("今天好開心！等下去散步。回家再泡杯茶。", "social", "短句"),
        (
            "窗外的微光沿著老屋安靜的門廊移動，讓我想起童年夏日那些悠長而無事的午後。",
            "essay",
            "長句",
        ),
        ("我們對模型進行 Fine-tuning。", "tech", "弱動詞"),
        ("我們今天整理 Python 與 Redis 的 FastAPI 指南。", "tech", "英文詞"),
        (
            "本服務採用非同步佇列處理寫入請求，避免高併發時鎖死主資料庫。"
            "當下游節點回應逾時，系統會依指數退避策略重試三次，以維持整體架構的穩定性。",
            "tech",
            "併發",
        ),
        (
            "今天下班路過巷口那家鹹酥雞，明明只是想買份甜不辣，結果又手滑點了一大袋😂 "
            "老闆還順手多塞了幾片九層塔，減肥的事明天再說吧！",
            "social",
            "😂",
        ),
        (
            "📌 啟用非同步佇列前，先確認資料庫的索引已經建立。節點逾時則依退避時間重試。",
            "tech",
            "索引",
        ),
        (
            "今天看了公司那個資料庫，到底誰想出這麼難記的名稱啦😂！"
            "我決定先去買杯手搖再回來。",
            "social",
            "「啦」",
        ),
        (
            "今天忙到忘了中午吃什麼啦！回家還得想晚餐，算了先去散步吧！",
            "social",
            "句尾語氣詞",
        ),
        (
            "晚上路過城南那間老酒吧🍺，想起父親在那裡彈琴的日子，窗邊的一盞燈還和從前一樣亮。",
            "essay",
            "長句",
        ),
        ("\n ```\n高可用性\n```", "essay", "設定值 essay"),
    ],
)
def test_profile_reason_identifies_decisive_signal(text, profile, reason):
    result = _preflight_stdin(text, fallback_profile="essay")
    assert result["suggested_profile"] == profile
    assert reason in result["profile_reason"]


def test_conflicting_profile_signals_use_configured_profile_and_explain_both():
    text = "非同步佇列和資料庫的回應逾時終於查清楚啦😂！晚上可以睡了。"
    result = _preflight_stdin(text, fallback_profile="essay")
    assert result["suggested_profile"] == "essay"
    assert all(
        clue in result["profile_reason"] for clue in ("資料庫", "「啦」", "採用設定值 essay")
    )

    overridden = _preflight_stdin(text, fallback_profile="essay", profile_override="social")
    assert overridden["suggested_profile"] == "social"
    assert "--profile" in overridden["profile_reason"]
