"""第四層規則：篇章呼吸與音律節奏（規格 §2.4、§5.2）。"""

from __future__ import annotations

import re
from bisect import bisect_left
from functools import lru_cache
from typing import Iterator, Sequence

from .. import load_default_lexicons
from ..l0_normalizer import DE_ATTR, han_length
from ..tokenizer_adapter import Token
from . import Issue, RuleProfile, SentenceContext


_BREATH = "L4_CLAUSE_BREATH_OVERLOAD"
_PRONOUNS = "L4_REDUNDANT_PRONOUNS"
_BLOAT = "L4_EXISTENTIAL_COPULA_BLOAT"
_ENDING = "L4_WEAK_ENDING_VERBOSE_IDIOM"
_COPULA_DISABLED = "L4_COPULA_SHI_DE"

_BASIS = {
    _BREATH: "中文竹節句以短分句推進，宜在新動作或轉折處換氣。",
    _PRONOUNS: "中文的話題鏈可用零形回指延續已交代的主語或領屬關係。",
    _BLOAT: "中文可以直接陳述問題、事件或性質，避免重疊使用存在或繫詞結構。",
    _ENDING: "雙音節與四字格能收束語氣，段尾也可用具體動詞直接落在重點。",
}
_CONNECTORS = {
    "接著", "然後", "隨後", "繼而", "進而", "於是", "因此", "所以",
    "然而", "但是", "可是", "不過", "反而", "同時", "此外",
}
_LINK_POS = {"c", "d", "t", "v"}
_VERB_POS = {"v", "vd", "vi"}
_ACTION_JOINERS = {"並", "並且", "且", "而", "再"}
# Jieba 也會用 d 標這些動詞。只有後面接名詞賓語時才補認為動作。
_CONTEXTUAL_ACTIONS = {"同步", "更新"}
_OBJECT_MODIFIERS = {"a", "an", "b", "f", "m", "mq", "q", "r"}
_AUXILIARIES = {
    "是", "有", "能", "可", "可以", "會", "要", "須", "必須", "應", "應該",
    "需要", "得", "想", "打算", "讓", "使", "使得", "給", "沒", "沒有",
}
_BOUND_MODIFIERS = {"的", "地", "得", "著", "把", "將", "被", "幫", "向", "對", "在", "到", "以", "從", "為", "為了"}
_TIME_MODIFIERS = {"原本", "原先", "先前", "當時"}
_TIME_FRAME_ENDS = {"後", "以後", "之後"}
_NOUN_TAILS = {"點", "站", "紀錄", "記錄", "時間", "報告", "流程", "方式"}

_REPEATED = {"他", "他的", "它", "它的", "我們", "我們的"}
_SPEECH_ROLES = {"我", "我們", "你", "妳", "您", "你們", "妳們"}
_SUBJECT_PRONOUNS = _SPEECH_ROLES | {"他", "她", "它", "牠", "他們", "她們", "它們", "牠們"}
_CAUSATIVE_VERBS = {"讓", "使", "使得", "令", "叫"}
_PRONOUN_PATTERN = re.compile(
    "|".join(sorted(_REPEATED | _SUBJECT_PRONOUNS, key=lambda term: (-len(term), term)))
)
_TOPIC_INTROS = _CONNECTORS | {"且", "又", "而", "由於", "因為", "雖然", "若", "如果", "使得"}
_OPENERS = "「『（《〈【“‘(["

_EXISTENTIAL_HEADS = {"有", "常有", "尚有", "已有", "還有", "確有"}
_QUANTIFIER_POS = {"m", "mq", "q"}
_EXISTENTIAL = re.compile(r"有(?P<core>[^，。！？；：、,.!?;:\0]+?)(?P<verb>存在|發生|出現)")
_BECAUSE = re.compile(r"基於(?:這個|這樣|上述)的?(?:原因|理由)")
_FINAL_PERIOD = r"(?=\s*。[」』”’）》】）\]]*\s*$)"
_COPULA = re.compile(r"是(?P<quality>[^，。！？；：\0]+?)的" + _FINAL_PERIOD)
_DEGREE = {"很", "非常", "相當"}
_ADJECTIVE_POS = {"a", "an", "ad", "z"}
# Jieba 對這些可直接作形容詞謂語的詞常給動詞或名詞標籤。
_QUALITIES = {"安全", "可靠", "清楚", "合理", "明確", "可行", "必要", "正確", "好用"}
_CONTRAST_AT_COPULA = re.compile(r"(?:不|非|而|卻|倒|才|反而|其實|並非|相較之下|相比之下)\s*$")
_CONTRAST_START = re.compile(r"^\s*[「『（“]? *(?:但|但是|卻|倒是|反而|相較之下|相比之下)")

