"""TICKET-003：TokenizerAdapter 抽象層與 JiebaPosAdapter 驗證。

規格：zh_polish_skill_spec_v2.md §5.1A（Token／Protocol／JiebaPosAdapter）、
§3.1（冷啟動 < 0.1s）。

冷啟動量測（Q2）：詞典＋word_tag 首次載入屬行程一次性成本，依 AC5 排除於計時
之外；module 級 warmup fixture 先載入繁體詞典，再計時 adapter init（含
register_whitelist）＋首次 tokenize，斷言 < 0.1s 並記錄實測值。
"""

from __future__ import annotations

import dataclasses
import time
from typing import List

import pytest

from engine import load_default_lexicons
from engine.state_manager import merge_whitelists
from engine.tokenizer_adapter import (
    TRADITIONAL_DICT_PATH,
    JiebaPosAdapter,
    Token,
    TokenizerAdapter,
    TokenizerError,
)


@pytest.fixture(scope="module")
def warm() -> JiebaPosAdapter:
    """一次性暖機：載入繁體詞典＋word_tag＋首次 posseg.cut（排除於冷啟動計時）。"""
    adapter = JiebaPosAdapter()
    adapter.tokenize("暖機")
    return adapter


@pytest.fixture(scope="module")
def whitelist_terms() -> List[dict]:
    return merge_whitelists(load_default_lexicons()["tech_whitelist"])


# --- AC1：Token dataclass 欄位與 §5.1A 完全一致 -----------------------------


def test_token_fields_match_spec():
    fields = {f.name: f for f in dataclasses.fields(Token)}
    assert set(fields) == {
        "surface",
        "pos",
        "start_char",
        "end_char",
        "is_frozen",
        "true_de_role",
    }
    tok = Token(surface="高可用性", pos="nz", start_char=0, end_char=4, is_frozen=True)
    assert tok.true_de_role == ""  # 預設空字串，由 L0 填入
    assert isinstance(tok.start_char, int) and isinstance(tok.end_char, int)
    assert isinstance(tok.is_frozen, bool)


# --- AC2：TokenizerAdapter Protocol ----------------------------------------


def test_protocol_methods_and_structural_typing(warm):
    assert hasattr(TokenizerAdapter, "register_whitelist")
    assert hasattr(TokenizerAdapter, "tokenize")
    assert isinstance(warm, TokenizerAdapter)  # runtime_checkable 结构檢查

    class DummyAdapter:
        def register_whitelist(self, terms: List[dict]) -> None:
            pass

        def tokenize(self, text: str) -> List[Token]:
            return []

    assert isinstance(DummyAdapter(), TokenizerAdapter)


# --- AC3：白名單絕對冷凍 ----------------------------------------------------


def test_whitelist_terms_frozen_and_whole(warm, whitelist_terms):
    adapter = JiebaPosAdapter(whitelist_terms)
    text = "系統具備高可用性與冪等性，並透過向量化提升可觀測性"
    tokens = adapter.tokenize(text)
    surfaces = {t.surface for t in tokens}
    for term in ("高可用性", "冪等性", "向量化", "可觀測性"):
        assert term in surfaces, f"{term} 被拆碎"
    frozen = {t.surface: t for t in tokens if t.is_frozen}
    assert {"高可用性", "冪等性", "向量化", "可觀測性"} <= set(frozen)
    assert frozen["高可用性"].pos == "nz"
    assert frozen["向量化"].pos == "vn"


def test_unregistered_words_not_frozen(warm):
    adapter = JiebaPosAdapter([{"term": "高可用性", "pos": "nz"}])
    tokens = adapter.tokenize("系統具備高可用性與局部性")
    by_surface = {t.surface: t for t in tokens}
    assert by_surface["高可用性"].is_frozen is True
    # 「局部性」未登錄 → 正常分詞、不冷凍
    assert all(t.is_frozen is False for t in tokens if t.surface != "高可用性")


def test_register_whitelist_incremental_and_pos_override(warm):
    adapter = JiebaPosAdapter()
    adapter.register_whitelist([{"term": "MemFuse", "pos": "nz"}])
    adapter.register_whitelist([{"term": "FlowDance"}])  # 缺 pos 補 nz
    adapter.register_whitelist([{"term": "MemFuse", "pos": "n"}])  # 覆寫詞性
    tokens = adapter.tokenize("MemFuse 與 FlowDance 整合")
    by_surface = {t.surface: t for t in tokens}
    assert by_surface["MemFuse"].is_frozen is True
    assert by_surface["MemFuse"].pos == "n"
    assert by_surface["FlowDance"].is_frozen is True
    assert by_surface["FlowDance"].pos == "nz"


