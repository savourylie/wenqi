"""第二層規則：修飾與包孕結構（規格 §2.2、§5.2）。"""

from __future__ import annotations

import re
from bisect import bisect_left
from typing import Iterator, Sequence

from ..l0_normalizer import (
    ACHIEVEMENT_VERBS,
    DE_ADV,
    DE_ATTR,
    RESULT_ADVERBS,
    adverbial_verb_index,
    han_length,
    long_adverbial_start,
)
from ..tokenizer_adapter import Token
from . import Issue, RuleProfile, SentenceContext


_LEFT_BRANCH = "L2_LEFT_BRANCH_OVERLOAD"
_DE_CHAIN = "L2_DE_CHAIN_NOISE"
_ADVERB_DI = "L2_ADVERB_DI_OVERUSE"
_BASIS = {
    _LEFT_BRANCH: "把核心名詞提早交代，可縮短依存距離並減少讀者等待主幹的負荷。",
    _DE_CHAIN: "疊用定語助詞容易混淆並列與從屬關係，也可能隱去名詞之間的動作。",
    _ADVERB_DI: "長狀語可以另成短分句。達成動詞已交代結果時，可省去重複的副詞。",
}

_VISIBLE_RUN = re.compile(r"[^\0,.!?;:…]+")
_COMMA = re.compile(r"[，,]")
_VERBS = {"v", "vn"}
_ADJECTIVES = {"a", "ad", "an", "b", "z"}
_QUANTITY_POS = {"mq", "q"}
_QUANTITY = re.compile(
    r"(?:[〇零一二兩三四五六七八九十百千萬幾數0-9]+|[這那每各某該])"
    r"[個位套種件項份本張家間條篇組首部門名隻只幅雙批座台臺]"
)
_ADVERSATIVES = {"但", "但是", "可是", "不過", "然而", "而是"}
_NEW_CLAUSE = _ADVERSATIVES | {
    "因此", "所以", "於是", "然後", "接著", "後來",
    "我", "你", "妳", "他", "她", "它", "我們", "你們", "你倆", "他們", "她們", "它們",
}
_DIRECT_COMPOUNDS = {"白", "黑", "紅", "木頭", "都市"}
_INCOMPLETE_RESULT = {
    "沒", "沒有", "還沒", "沒能", "未", "還未", "尚未", "從未", "未曾", "未能", "不曾", "不", "不能", "無法",
    "會", "將", "即將", "要", "能", "能夠", "可", "可以", "得", "能否", "能不能", "是否", "務必",
}
_CONDITIONS = {"若", "倘若", "假如", "如果", "只要"}
_PROJECTED_RESULT = _CONDITIONS | {
    "希望", "預計", "預期", "預定", "預備", "打算", "有望", "期待",
    "明天", "明日", "後天", "下週", "下月", "明年", "將來",
}


def _clauses(tokens: Sequence[Token], context: SentenceContext) -> Iterator[Sequence[Token]]:
    # 等長遮罩切斷比對。回傳的片段仍可直接按句內座標對應原文。
    words = [token for token in tokens if not token.surface.isspace()]
    starts = [token.start_char for token in words]
    for clause_start, clause_end in context.clause_spans:
        for run in _VISIBLE_RUN.finditer(context.text, clause_start, clause_end):
            start = bisect_left(starts, run.start())
            end = bisect_left(starts, run.end(), lo=start)
            members = [token for token in words[start:end] if token.end_char <= run.end()]
            if members:
                yield members


def _issue(
    text: str, rule: str, first: Token, last: Token, pattern: str, instruction: str,
) -> Issue:
    return {
        "layer": "L2",
        "rule_id": rule,
        "priority": 2,
        "span": text[first.start_char:last.end_char],
        "char_idx": first.start_char,
        "pos_pattern": pattern,
        "theoretical_basis": _BASIS[rule],
        "instruction": instruction,
    }


def _attr_at(tokens: Sequence[Token], index: int) -> bool:
    return (
        index < len(tokens) and tokens[index].true_de_role == DE_ATTR
        and not tokens[index].is_frozen
    )


def _adjective(token: Token) -> bool:
    # jieba 將案例中的「參差」與「陌生」標成 n。
    return token.pos in _ADJECTIVES or token.surface in {"參差", "陌生"}


def _noun_bounds(tokens: Sequence[Token], start: int) -> tuple[int, int] | None:
    head = start
    while head < len(tokens) and _adjective(tokens[head]) and not tokens[head].is_frozen:
        head += 1
    end = head
    while end < len(tokens) and tokens[end].pos.startswith("n") and not _adjective(tokens[end]):
        end += 1
    return (head, end) if end > head else None