_VERBOSE_IDIOM = re.compile(
    r"(?P<unclear>不是一句話就能(?:夠)?說(?:得)?清楚的)|總的來說|在很大程度上"
)
_WEAK_ENDING = re.compile(
    r"是(?:我們)?(?P<modal>需要|必須|值得)去?(?P<action>注意|思考|關注)的"
    r"(?:(?:一個)?(?:地方|問題|事情)|一件事情)" + _FINAL_PERIOD
)


@lru_cache(maxsize=1)
def _idiom_map() -> dict[str, list[str]]:
    return {
        entry["term"]: entry["replacements"]
        for entry in load_default_lexicons()["idiom_map"]
    }


def _issue(
    context: SentenceContext,
    tokens: Sequence[Token],
    rule: str,
    span: tuple[int, int],
    pattern: str,
    instruction: str,
    *,
    edits: Sequence[tuple[int, int]] = (),
) -> Issue | None:
    start, end = span
    replaceable = []
    frozen = []
    for token in tokens:
        if end <= token.start_char:
            break
        if token.end_char <= start:
            continue
        if token.is_frozen:
            if any(token.start_char < stop and begin < token.end_char for begin, stop in edits):
                return None
            frozen.append(token.surface)
        elif any(begin <= token.start_char and token.end_char <= stop for begin, stop in edits):
            replaceable.append(token.start_char)

    if frozen:
        words = "、".join(f"「{word}」" for word in dict.fromkeys(frozen))
        instruction += f"保留凍結詞{words}原樣。"
    original = context.original_text if context.original_text is not None else context.text
    issue: Issue = {
        "layer": "L4",
        "rule_id": rule,
        "priority": 2,
        "span": original[start:end],
        "char_idx": start,
        "pos_pattern": pattern,
        "theoretical_basis": _BASIS[rule],
        "instruction": instruction,
    }
    if replaceable:
        issue["_replaceable_token_starts"] = tuple(replaceable)
    return issue


def _has_following_object(tokens: Sequence[Token], start: int) -> bool:
    for index in range(start, len(tokens)):
        token = tokens[index]
        if token.pos.startswith("n") or token.pos == "eng":
            return True
        if token.pos not in _OBJECT_MODIFIERS:
            return False
    return False


def _time_frame_breakpoint(tokens: Sequence[Token]) -> Token | None:
    frame_start = next(
        (i for i, token in enumerate(tokens) if token.surface == "在" and token.pos == "p"), None
    )
    if frame_start is None or any(
        token.pos in _VERB_POS | {"vn"} or token.surface in {"把", "被"} for token in tokens[:frame_start]
    ):
        return None

    has_action = False
    for index in range(frame_start + 1, len(tokens) - 1):
        token = tokens[index]
        if token.pos in _VERB_POS and token.surface not in _AUXILIARIES:
            has_action = True
        if not has_action or token.surface not in _TIME_FRAME_ENDS or token.pos not in {"f", "t"}:
            continue

        # 「在部署完成後會自動檢查」可在「會」前分節，保留下一個動作的修飾語。
        # 若接數量詞（如「後三天」）或定語，還不能在這裡斷開。
        action = next((
            i for i in range(index + 1, len(tokens))
            if tokens[i].pos not in {"d", "ad"}
            and tokens[i].surface not in _AUXILIARIES | {"自動"}
        ), None)
        if action is not None and tokens[action].pos in _VERB_POS | {"vn"} and (
            action + 1 == len(tokens) or tokens[action + 1].surface != "的"
        ):
            return tokens[index + 1]
        return None
    return None


