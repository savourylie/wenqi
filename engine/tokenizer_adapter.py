"""TokenizerAdapter 抽象層（預設實作 JiebaPosAdapter）。

實作於 TICKET-003。規格：zh_polish_skill_spec_v2.md §5.1A（介面與 JiebaPosAdapter
行為）、§3.1（算力分層與冷啟動 < 0.1s）。

設計決策（TICKET-003 clarify）：
- Q1 繁體支援：jieba 內建詞典偏簡體。以離線 opencc（``s2twp``，僅 dev 依賴）把
  jieba ``dict.txt`` 的 word 欄簡轉繁，產出 ``config/jieba_dict_traditional.txt``
  （见 ``scripts/build_traditional_dict.py``）。adapter 初始化以
  ``jieba.posseg.initialize`` 載入這份繁體詞典——它同時重建 tokenizer FREQ 與
  posseg ``word_tag_tab``，故詞性標籤正確（单纯 ``jieba.set_dictionary`` 不會重建
  ``word_tag_tab``，會使已知詞詞性全變 ``x``）。surface 全程保留原繁體字，
  绝不轉換輸入文字。
- Q2 冷啟動：詞典＋word_tag 首次載入（含 jieba 快取建立）屬行程層級一次性成本，
  依 §3.1／AC 排除於計時之外。``_ensure_dictionary`` 以 module guard 保证只載入
  一次；後續 adapter 实例只做 register_whitelist＋tokenize（暖機後 < 0.1s）。

邊界：本模組只負責白名單註冊、``is_frozen`` 標記與字元索引還原。``true_de_role``
留空字串，由 L0（TICKET-004）填入；Markdown 遮罩與「的／地／得」消歧義不在本票。
白名單語意（哪些詞該冷凍）由 L0/L5 決定；三級合併由 state_manager.merge_whitelists
（TICKET-002）产出 ``List[dict]``（必含 pos）餵入 ``register_whitelist``。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Protocol, runtime_checkable

import jieba.posseg as pseg

logger = logging.getLogger(__name__)

#: 繁體優化詞典（離線 opencc 產出，TICKET-003 Q1）。
TRADITIONAL_DICT_PATH = (
    Path(__file__).resolve().parent.parent / "config" / "jieba_dict_traditional.txt"
)

#: 白名單條目缺 pos 時的預設詞性（專有名詞），與 state_manager.DEFAULT_POS 一致。
_DEFAULT_POS = "nz"
LATIN_WORD_CHAR = r"[A-Za-z0-9_/‐‑-]"
LATIN_WORD = r"[A-Za-z][A-Za-z0-9]*(?:[-‐‑/][A-Za-z0-9]+)*"
_HORIZONTAL_SPACE = r"[ \t\u3000]"
_TEMPORAL_CONNECTOR = rf"(?i:before|after){_HORIZONTAL_SPACE}"
_BEFORE_AND_AFTER = (
    rf"(?i:before{_HORIZONTAL_SPACE}+and{_HORIZONTAL_SPACE}+after)(?!{LATIN_WORD_CHAR})"
)
ENGLISH_ACTION_AFTER_VERB = (
    rf"(?:{_HORIZONTAL_SPACE}*[了過著])?"
    rf"(?:{_HORIZONTAL_SPACE}*(?:\d+|[〇零一二兩三四五六七八九十百千萬億兆幾數]+)次)?"
    rf"{_HORIZONTAL_SPACE}*(?:{_BEFORE_AND_AFTER}|{LATIN_WORD})"
    rf"(?:{_HORIZONTAL_SPACE}+(?!{_TEMPORAL_CONNECTOR}){LATIN_WORD})*"
    rf"(?!{LATIN_WORD_CHAR})"
)


def whitelist_matches(text: str, terms: Iterable[str]) -> list[re.Match[str]]:
    """比對作者確認的原文詞組，保留英文單詞邊界與原文字元座標。"""
    hits = []
    for term in dict.fromkeys(terms):
        pattern = re.escape(term)
        if re.fullmatch(LATIN_WORD_CHAR, term[0]):
            pattern = rf"(?<!{LATIN_WORD_CHAR})" + pattern
        if re.fullmatch(LATIN_WORD_CHAR, term[-1]):
            pattern += rf"(?!{LATIN_WORD_CHAR})"
        hits.extend(re.finditer(pattern, text))
    return sorted(hits, key=lambda hit: hit.start())


class TokenizerError(ValueError):
    """分詞器初始化、白名單註冊或分詞失敗。"""


@dataclass
class Token:
    """分詞結果（§5.1A 欄位完全一致）。

    ``true_de_role`` 預設空字串；若為「的／地／得」，由 L0（TICKET-004）填入
    ``DE_ATTR`` | ``DE_ADV`` | ``DE_COMP``。
    """

    surface: str  # 字面詞彙
    pos: str  # 詞性標籤（ICTCLAS/Jieba 兼容：n, v, vn, a, d, p, c, uj, uv, ud, i, nz, r, m, q…）
    start_char: int  # 原句起始字元索引
    end_char: int  # 原句結束字元索引
    is_frozen: bool  # 是否為 L5 白名單保護詞
    true_de_role: str = ""


@runtime_checkable
class TokenizerAdapter(Protocol):
    """可替換的分詞器抽象層（§5.1A）。

    未來抽換分詞器只需實作此 Protocol，規則引擎不需改動。
    """

    def register_whitelist(self, terms: List[dict]) -> None:
        """註冊白名單詞條（``List[dict]``，每條含 ``term``，可含 ``pos``／``note``）。"""
        ...

    def tokenize(self, text: str) -> List[Token]:
        """分詞並回傳 Token 串（含字元索引與 is_frozen 標記）。"""
        ...


# 行程層級一次性詞典載入 guard（Q2：首次載入排除於冷啟動計時之外）。
_dictionary_initialized = False


def _ensure_dictionary(dict_path: Path) -> None:
    """以繁體詞典初始化 jieba.posseg（只執行一次）。

    ``pseg.initialize`` 同時重建 tokenizer FREQ 與 posseg ``word_tag_tab``，
    使繁體詞分段與詞性皆正確。首次呼叫含詞典快取建立／word_tag 載入（一次性
    成本，依 AC5 排除於冷啟動計時）；後續呼叫直接返回。
    """
    global _dictionary_initialized
    if _dictionary_initialized:
        return
    if not dict_path.is_file():
        raise TokenizerError(
            "找不到繁體詞典 "
            f"{dict_path}；請先執行 scripts/build_traditional_dict.py 產出。"
        )
    pseg.initialize(str(dict_path))
    _dictionary_initialized = True
    logger.info("已載入繁體優化詞典: %s", dict_path)


class JiebaPosAdapter:
    """預設分詞器實作：``jieba.posseg`` ＋ 繁體優化詞表（§5.1A）。

    初始化時載入繁體詞典（行程一次性），並逐條註冊合併白名單。
    白名單詞組在原文中以完整範圍冷凍，其餘文字交給 Jieba 分詞。
    """

    def __init__(
        self,
        terms: Optional[List[dict]] = None,
        dict_path: Optional[Path] = None,
    ) -> None:
        self._dict_path = Path(dict_path) if dict_path is not None else TRADITIONAL_DICT_PATH
        _ensure_dictionary(self._dict_path)
        self._frozen: Dict[str, str] = {}
        if terms:
            self.register_whitelist(terms)

    def register_whitelist(self, terms: List[dict]) -> None:
        """把原文詞組與指定詞性註冊到這個 adapter。

        可多次呼叫增量註冊；同詞條覆寫詞性。條目須含非空 ``term``；``pos``
        缺省補 ``nz``。無效條目拋 ``TokenizerError``。
        """
        if not isinstance(terms, list):
            raise TokenizerError("白名單必須為 List[dict]")
        entries: dict[str, str] = {}
        for idx, entry in enumerate(terms):
            if not isinstance(entry, dict):
                raise TokenizerError(f"whitelist[{idx}]: 條目必須為物件")
            term = entry.get("term")
            if not isinstance(term, str) or not term.strip():
                raise TokenizerError(f"whitelist[{idx}]: 缺少非空 term")
            pos = entry.get("pos", _DEFAULT_POS)
            if not isinstance(pos, str) or not pos.strip():
                raise TokenizerError(f"whitelist[{idx}]: pos 必須為非空字串")
            entries[term] = pos
        # tokenize 依原文範圍組成冷凍 token，讓單篇詞組與詞性留在本實例。
        self._frozen.update(entries)

    def tokenize(self, text: str) -> List[Token]:
        """分詞並還原原句字元索引（含中英夾雜），標記 is_frozen。

        jieba.posseg 不附 offset；以單調 cursor 依序 ``text.find(surface, cursor)``
        重建 start/end，空白／标点 token（pos ``x``）亦對齊。``true_de_role``
        留空字串供 L0 填入。
        """
        if not isinstance(text, str):
            raise TokenizerError("tokenize 輸入必須為字串")
        hits = whitelist_matches(text, self._frozen)
        hits.sort(key=lambda hit: (hit.start(), -len(hit[0])))
        tokens: List[Token] = []
        cursor = 0
        for hit in hits:
            if hit.start() < cursor:
                continue
            tokens.extend(self._tokenize_plain_text(text[cursor:hit.start()], cursor))
            tokens.append(Token(hit[0], self._frozen[hit[0]], hit.start(), hit.end(), True))
            cursor = hit.end()
        tokens.extend(self._tokenize_plain_text(text[cursor:], cursor))
        return tokens

    @staticmethod
    def _tokenize_plain_text(text: str, offset: int) -> Iterator[Token]:
        cursor = 0
        for word, flag in pseg.cut(text):
            idx = text.find(word, cursor)
            if idx < 0:
                raise TokenizerError(
                    f"字元索引還原失敗：{word!r} 於位置 {cursor} 之後找不到"
                )
            end = idx + len(word)
            yield Token(word, flag, offset + idx, offset + end, False)
            cursor = end