def _left_anchor(tokens: Sequence[Token]) -> int | None:
    """回傳左錨之後的第一個位置，優先採用引出同一受詞的數量詞。"""
    verb_end = None
    for index, token in enumerate(tokens):
        if token.is_frozen:
            continue
        if _QUANTITY.fullmatch(token.surface) or token.pos in _QUANTITY_POS:
            return index + 1
        if token.pos in {"m", "r"} and index + 1 < len(tokens):
            following = tokens[index + 1]
            if following.pos == "q" and not following.is_frozen:
                return index + 2
        if verb_end is not None:
            if token.surface in {"了", "著", "過"}:
                continue
            break
        if token.pos in _VERBS:
            verb_end = index + 1
    return verb_end


def _open_modifier(tokens: Sequence[Token], start: int) -> bool:
    if start == len(tokens):
        return False
    first = tokens[start]
    if first.pos.startswith("n") and not _adjective(first):
        # 已有名詞的受詞通常已完結。「是一個高個子，……的人」仍可延續描述。
        return _noun_bounds(tokens, start) == (start, len(tokens)) and any(
            token.surface == "是" for token in tokens[:start]
        )
    return any(token.pos in _VERBS or _adjective(token) for token in tokens[start:])


def _short_parallel(text: str) -> bool:
    sections = _COMMA.split(text)
    return len(sections) > 1 and all(0 < han_length(section) <= 4 for section in sections)


def _comma_between(text: str, left_end: int, right_start: int) -> bool:
    return text[left_end:right_start].strip() in {"，", ","}


def _left_branches(
    clauses: Sequence[Sequence[Token]], text: str, limit: int,
) -> Iterator[Issue]:
    prefix: list[Token] = []
    previous_end = 0
    for clause in clauses:
        local_start = _left_anchor(clause)
        starts_own_phrase = local_start is not None and (
            _QUANTITY.fullmatch(clause[local_start - 1].surface)
            or clause[local_start - 1].pos in _QUANTITY_POS
        )
        if (
            not _comma_between(text, previous_end, clause[0].start_char)
            or clause[0].surface in _NEW_CLAUSE or clause[0].pos == "nr" or starts_own_phrase
        ):
            prefix = []
        previous_end = clause[-1].end_char

        boundary = len(prefix)
        start = 0 if prefix else local_start
        prefix.extend(clause)
        tokens = prefix
        has_noun_head = False
        issue = None
        for index in range(boundary, len(tokens)):
            if not _attr_at(tokens, index):
                continue
            noun = _noun_bounds(tokens, index + 1)
            if noun is None:
                continue
            has_noun_head = True
            head, end = noun
            if start is None or start >= index:
                continue
            modifier = tokens[start:head]
            length = sum(
                han_length(token.surface.replace("的", "") if token.is_frozen else token.surface)
                for token in modifier
            )
            if length <= limit or not any(
                token.pos in _VERBS and not token.is_frozen for token in tokens[start:index]
            ):
                continue
            if boundary and _short_parallel(text[tokens[start].start_char:tokens[index].start_char]):
                continue
            issue = _issue(
                text, _LEFT_BRANCH, tokens[start], tokens[end - 1],
                "(v/vn 或數量詞) + 長前飾 + DE_ATTR + n",
                "先交代核心名詞及其短修飾語，再以逗號把長修飾移到後面補充。",
            )
        if issue is not None:
            yield issue
        if has_noun_head or start is None or not (boundary or _open_modifier(tokens, start)):
            prefix = []
        elif start:
            prefix = tokens[start:]


