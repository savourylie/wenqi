"""L0 Markdown 遮罩與「的／地／得」詞性窗口消歧義（規格 §5.1B/C）。"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, replace
from functools import lru_cache
from itertools import chain
from typing import Iterator, Optional, Sequence, TypedDict

from engine import load_default_lexicons
from engine.tokenizer_adapter import JiebaPosAdapter, Token, TokenizerAdapter

DE_ATTR = "DE_ATTR"
DE_ADV = "DE_ADV"
DE_COMP = "DE_COMP"
RESULT_ADVERBS = frozenset({"成功", "順利"})
ACHIEVEMENT_VERBS = frozenset({"推翻", "發明", "泳渡", "解決", "完成", "突破"})

_DE_MARKERS = {"的", "地", "得"}
_ADVERB_MARKERS = {"的", "地"}
_MODAL_VERBS = {"能", "會", "可以"}
_NOUN_POS = {"n", "nr", "ns", "nt", "nz"}
_QUANTIFIER_POS = {"m", "q", "mq"}
_COMPLEMENT_ADJECTIVE_POS = {"a", "ad", "b", "an"}
_ADVERBIAL_POS = {"d", "a", "ad", "b"}
_LONG_MODIFIER_POS = _ADVERBIAL_POS | {"l", "z"}
_VERBAL_IDIOMS = {"知其不可為而為之", "明知不可為而為之"}
_PREDICATE_PREFIXES = {"竟然", "居然", "還是", "大"}
_VERBAL_POS = {"v", "vn"}
_VERB_INTRODUCERS = {"去", "來", "把", "被", "將"}
_ASPECT_PARTICLES = {"了", "過", "著"}
_OBJECT_POS = {"n", "nz", "r"}
_DEMONSTRATIVE_PREFIXES = ("這", "那", "此", "該")
_DEGREE_ADVERBS = (
    "很", "太", "極", "更", "不夠", "相當", "十分", "格外", "頗", "稍微",
    "比較", "較為", "過於", "極其", "無比", "異常", "越來越", "那麼", "這麼",
    "有點", "非常",
)
_RESULT_STATES = {
    "要命", "死去活來", "一乾二淨", "清楚", "好", "快", "多", "遠", "慢",
    "乾淨", "明白", "飽", "累", "壞", "完", "懂",
}

_FRONTMATTER = re.compile(
    r"\A\ufeff?---[ \t]*\r?\n.*?^(?:---|\.\.\.)[ \t]*(?=\r?$)", re.MULTILINE | re.DOTALL
)
_FENCE_LINE = re.compile(
    r"^ {0,3}(?P<marker>`{3,}|~{3,})(?P<info>[^\r\n]*)(?=\r?$)", re.MULTILINE
)
_QUOTE_LINE = re.compile(r"^ {0,3}>[^\r\n]*", re.MULTILINE)
_MASKED_CHARACTERS = re.compile(r"[^\r\n]+")
_INLINE_MASK = re.compile(
    r"(?<!`)(?P<ticks>`+)(?!`)"
    r"(?:(?!\r?\n[ \t]*\r?\n)[\s\S])*?(?<!`)(?P=ticks)(?!`)"
    r"|(?P<link>\]\()"
    r"|(?<!\$)\$(?![\s$])(?:\\[^\r\n]|[^$\\\r\n])*?(?<!\s)\$(?!\$)"
)
_LINK_DELIMITER = re.compile(
    r"\\[^\r\n]|<[^<>\r\n]*>"
    r"""|(?<=[ \t])(?P<quote>["'])(?:\\[^\r\n]|(?!(?P=quote))[^\\\r\n])*(?P=quote)(?=[ \t]*\))"""
    r"|[()\r\n]"
)


class L0Error(ValueError):
    """L0 無法處理輸入。"""


@dataclass(frozen=True)
class MaskRegion:
    """同一遮罩區在原文與遮罩後文本的半開字元區間。"""

    original_start: int
    original_end: int
    masked_start: int
    masked_end: int
    is_block: bool = False


class DeNormalizationEntry(TypedDict):
    char_idx: int
    surface: str
    true_role: str


class L0Issue(TypedDict):
    layer: str
    rule_id: str
    char_idx: int
    surface: str
    suggestion: str
    theoretical_basis: str


@dataclass
class L0Result:
    """L0 文件級輸出。Token 與診斷的位置均使用原文字元座標。"""

    masked_text: str
    mask_regions: list[MaskRegion]
    tokens: list[Token]
    de_normalization_map: list[DeNormalizationEntry]
    issues: list[L0Issue]


def _fenced_code_spans(text: str, start: int) -> Iterator[tuple[int, int]]:
    opener = None
    for line in _FENCE_LINE.finditer(text, start):
        marker = line["marker"]
        if opener is None:
            if marker[0] != "`" or "`" not in line["info"]:
                opener = line
            continue

        opening_marker = opener["marker"]
        if marker.startswith(opening_marker) and not line["info"].strip(" \t"):
            yield opener.start(), line.end()
            opener = None
    if opener is not None:
        yield opener.start(), len(text)


def _block_spans(text: str) -> list[tuple[int, int]]:
    frontmatter = _FRONTMATTER.match(text)
    spans = [frontmatter.span()] if frontmatter else []
    spans.extend(_fenced_code_spans(text, frontmatter.end() if frontmatter else 0))
    spans.extend(line.span() for line in _QUOTE_LINE.finditer(text))

    # 引用標記可能在程式碼區塊內。保留外層遮罩，避免遮罩切進彼此的區間。
    merged: list[tuple[int, int]] = []
    for start, end in sorted(spans):
        if merged and start < merged[-1][1]:
            previous_start, previous_end = merged[-1]
            merged[-1] = (previous_start, max(previous_end, end))
        else:
            merged.append((start, end))
    return merged


def _is_escaped(text: str, position: int) -> bool:
    start = position
    while start > 0 and text[start - 1] == "\\":
        start -= 1
    return (position - start) % 2 == 1


def _link_ends(text: str, start: int, end: int) -> dict[int, int]:
    # 一次配對所有連結括號，跳過角括號目的地與引號標題內的括號。
    openers: list[int] = []
    ends: dict[int, int] = {}
    for match in _LINK_DELIMITER.finditer(text, start, end):
        delimiter = match[0]
        if delimiter == "(":
            openers.append(match.start())
        elif delimiter == ")" and openers:
            opener = openers.pop()
            if opener > start and text[opener - 1] == "]":
                ends[opener - 1] = match.end()
        elif delimiter in {"\r", "\n"}:
            openers.clear()
    return ends


def _inline_spans(text: str, start: int, end: int) -> Iterator[tuple[int, int]]:
    cursor = start
    link_ends = None
    while match := _INLINE_MASK.search(text, cursor, end):
        cursor = match.end()
        if _is_escaped(text, match.start()):
            cursor = match.end("ticks") if match["ticks"] else match.start() + 1
            continue

        if match["link"]:
            if link_ends is None:
                link_ends = _link_ends(text, start, end)
            link_end = link_ends.get(match.start())
            if link_end is None:
                continue
            cursor = link_end
        yield match.start(), cursor


def mask_markdown(text: str) -> tuple[str, list[MaskRegion]]:
    """將六類受保護區塊替換為 ``__MASK_i__``，並保存對應區間。"""
    if not isinstance(text, str):
        raise L0Error("L0 輸入必須為字串")

    spans: list[tuple[int, int, bool]] = []
    cursor = 0
    for start, end in _block_spans(text):
        spans.extend((left, right, False) for left, right in _inline_spans(text, cursor, start))
        spans.append((start, end, True))
        cursor = end
    spans.extend((left, right, False) for left, right in _inline_spans(text, cursor, len(text)))

    parts: list[str] = []
    regions: list[MaskRegion] = []
    original_cursor = masked_cursor = 0
    for index, (start, end, is_block) in enumerate(spans):
        placeholder = f"__MASK_{index}__"
        parts.extend((text[original_cursor:start], placeholder))
        masked_start = masked_cursor + start - original_cursor
        masked_cursor = masked_start + len(placeholder)
        regions.append(MaskRegion(start, end, masked_start, masked_cursor, is_block))
        original_cursor = end
    parts.append(text[original_cursor:])
    return "".join(parts), regions


def visible_prose(text: str, regions: Sequence[MaskRegion]) -> str:
    """遮罩區以等長佔位字元表示，保留原文座標與換行。"""
    parts = []
    start = 0
    for region in regions:
        parts.append(text[start:region.original_start])
        hidden = text[region.original_start:region.original_end]
        parts.append(_MASKED_CHARACTERS.sub(lambda match: "\0" * len(match[0]), hidden))
        start = region.original_end
    parts.append(text[start:])
    return "".join(parts)


def _restore_tokens(
    masked_text: str, regions: list[MaskRegion], tokenizer: TokenizerAdapter
) -> list[Token]:
    tokens = iter(tokenizer.tokenize(masked_text))
    token = next(tokens, None)
    restored: list[Token] = []
    visible_start = offset = 0

    for region in chain(regions, (None,)):
        visible_end = region.masked_start if region is not None else len(masked_text)
        while token is not None and token.start_char < visible_end:
            start = max(token.start_char, visible_start)
            end = min(token.end_char, visible_end)
            if start < end:
                pieces: Sequence[Token]
                if start == token.start_char and end == token.end_char:
                    pieces, shift = (token,), offset
                else:
                    # 跨越佔位符的 token 只重新分詞可見部分，保留正確詞性與冷凍狀態。
                    pieces, shift = tokenizer.tokenize(masked_text[start:end]), start + offset
                restored.extend(
                    replace(
                        piece,
                        start_char=piece.start_char + shift,
                        end_char=piece.end_char + shift,
                        true_de_role="",
                    )
                    for piece in pieces
                )
            if token.end_char > visible_end:
                break
            token = next(tokens, None)

        if region is not None:
            restored.append(
                Token(
                    surface=masked_text[region.masked_start:region.masked_end],
                    pos="x",
                    start_char=region.original_start,
                    end_char=region.original_end,
                    is_frozen=False,
                )
            )
            visible_start = region.masked_end
            offset = region.original_end - region.masked_end
    return restored


def _is_complement(left: Token, right: Token, right2: Optional[Token]) -> bool:
    if left.pos not in {"v", "a"} or left.surface in _MODAL_VERBS:
        return False

    if right.surface in _DEGREE_ADVERBS:
        # 程度詞可獨立出現在句尾，也可被 jieba 拆成「十分」＋「明白」。
        if right2 is None or right2.surface in {"\n", "\r", "\r\n"} or all(
            unicodedata.category(char).startswith("P") for char in right2.surface
        ):
            return True
        return right2.pos in _COMPLEMENT_ADJECTIVE_POS or right2.surface in _RESULT_STATES

    # 「很多書」、「更新內容」的首詞也可能以程度副詞的字開頭。
    if right2 is not None and right2.pos in _NOUN_POS:
        return False
    return (
        (right.surface.startswith(_DEGREE_ADVERBS) and right.pos not in _NOUN_POS)
        or right.surface in _RESULT_STATES
        or right.pos in _COMPLEMENT_ADJECTIVE_POS
    )


@lru_cache(maxsize=1)
def _weak_verbs() -> frozenset[str]:
    return frozenset(entry["term"] for entry in load_default_lexicons()["weak_verbs"])


def _is_nominal_lead(token: Token) -> bool:
    return (
        token.pos in _QUANTIFIER_POS
        or (token.pos == "r" and token.surface.startswith(_DEMONSTRATIVE_PREFIXES))
        or token.surface in _weak_verbs()
    )


def _is_adverbial(
    left2: Optional[Token], left: Token, right: Token, right2: Optional[Token]
) -> bool:
    if left.pos != "i" and (len(left.surface) < 2 or left.pos not in _ADVERBIAL_POS):
        return False

    if right.pos == "vn":
        return (
            right2 is not None
            and (right2.surface in _ASPECT_PARTICLES or right2.pos in _OBJECT_POS)
            and (left2 is None or not _is_nominal_lead(left2))
        )
    return right.pos == "v" or (
        right.surface in _VERB_INTRODUCERS and right2 is not None and right2.pos in _VERBAL_POS
    )


def han_length(text: str) -> int:
    return sum(
        char == "〇" or unicodedata.name(char, "").startswith(
            ("CJK UNIFIED IDEOGRAPH", "CJK COMPATIBILITY IDEOGRAPH")
        )
        for char in text
    )


def _joined(left: Token, right: Token) -> bool:
    return left.end_char == right.start_char and not (left.is_frozen or right.is_frozen)


def _verbal_idiom_start(tokens: Sequence[Token], end: int, suffix: str = "") -> int | None:
    phrase = suffix
    for index in range(end - 1, -1, -1):
        if not _joined(tokens[index], tokens[index + 1]):
            break
        phrase = tokens[index].surface + phrase
        if phrase in _VERBAL_IDIOMS:
            return index
        if not any(idiom.endswith(phrase) for idiom in _VERBAL_IDIOMS):
            break
    return None


def long_adverbial_start(tokens: Sequence[Token], marker: int) -> int | None:
    """成語、四字以上的修飾片語或重疊量詞，可作長狀語。"""
    if marker == 0 or not _joined(tokens[marker - 1], tokens[marker]):
        return None
    left = tokens[marker - 1]
    if left.pos == "i" or (left.pos in _VERBAL_POS and han_length(left.surface) >= 4):
        return marker - 1

    if marker >= 2 and _joined(tokens[marker - 2], left):
        previous = tokens[marker - 2]
        if left.pos in _QUANTIFIER_POS and previous.surface == left.surface:
            return marker - 2 if han_length(left.surface) >= 2 else None

    if left.surface.endswith("之"):
        idiom = _verbal_idiom_start(tokens, marker)
        if idiom is not None:
            return idiom
    start = marker
    while start > 0 and tokens[start - 1].pos in _LONG_MODIFIER_POS:
        if not _joined(tokens[start - 1], tokens[start]):
            break
        start -= 1
    length = sum(han_length(token.surface) for token in tokens[start:marker])
    return start if length >= 4 else None


def adverbial_verb_index(tokens: Sequence[Token], marker: int) -> int | None:
    """在同一片段內略過「竟然大唱」、「還是去赴」等動詞前綴。"""
    for index in range(marker + 1, len(tokens)):
        token = tokens[index]
        if not _joined(tokens[index - 1], token):
            break
        if token.surface in _VERB_INTRODUCERS and index + 1 < len(tokens):
            following = tokens[index + 1]
            if following.pos in _VERBAL_POS and _joined(token, following):
                return index + 1
        if token.pos in _VERBAL_POS:
            return index
        # 「的」後的普通副詞也可以修飾名物化事件，如「橫貫公路的再度坍方」。
        if token.surface not in _PREDICATE_PREFIXES and (
            tokens[marker].surface != "地" or token.pos not in {"d", "ad"}
        ):
            break
    return None


def _split_token(token: Token, index: int, left_pos: str, right_pos: str) -> tuple[Token, Token]:
    midpoint = token.start_char + index
    return (
        replace(token, surface=token.surface[:index], pos=left_pos, end_char=midpoint),
        replace(token, surface=token.surface[index:], pos=right_pos, start_char=midpoint),
    )


def _repair_de_boundaries(tokens: Sequence[Token]) -> Iterator[Token]:
    index = 0
    while index < len(tokens):
        token = tokens[index]
        left = tokens[index - 1] if index else None
        right = tokens[index + 1] if index + 1 < len(tokens) else None
        if (
            token.pos == "z" and len(token.surface) > 2 and token.surface.endswith("的")
            and right is not None and right.pos in _NOUN_POS and _joined(token, right)
        ):
            # 例如「彎彎的」被合成一詞，後接名詞時應保留定語助詞。
            yield from _split_token(token, len(token.surface) - 1, token.pos, "uj")
        elif token.surface in {"之的", "之地"} and _verbal_idiom_start(tokens, index, "之") is not None:
            marker_pos = "uv" if token.surface[1] == "地" else "uj"
            yield from _split_token(token, 1, "u", marker_pos)
        elif (
            left is not None and right is not None and len(token.surface) == 2
            and token.surface[0] in _ADVERB_MARKERS and _joined(left, token) and _joined(token, right)
            and (
                (token.surface[1] == "想" and right.surface == "出" and left.pos == "i")
                or (token.surface[1] == "泳" and right.surface == "渡" and left.surface in RESULT_ADVERBS)
            )
        ):
            # jieba 可能把「地想出」和「地泳渡」拆成「地想＋出」與「地泳＋渡」。
            marker_pos = "uv" if token.surface[0] == "地" else "uj"
            marker, verb = _split_token(token, 1, marker_pos, "v")
            yield marker
            yield replace(verb, surface=verb.surface + right.surface, end_char=right.end_char)
            index += 1
        elif (
            token.surface == "解決問題" and index >= 2 and left is not None
            and left.surface in _ADVERB_MARKERS
            and tokens[index - 2].surface in RESULT_ADVERBS
            and _joined(tokens[index - 2], left) and _joined(left, token)
            and (
                left.surface == "地" or (
                    (index < 3 or not _is_nominal_lead(tokens[index - 3]))
                    and (right is None or right.surface not in _DE_MARKERS)
                )
            )
        ):
            yield from _split_token(token, 2, "v", "n")
        else:
            yield token
        index += 1


def _is_long_adverbial(tokens: Sequence[Token], marker: int, start: int) -> bool:
    verb_index = adverbial_verb_index(tokens, marker)
    if verb_index is None:
        return False
    if tokens[marker].surface == "地":
        return True
    # 「的＋動名詞」仍需謂語線索，避免把名詞組誤作狀語。
    verb = tokens[verb_index]
    if verb.pos == "v":
        return True
    if start > 0 and _is_nominal_lead(tokens[start - 1]):
        return False
    if verb_index + 1 == len(tokens):
        return False
    following = tokens[verb_index + 1]
    return following.surface in _ASPECT_PARTICLES or following.pos in _OBJECT_POS


def _normalize_de(
    tokens: list[Token],
) -> tuple[list[DeNormalizationEntry], list[L0Issue]]:
    normalization_map: list[DeNormalizationEntry] = []
    issues: list[L0Issue] = []
    for i, token in enumerate(tokens):
        if token.surface not in _DE_MARKERS or token.is_frozen:
            continue

        left = tokens[i - 1] if i >= 1 else None
        right = tokens[i + 1] if i + 1 < len(tokens) else None
        right2 = tokens[i + 2] if i + 2 < len(tokens) else None
        long_start = long_adverbial_start(tokens, i) if token.surface in _ADVERB_MARKERS else None
        long_adverbial = long_start is not None and _is_long_adverbial(tokens, i, long_start)
        if left is not None:
            if token.surface == "地" and left.pos in _QUANTIFIER_POS and not long_adverbial:
                continue  # 「一塊地」的「地」是名詞。
            if token.surface == "得" and (left.pos == "r" or left.pos in _NOUN_POS):
                continue  # 主語後的助動詞 děi 不屬於三種助詞。

        role = DE_ATTR
        if left is not None and right is not None:
            likeness_complement = (
                token.surface == "得" and left.surface == "長" and right.pos == "v"
                and right.surface in {"像", "好像"} and _joined(left, token) and _joined(token, right)
            )
            if likeness_complement or _is_complement(left, right, right2):
                role = DE_COMP
            elif long_adverbial or _is_adverbial(tokens[i - 2] if i >= 2 else None, left, right, right2):
                role = DE_ADV
            elif (
                token.surface == "地" and left.surface in RESULT_ADVERBS
                and right.surface in ACHIEVEMENT_VERBS and _joined(left, token) and _joined(token, right)
            ):
                role = DE_ADV

        token.true_de_role = role
        normalization_map.append(
            DeNormalizationEntry(char_idx=token.start_char, surface=token.surface, true_role=role)
        )
        if role == DE_COMP and token.surface != "得":
            issues.append(
                L0Issue(
                    layer="L0",
                    rule_id="L0_TYPO_DE_COMP",
                    char_idx=token.start_char,
                    surface=token.surface,
                    suggestion="得",
                    theoretical_basis="補語標記應用「得」",
                )
            )
    return normalization_map, issues


def normalize(text: str, tokenizer: Optional[TokenizerAdapter] = None) -> L0Result:
    """遮罩、分詞與消歧義。可傳入已註冊白名單的分詞器。"""
    masked_text, regions = mask_markdown(text)
    adapter = tokenizer if tokenizer is not None else JiebaPosAdapter()
    tokens = list(_repair_de_boundaries(_restore_tokens(masked_text, regions, adapter)))
    normalization_map, issues = _normalize_de(tokens)
    return L0Result(masked_text, regions, tokens, normalization_map, issues)
