"""L1~L4 各層匯出 scan(tokens, sentence_ctx, profile) 以掛載至 Scanner。"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from typing import TYPE_CHECKING, Callable, Iterator, Literal, Sequence, TypedDict

if TYPE_CHECKING:
    from ..tokenizer_adapter import Token


class _IssueDetails(TypedDict, total=False):
    char_idx: int
    suggested_breakpoint: int
    severity: Literal["info"]
    # 僅供 Scanner 彙整句內必留詞，輸出 JSON 時移除。
    _replaceable_token_starts: tuple[int, ...]


class Issue(_IssueDetails):
    layer: str
    rule_id: str
    priority: int
    span: str
    pos_pattern: str
    theoretical_basis: str
    instruction: str


class RuleProfile(TypedDict):
    name: str
    description: str
    max_pre_modifier_len: int
    max_clause_len: int
    disabled_rules: list[str]
    idiom_replacement_aggressiveness: str


@dataclass(frozen=True)
class SentenceContext:
    """句內 Token 和分句共用從 0 起算的 Unicode 字元座標。

    text 保留原文長度，遮罩位置以等長 NUL 字元表示。
    original_text 供跨遮罩的診斷取回原文跨度。
    clause_spans 使用半開區間，依句內原文排序。
    """

    text: str
    clause_spans: tuple[tuple[int, int], ...]
    is_paragraph_end: bool
    original_text: str | None = None


Scan = Callable[[Sequence["Token"], SentenceContext, RuleProfile], Sequence[Issue]]

_RULE_MODULES = {
    "L1": "l1_vitality",
    "L2": "l2_branching",
    "L3": "l3_logic",
    "L4": "l4_cadence",
}
LAYERS = tuple(_RULE_MODULES)


def load_scanners(requested_layer: str) -> Iterator[tuple[str, Scan]]:
    """從已註冊的層級模組載入 scan，讓還在開發的佔位模組保持空輸出。"""
    for layer in LAYERS if requested_layer == "ALL" else (requested_layer,):
        module = import_module(f".{_RULE_MODULES[layer]}", __name__)
        scan = getattr(module, "scan", None)
        if scan is not None:
            yield layer, scan