def _specific_de_chain(text: str, tokens: Sequence[Token], index: int) -> tuple[Issue, int] | None:
    first = tokens[index]
    if first.is_frozen or not _attr_at(tokens, index + 1) or index + 2 >= len(tokens):
        return None
    after_marker = tokens[index + 2]
    first_noun = _noun_bounds(tokens, index + 2)

    if _adjective(first) and _adjective(after_marker) and _attr_at(tokens, index + 3):
        head = _noun_bounds(tokens, index + 4)
        if head is not None:
            end = head[1]
            return _issue(
                text, _DE_CHAIN, first, tokens[end - 1], "a + DE_ATTR + a + DE_ATTR + n",
                "用「而」連接並列形容詞，保留末尾連接核心名詞的助詞。",
            ), end

    if _adjective(first) and first_noun is not None:
        first_head, first_end = first_noun
        if first_head == index + 2 and _attr_at(tokens, first_end):
            second_adjective = first_end + 1
            if (
                second_adjective < len(tokens) and _adjective(tokens[second_adjective])
                and _attr_at(tokens, second_adjective + 1)
            ):
                second_noun = _noun_bounds(tokens, second_adjective + 2)
                if second_noun is not None:
                    end = second_noun[1]
                    return _issue(
                        text, _DE_CHAIN, first, tokens[end - 1],
                        "a + DE_ATTR + n + DE_ATTR + a + DE_ATTR + n",
                        "補回名詞之間隱含的動詞，例如楊柳「投下」倩影。",
                    ), end

    white_duck = first.surface == "白色" and after_marker.surface == "鴨"
    if first_noun is not None and first_noun[0] == index + 2 and (
        first.surface in _DIRECT_COMPOUNDS or white_duck
    ):
        end = first_noun[1]
        instruction = "刪去中間的助詞，直接連接修飾語與核心名詞。"
        if white_duck:
            instruction = "將「白色的鴨」簡化為「白鴨」。"
        issue = _issue(text, _DE_CHAIN, first, tokens[end - 1], "修飾詞 + DE_ATTR + n", instruction)
        if white_duck:
            issue["_replaceable_token_starts"] = (first.start_char,)
        return issue, end
    return None


def _de_chains(clause: Sequence[Token], text: str) -> Iterator[Issue]:
    index = 0
    found_specific = False
    while index < len(clause):
        match = _specific_de_chain(text, clause, index)
        if match is None:
            index += 1
        else:
            issue, index = match
            found_specific = True
            yield issue
    if not found_specific and sum(_attr_at(clause, index) for index in range(len(clause))) >= 3:
        yield _issue(
            text, _DE_CHAIN, clause[0], clause[-1], "DE_ATTR ≥ 3",
            "釐清各修飾語的關係，把反覆的定語助詞改為並列或用短句交代動作。",
        )


def _result_is_incomplete(clause: Sequence[Token], end: int, conditional: bool) -> bool:
    prefix = clause[:end]
    if any(token.surface in _PROJECTED_RESULT for token in prefix):
        return True
    for token in reversed(prefix):
        if token.surface in _INCOMPLETE_RESULT:
            return True
        if token.pos not in {"d", "ad", "t"}:
            break
    return conditional and not any(token.surface in {"已", "已經", "早已"} for token in prefix)


def _adverbials(clause: Sequence[Token], text: str, conditional: bool) -> Iterator[Issue]:
    for index in range(1, len(clause) - 1):
        marker = clause[index]
        left, right = clause[index - 1], clause[index + 1]
        if marker.true_de_role != DE_ADV or marker.is_frozen or left.is_frozen:
            continue
        if left.surface in RESULT_ADVERBS and right.surface in ACHIEVEMENT_VERBS:
            if not _result_is_incomplete(clause, index - 1, conditional):
                issue = _issue(
                    text, _ADVERB_DI, left, right, "(成功/順利) + DE_ADV + 達成動詞",
                    f"動詞已表達達成結果。若「{left.surface}」只重述結果，可省去「{left.surface}{marker.surface}」。",
                )
                issue["_replaceable_token_starts"] = (left.start_char,)
                yield issue
            continue
        start = long_adverbial_start(clause, index)
        verb = adverbial_verb_index(clause, index) if start is not None else None
        if start is not None and verb is not None:
            yield _issue(
                text, _ADVERB_DI, clause[start], clause[verb], "成語或長片語 + DE_ADV + v/vn",
                f"把「{marker.surface}」改成逗號，以獨立短句展開動作。",
            )


def scan(tokens: Sequence[Token], sentence_ctx: SentenceContext, profile: RuleProfile) -> list[Issue]:
    """掃描整句，輸出可依原文定位的 L2 診斷。"""
    clauses = list(_clauses(tokens, sentence_ctx))
    text = sentence_ctx.text
    issues = list(_left_branches(clauses, text, profile["max_pre_modifier_len"]))
    previous = None
    for clause in clauses:
        issues.extend(_de_chains(clause, text))
        conditional = (
            previous is not None and previous[0].surface in _CONDITIONS
            and _comma_between(text, previous[-1].end_char, clause[0].start_char)
            and clause[0].surface not in _ADVERSATIVES
        )
        issues.extend(_adverbials(clause, text, conditional))
        previous = clause
    return sorted(issues, key=lambda issue: issue["char_idx"])