def _breakpoint(tokens: Sequence[Token]) -> Token | None:
    tokens = tuple(token for token in tokens if not token.surface.isspace())
    # 明確承接詞優先，避免把前段的動詞型名詞或修飾語當作新動作。
    for previous, token in zip(tokens, tokens[1:-1]):
        if (
            token.surface in _CONNECTORS and token.pos in _LINK_POS
            and not token.is_frozen and previous.surface not in _BOUND_MODIFIERS
        ):
            return token

    time_breakpoint = _time_frame_breakpoint(tokens)
    if time_breakpoint is not None:
        return time_breakpoint

    verbs = [
        index for index, token in enumerate(tokens)
        if not token.is_frozen and token.surface not in _AUXILIARIES
        and (index + 1 == len(tokens) or tokens[index + 1].surface != "的")
        and (
            token.pos in _VERB_POS
            or (
                token.pos == "d" and token.surface in _CONTEXTUAL_ACTIONS
                and _has_following_object(tokens, index + 1)
            )
        )
    ]
    for index in verbs[1:]:
        previous, token = tokens[index - 1], tokens[index]
        following = tokens[index + 1] if index + 1 < len(tokens) else None
        if previous.end_char == token.start_char and previous.pos.endswith("g"):
            continue
        if following is not None and token.end_char == following.start_char and following.surface in _NOUN_TAILS:
            continue  # 例如「安置點」和「完工紀錄」中的動詞型修飾語。
        if previous.surface in _ACTION_JOINERS:
            return None if previous.is_frozen else previous
        if (
            previous.surface in _BOUND_MODIFIERS | _AUXILIARIES | _TIME_MODIFIERS
            or previous.pos.startswith(("r", "d", "p", "t"))
            or previous.pos in _VERB_POS | {"b", "m", "mq", "q"}
        ):
            return None
        return token
    return None


def _breath_issue(
    context: SentenceContext,
    tokens: Sequence[Token],
    clause: Sequence[Token],
    span: tuple[int, int],
    limit: int,
) -> Issue | None:
    start, end = span
    text = context.text[start:end]
    length = han_length(text)
    if length <= limit:
        return None

    start += len(text) - len(text.lstrip())
    end -= len(text) - len(text.rstrip())
    breakpoint = _breakpoint(clause)
    if breakpoint is None:
        instruction = "按語意另找停頓處，將過長分句拆成幾節，每節以 7～15 字為參考。保留原有的修飾關係。"
    else:
        instruction = f"可在「{breakpoint.surface}」前分節，讓每節接近 7～15 字。"
    issue = _issue(
        context, tokens, _BREATH, (start, end), f"漢字數 {length} > {limit}", instruction
    )
    if issue is not None and breakpoint is not None:
        issue["suggested_breakpoint"] = breakpoint.start_char
    return issue


def _explicit_subject(text: str, clause: Sequence[Token]) -> str | None:
    """只採用謂語前明確的主語。帶代詞領屬語的名詞片語可能共用話題。"""
    start = 0
    while start < len(clause):
        token = clause[start]
        if token.surface not in _TOPIC_INTROS and token.pos != "t" and token.surface not in _OPENERS:
            break
        start += 1
    if start == len(clause):
        return None
    first = clause[start]
    if first.surface in _SUBJECT_PRONOUNS:
        return None if text.startswith(("的", "自己的"), first.end_char) else first.surface

    nouns = []
    introduces_another = text.startswith(("另", "其他", "別的"), first.start_char)
    for token in clause[start:]:
        if token.pos.startswith("n") or token.pos == "eng":
            nouns.append(token.surface)
        elif token.pos.startswith(("v", "a", "d", "p")) and nouns:
            return ("另" if introduces_another else "") + "".join(nouns)
        elif token.pos in {"a", "an", "b", "m", "q", "r"} or token.true_de_role == DE_ATTR:
            continue
        else:
            break
    return None