def test_register_whitelist_validation(warm):
    adapter = JiebaPosAdapter()
    with pytest.raises(TokenizerError):
        adapter.register_whitelist("not-a-list")  # type: ignore[arg-type]
    with pytest.raises(TokenizerError):
        adapter.register_whitelist([{"pos": "nz"}])  # 缺 term
    with pytest.raises(TokenizerError):
        adapter.register_whitelist([{"term": "  "}])  # 空白 term
    with pytest.raises(TokenizerError):
        adapter.register_whitelist([{"term": "x", "pos": ""}])  # 空白 pos


# --- AC4：字元索引還原（含中英夾雜） ----------------------------------------


def _assert_spans_align(text: str, tokens: List[Token]):
    prev_end = 0
    for tok in tokens:
        assert text[tok.start_char : tok.end_char] == tok.surface
        assert tok.start_char >= prev_end  # 單調、不重疊
        assert tok.end_char <= len(text)
        prev_end = tok.end_char


def test_char_indices_mixed_chinese_english(warm):
    adapter = JiebaPosAdapter()
    text = "我們對小模型進行 Fine-tuning"
    tokens = adapter.tokenize(text)
    _assert_spans_align(text, tokens)
    by_surface = {t.surface: t for t in tokens}
    assert by_surface["Fine"].start_char == text.index("Fine")
    assert by_surface["tuning"].end_char == len(text)
    assert by_surface["進行"].pos == "v"


def test_char_indices_full_coverage(warm):
    adapter = JiebaPosAdapter()
    for text in [
        "系統具備高可用性與冪等性",
        "苦口婆心的勸他跑的很快",
        "對小模型進行 Fine-tuning，提升資料存取的局部性。",
        "第一行\n第二行  with space",
    ]:
        tokens = adapter.tokenize(text)
        _assert_spans_align(text, tokens)
        # jieba.posseg 覆盖所有字元（空白／标点為 x）→ surface 串接還原原文
        assert "".join(t.surface for t in tokens) == text


def test_empty_text(warm):
    assert JiebaPosAdapter().tokenize("") == []


def test_tokenize_rejects_non_string(warm):
    with pytest.raises(TokenizerError):
        JiebaPosAdapter().tokenize(123)  # type: ignore[arg-type]


# --- AC5：冷啟動 < 0.1s（暖機後計時，Q2） -----------------------------------


def test_cold_start_under_100ms(warm, whitelist_terms, capsys):
    # warm fixture 已完成一次性詞典載入；此處計時 adapter init＋register＋首次分詞。
    start = time.perf_counter()
    adapter = JiebaPosAdapter(whitelist_terms)
    tokens = adapter.tokenize("系統具備高可用性與冪等性，並透過向量化提升可觀測性")
    elapsed = time.perf_counter() - start
    with capsys.disabled():
        print(f"\n[TICKET-003 冷啟動] 暖機後 init+register+首次分詞 = {elapsed * 1000:.2f} ms")
    assert tokens  # 确实有分詞結果
    assert elapsed < 0.1, f"冷啟動 {elapsed:.4f}s 超出 0.1s 目標"


# --- AC6：繁體常見詞不被錯誤切分 --------------------------------------------


def test_traditional_common_words_whole(warm):
    adapter = JiebaPosAdapter()
    # 常見繁體詞（簡體詞典會切錯）應保持完整且詞性合理
    cases = {
        "我們使用資料庫": "資料庫",
        "提升資訊安全": "資訊",
        "這套軟體很好用": "軟體",
    }
    for text, term in cases.items():
        tokens = adapter.tokenize(text)
        surfaces = [t.surface for t in tokens]
        assert term in surfaces, f"{term} 在 {text!r} 被切錯：{surfaces}"


def test_traditional_dict_resource_present():
    assert TRADITIONAL_DICT_PATH.is_file()


def test_missing_dict_raises(tmp_path):
    # 指定不存在的詞典 → 明確報錯（不靜默降級）
    import engine.tokenizer_adapter as ta

    saved = ta._dictionary_initialized
    ta._dictionary_initialized = False
    try:
        with pytest.raises(TokenizerError):
            JiebaPosAdapter(dict_path=tmp_path / "nope.txt")
    finally:
        ta._dictionary_initialized = saved