def _pronoun_issues(
    context: SentenceContext,
    clauses: Sequence[tuple[tuple[int, int], Sequence[Token]]],
) -> Iterator[Issue | None]:
    topic = None
    previous_head = None
    seen: set[str] = set()
    for (start, end), tokens in clauses:
        subject = _explicit_subject(context.text, tokens)
        # 「王明，……他」可能延續同一人物。比較新實體主語時保留這個話題。
        if subject is not None and (subject not in _SUBJECT_PRONOUNS or subject in _SPEECH_ROLES):
            if topic is not None and topic != subject:
                seen.clear()
                previous_head = None
            topic = subject

        by_start = {token.start_char: token for token in tokens}
        words = [token for token in tokens if not token.surface.isspace()]
        causative_targets = {
            word.start_char for verb, word in zip(words, words[1:]) if verb.surface in _CAUSATIVE_VERBS
        }
        head = next((token for token in tokens if token.surface not in _OPENERS), None)
        next_head = None
        for match in _PRONOUN_PATTERN.finditer(context.text, start, end):
            term = match[0]
            token = by_start.get(match.start())
            if token is None or token.surface not in {term, term.removesuffix("的")}:
                continue
            if context.text.startswith("們", match.end()):
                continue
            leading = (
                token is head and term in _SUBJECT_PRONOUNS
                and not context.text.startswith(("的", "自己的"), match.end())
            )
            if leading:
                next_head = term

            span = match.span()
            if term == "它們":
                if context.text.startswith("的", match.end()):
                    span = (match.start(), match.end() + 1)
                pronoun = context.text[span[0]:span[1]]
                instruction = f"話題已經清楚時可省略「{pronoun}」，需要交代指涉時保留或寫明事物名稱。"
            elif term in seen or (leading and term == previous_head):
                if term in _SUBJECT_PRONOUNS and match.start() in causative_targets:
                    continue  # 保留「讓他停下」中動作所指的對象。
                instruction = f"先確認兩處「{term}」的指涉相同，省略後仍清楚時可保留前一處、省略此處。"
            else:
                if term in _REPEATED:
                    seen.add(term)
                continue
            yield _issue(
                context, tokens, _PRONOUNS, span, f"r({term})",
                instruction, edits=(span,),
            )
        previous_head = next_head


def _existential_issues(
    context: SentenceContext,
    clause: Sequence[Token],
    end: int,
) -> Iterator[Issue | None]:
    by_start = {token.start_char: token for token in clause}
    for token in clause:
        if token.surface not in _EXISTENTIAL_HEADS:
            continue
        # 「常有」「尚有」等可能合為一個詞。診斷從「有」開始，保留前置副詞。
        start = token.end_char - 1
        match = _EXISTENTIAL.match(context.text, start, end)
        if match is None or match["core"].lstrip().startswith("的"):
            continue
        verb = by_start.get(match.start("verb"))
        if verb is None or verb.surface != match["verb"]:
            continue
        core = [
            word for word in clause
            if match.start("core") <= word.start_char and word.end_char <= match.end("core")
        ]
        last_modifier = max(
            (index for index, word in enumerate(core) if word.true_de_role == DE_ATTR), default=-1
        )
        head = core[last_modifier + 1:]
        if not head:
            continue
        noun_head = (
            (head[-1].pos.startswith("n") or head[-1].pos in {"vn", "an", "eng"})
            and not any(word.pos in _VERB_POS and not word.is_frozen for word in head)
        )
        # 數量詞後單一動詞可作名詞用，例如「好多鼓勵」。
        counted_event = (
            len(head) > 1 and head[-1].pos in _VERB_POS
            and all(word.pos in _QUANTIFIER_POS for word in head[:-1])
            and context.text[match.end():end].strip() in {"", "了", "過"}
        )
        if not (noun_head or counted_event):
            continue

        qualifier = context.text[token.start_char:start]
        noun = match["core"].strip()
        edits = [(token.start_char, token.end_char)]
        if verb.surface == "存在":
            if not qualifier and noun.startswith("很多") and not context.text[match.end():end].strip():
                suggestion = f"可直接寫成「{noun[2:]}很多」來陳述數量。"
                edits.append(match.span("verb"))
            else:
                suggestion = f"可省去「有」，直接交代「{noun}」的存在或狀態。"
        else:
            suggestion = f"可省去「有」，調整「{verb.surface}」與「{noun}」的語序，交代事件。"
        if qualifier:
            suggestion += f"保留「{qualifier}」表達的時間、頻率或語氣。"
        yield _issue(context, clause, _BLOAT, match.span(), "有 + NP + 存在／發生／出現", suggestion, edits=edits)


def _copula_issue(
    context: SentenceContext,
    tokens: Sequence[Token],
) -> Issue | None:
    match = _COPULA.search(context.text)
    if match is None or not any(
        token.start_char == match.start() and token.surface == "是" for token in tokens
    ):
        return None
    if _CONTRAST_AT_COPULA.search(context.text[:match.start()]):
        return None
    clause_start = next(start for start, end in context.clause_spans if start <= match.start() < end)
    if _CONTRAST_START.match(context.text[clause_start:match.start()]):
        return None
    quality = [
        token for token in tokens
        if match.start("quality") <= token.start_char and token.end_char <= match.end("quality")
    ]
    if len(quality) == 2 and quality[0].surface in _DEGREE:
        quality = quality[1:]
    if len(quality) != 1 or (
        quality[0].pos not in _ADJECTIVE_POS and quality[0].surface not in _QUALITIES
    ):
        return None
    return _issue(
        context, tokens, _BLOAT, match.span(), "是 + (程度副詞) + Adj + 的",
        f"省去句框「是……的」，讓「{match['quality'].strip()}」直接作謂語。",
        edits=((match.start(), match.start("quality")), (match.end("quality"), match.end())),
    )


def _idiom_issues(
    context: SentenceContext, tokens: Sequence[Token], aggressiveness: str,
) -> Iterator[Issue | None]:
    for match in _VERBOSE_IDIOM.finditer(context.text):
        canonical = "不是一句話就能夠說得清楚的" if match["unclear"] else match[0]
        replacements = _idiom_map()[canonical]
        if canonical == "在很大程度上":
            main_factor, magnitude = replacements
            instruction = f"表主要因素時可用「{main_factor}」，描述變化幅度時可用「{magnitude}」。"
        elif aggressiveness == "low":
            instruction = f"用較平實的「{replacements[-1]}」精簡套語。"
        elif aggressiveness == "medium":
            options = "或".join(f"「{word}」" for word in replacements)
            instruction = f"依語氣改用{options}，縮短套語。"
        else:
            instruction = f"用「{replacements[0]}」精簡套語。"
        yield _issue(
            context, tokens, _ENDING, match.span(), "冗長套語", instruction, edits=(match.span(),),
        )


def _weak_ending_issue(context: SentenceContext, tokens: Sequence[Token]) -> Issue | None:
    match = _WEAK_ENDING.search(context.text)
    if match is None:
        return None
    action = match["action"]
    modal = match["modal"]
    if modal == "需要":
        edits = ((match.start(), match.start("action")), (match.end("action"), match.end()))
        modal = "須"
    else:
        edits = (
            (match.start(), match.start("modal")), (match.end("modal"), match.start("action")),
            (match.end("action"), match.end()),
        )
    return _issue(
        context, tokens, _ENDING, match.span(), "是 + 情態詞 + 動詞 + 的 + 段尾空殼",
        f"保留段尾的動作與語氣，將這段收為「{modal}{action}」。",
        edits=edits,
    )


def scan(tokens: Sequence[Token], sentence_ctx: SentenceContext, profile: RuleProfile) -> list[Issue]:
    """使用 Scanner 提供的整句、分句、白名單與段末座標。"""
    starts = tuple(token.start_char for token in tokens)
    clauses = []
    for start, end in sentence_ctx.clause_spans:
        clause = tuple(
            token for token in tokens[bisect_left(starts, start):bisect_left(starts, end)]
            if token.end_char <= end
        )
        clauses.append(((start, end), clause))

    issues: list[Issue | None] = []
    for span, clause in clauses:
        issues.append(_breath_issue(sentence_ctx, tokens, clause, span, profile["max_clause_len"]))
        issues.extend(_existential_issues(sentence_ctx, clause, span[1]))

    issues.extend(_pronoun_issues(sentence_ctx, clauses))
    for match in _BECAUSE.finditer(sentence_ctx.text):
        therefore, to_that_end = _idiom_map()["基於這個原因"]
        issues.append(_issue(
            sentence_ctx, tokens, _BLOAT, match.span(), "基於 + 指示語 + 原因／理由",
            f"說明結果時用「{therefore}」，引出相應行動時可用「{to_that_end}」。",
            edits=(match.span(),),
        ))
    if _COPULA_DISABLED not in profile["disabled_rules"]:
        issues.append(_copula_issue(sentence_ctx, tokens))

    issues.extend(_idiom_issues(sentence_ctx, tokens, profile["idiom_replacement_aggressiveness"]))
    if sentence_ctx.is_paragraph_end:
        issues.append(_weak_ending_issue(sentence_ctx, tokens))
    return sorted((issue for issue in issues if issue is not None), key=lambda issue: issue["char_idx"])
