"""第一層規則：詞性與語態重心（化靜為動、化虛為實）。

規格 zh_polish_skill_spec_v2.md §2.1、§5.2（TICKET-007）。
"""

from __future__ import annotations

import re
from bisect import bisect_left
from dataclasses import dataclass, replace
from functools import lru_cache
from typing import Iterator, Sequence

from .. import load_default_lexicons
from ..l0_normalizer import DE_ADV, DE_ATTR
from ..tokenizer_adapter import ENGLISH_ACTION_AFTER_VERB, Token
from . import Issue, RuleProfile, SentenceContext


_WEAK = "L1_WEAK_VERB_NOMINALIZATION"
_EVENT = "L1_EVENT_NOMINALIZATION"
_JARGON = "L1_PSEUDO_JARGON"
_PLURAL = "L1_REDUNDANT_PLURAL_ZHIYI"
_INANIMATE = "L1_INANIMATE_SUBJECT"
_PASSIVE = "L1_PASSIVE_BEI"
_BASIS = {
    _WEAK: "弱動詞把動作核心化為抽象名詞。中文可以直接讓動作詞作謂語。",
    _EVENT: "中文可直接用主謂短句或動賓短句作主詞或受詞，省去把事件包成名詞的「的」。",
    _JARGON: "「具有……性／度」可能把簡單的狀態塞進抽象名詞框架。可用形容詞或動詞作謂語。",
    _PLURAL: "中文的集合名詞本身可表複數。數量和集合界線也可由上下文交代。",
    _INANIMATE: "敘述人的變化時，可讓當事人作主詞，把抽象變化表為原因。",
    _PASSIVE: "中文可用主動句、受事作主詞的句子，或「獲、遭、受」等詞表達施受關係。",
}

# Scanner 的分句已排除全形標點。另以遮罩和 ASCII 標點限制句型配對。
_VISIBLE_RUN = re.compile(r"[^\0,.!?;:]+")
_MODIFIER_POS = {"a", "ad", "an", "b", "d", "m", "mq", "q", "z"}
_ASPECT = {"了", "過", "著"}
_EXACT_NUMBER = r"[0-9〇零一二兩三四五六七八九十百千萬億兆]+"
_NUMBER = rf"(?:{_EXACT_NUMBER}|[幾數])"
_ENGLISH_TAIL = re.compile(ENGLISH_ACTION_AFTER_VERB)
_DEATH_TOLL = re.compile(rf"\s*(?P<count>{_NUMBER}人)(?P<event>死亡)")
_REPETITIONS = re.compile(rf"{_NUMBER}次")
_WEAK_ACTIONS = {
    "研究", "貢獻", "討論", "分析", "評估", "反應", "試驗", "優化", "處理", "測試", "死亡", "幫助",
    "翻修", "檢討", "驗證", "觀察", "記錄", "肯定", "說明",
}
_WEAK_MODIFIERS = ("深入", "詳細", "仔細", "全面", "進一步", "逐一", "徹底")
_MODIFIED_ACTION = re.compile(
    rf"({'|'.join(_WEAK_MODIFIERS)})({'|'.join(sorted(_WEAK_ACTIONS))})"
)
_PREPOSED = {"對", "針對", "對於", "向", "在"}


def _alternatives(words: Sequence[str]) -> str:
    return "|".join(re.escape(word) for word in sorted(words, key=len, reverse=True))


@dataclass(frozen=True)
class _Lexicons:
    weak: re.Pattern[str]
    jargon: dict[str, tuple[str, ...]]
    jargon_patterns: tuple[tuple[re.Pattern[str], str], ...]
    jargon_terms: re.Pattern[str]
    jargon_score: re.Pattern[str]


@lru_cache(maxsize=1)
def _lexicons() -> _Lexicons:
    data = load_default_lexicons()
    jargon = {
        entry["term"]: tuple(entry.get("replacements", ()))
        for entry in data["pseudo_jargon"] if not entry.get("is_pattern")
    }
    terms = _alternatives(list(jargon))
    return _Lexicons(
        weak=re.compile(_alternatives([entry["term"] for entry in data["weak_verbs"]])),
        jargon=jargon,
        jargon_patterns=tuple(
            (re.compile(entry["term"]), next(iter(entry.get("replacements", ())), ""))
            for entry in data["pseudo_jargon"] if entry.get("is_pattern")
        ),
        jargon_terms=re.compile(terms),
        jargon_score=re.compile(
            rf"(?P<term>{terms})(?P<degree>(?:頗|很|甚|較|相當|非常)?[高大強低小弱])"
        ),
    )


@dataclass(frozen=True)
class _Clause:
    source: str
    start: int
    end: int
    tokens: tuple[Token, ...]
    frozen_tokens: tuple[Token, ...]

    def frozen(self, start: int, end: int) -> bool:
        return any(token.start_char < end and start < token.end_char for token in self.frozen_tokens)


def _clauses(tokens: Sequence[Token], context: SentenceContext) -> Iterator[_Clause]:
    visible_tokens = [token for token in tokens if not token.surface.isspace()]
    starts = [token.start_char for token in visible_tokens]
    for clause_start, clause_end in context.clause_spans:
        for segment in _VISIBLE_RUN.finditer(context.text, clause_start, clause_end):
            start, end = segment.span()
            low = bisect_left(starts, start)
            high = bisect_left(starts, end, lo=low)
            members = tuple(token for token in visible_tokens[low:high] if token.end_char <= end)
            if members:
                frozen = tuple(
                    token for token in visible_tokens[max(0, low - 1):high]
                    if token.is_frozen and token.end_char > start
                )
                yield _Clause(context.text, start, end, members, frozen)


def _issue(
    clause: _Clause,
    rule: str,
    start: int,
    end: int,
    pattern: str,
    instruction: str,
    *,
    replacements: Sequence[tuple[int, int]] = (),
    core_start: int | None = None,
    info: bool = False,
) -> Issue | None:
    if clause.frozen(start if core_start is None else core_start, end):
        return None
    issue: Issue = {
        "layer": "L1",
        "rule_id": rule,
        "priority": 3 if info else 2,
        "span": clause.source[start:end],
        "char_idx": start,
        "pos_pattern": pattern,
        "theoretical_basis": _BASIS[rule],
        "instruction": instruction,
    }
    if info:
        issue["severity"] = "info"
    if replacements:
        issue["_replaceable_token_starts"] = tuple(
            token.start_char for token in clause.tokens if not token.is_frozen
            and any(begin <= token.start_char and token.end_char <= finish
                    for begin, finish in replacements)
        )
    return issue


@dataclass(frozen=True)
class _WeakTarget:
    word: str
    start: int
    end: int
    modifier: str = ""
    modifier_start: int = 0
    # n+vn 複合動作詞（壓力測試）：改寫以「做」取代弱動詞，而非直接作謂語。
    nominal: bool = False


def _weak_target(clause: _Clause, index: int, verb: re.Match[str]) -> _WeakTarget | None:
    tokens = clause.tokens
    end_of_verb = verb.end()
    token = tokens[index]
    if end_of_verb < token.end_char:
        remainder = clause.source[end_of_verb:token.end_char]
        if remainder in _WEAK_ACTIONS:
            return _WeakTarget(remainder, end_of_verb, token.end_char)
        return None

    index += 1
    if index < len(tokens) and tokens[index].surface in _ASPECT:
        index += 1
    if index == len(tokens):
        return None
    first = index
    modifier_start = tokens[first].start_char
    if verb[0] == "造成":
        toll = _DEATH_TOLL.match(clause.source, modifier_start, clause.end)
        if toll:
            return _WeakTarget("死亡", toll.start("event"), toll.end(), toll["count"], modifier_start)

    for index in range(first, len(tokens)):
        token = tokens[index]
        modifier_end = token.start_char
        if index > first and tokens[index - 1].true_de_role in {DE_ATTR, DE_ADV}:
            modifier_end = tokens[index - 1].start_char
        modifier = clause.source[modifier_start:modifier_end].strip()
        compound = _MODIFIED_ACTION.fullmatch(token.surface)
        if compound:
            return _WeakTarget(compound[2], token.start_char + compound.start(2), token.end_char,
                               modifier + compound[1], modifier_start)
        if token.surface in _WEAK_ACTIONS or token.pos == "vn":
            return _WeakTarget(token.surface, token.start_char, token.end_char, modifier, modifier_start)
        # 「壓力／測試」：名詞修飾語與後接動作詞合成複合動作詞。
        if token.pos.startswith("n") and index + 1 < len(tokens):
            following = tokens[index + 1]
            if following.start_char == token.end_char and (
                following.pos == "vn" or following.surface in _WEAK_ACTIONS
            ):
                return _WeakTarget(token.surface + following.surface, token.start_char,
                                   following.end_char, modifier, modifier_start, nominal=True)
        if (token.pos in _MODIFIER_POS or token.surface in _WEAK_MODIFIERS
                or (index > first and token.true_de_role in {DE_ATTR, DE_ADV})):
            continue
        break
    return None


_MERGED_PREPOSITION = re.compile(r"[已將曾先再也都就才並只僅還又便即]對")


def _preposed_phrase(clause: _Clause, index: int, weak: re.Pattern[str]) -> Token | None:
    # 遇到連詞或另一個弱動詞時停止往前延伸。
    for previous in range(index - 1, -1, -1):
        token = clause.tokens[previous]
        if token.pos == "c" or weak.fullmatch(token.surface):
            break
        if token.pos == "p" and token.surface in _PREPOSED:
            if previous < index - 1 and not token.is_frozen:
                return token
            break
        # 「已對錯誤碼章節進行…」：介詞「對」被 Jieba 併入副詞成一個 d 詞。
        if _MERGED_PREPOSITION.fullmatch(token.surface) and not token.is_frozen:
            if previous < index - 1:
                return replace(token, surface="對", pos="p", start_char=token.end_char - 1)
            break
    return None


def _weak_issues(clause: _Clause, lexicons: _Lexicons) -> Iterator[Issue | None]:
    for index, token in enumerate(clause.tokens):
        verb = lexicons.weak.match(clause.source, token.start_char, token.end_char)
        if verb is None or token.is_frozen:
            continue

        english = _ENGLISH_TAIL.match(clause.source, verb.end(), clause.end)
        if english:
            span = clause.source[verb.start():english.end()]
            yield _issue(
                clause, _WEAK, verb.start(), english.end(), "v_weak + 英文動作",
                f"「{span}」的「{verb[0]}」可作語法黏著劑。保留英文原詞，只在需要時微調空格。",
                info=True,
            )
            continue

        target = _weak_target(clause, index, verb)
        if target is None:
            continue
        prefix = _preposed_phrase(clause, index, lexicons.weak)
        start = prefix.start_char if prefix else token.start_char
        replacements = [(verb.start(), verb.end())]
        if verb.end() < token.end_char:
            replacements.append((token.start_char, token.end_char))

        example = target.modifier + target.word
        if target.word == "研究" and target.modifier == "詳細":
            example = "詳加研究"
            replacements.append((target.modifier_start, target.start))
        elif target.word == "貢獻" and target.modifier == "重大":
            example = "貢獻很大"
            replacements.append((target.modifier_start, target.start))
        elif target.word == "反應":
            example = target.word + target.modifier
        elif target.word == "死亡" and _DEATH_TOLL.fullmatch(target.modifier + target.word):
            example = "死了" + target.modifier
            replacements.append((target.start, target.end))
        elif _REPETITIONS.fullmatch(target.modifier):
            example = target.word + target.modifier

        if target.nominal:
            instruction = f"把「{verb[0]}」換成「做」，保留「{example}」的次數與對象，維持原句時態。"
        else:
            instruction = f"刪掉「{verb[0]}」，用「{example}」直接作謂語，保留原句的時態和其餘實詞。"
        if prefix and prefix.surface in {"對", "針對", "對於"}:
            instruction += f"把「{prefix.surface}」所引出的受詞接回動詞，原樣保留受詞中的術語。"
        elif prefix:
            operand = clause.source[prefix.end_char:verb.start()].strip()
            if prefix.surface == "在" and target.word == "試驗" and operand.endswith("身上"):
                subject = operand.removesuffix("身上").removesuffix("的")
                instruction += f"把試驗對象改以「用{subject}」引出，寫作「用{subject}試驗」。"
            else:
                instruction += f"保留「{prefix.surface}」片語表達的對象或情境。"
        yield _issue(
            clause, _WEAK, start, target.end, "[p + NP] + v_weak + [助詞／修飾語] + vn",
            instruction, replacements=replacements, core_start=verb.start(),
        )


_CHANGE_EVENTS = {"減少", "增加", "出現", "改變", "發展", "驅使", "缺乏", "變動", "掉包", "等待"}
_SUBJECT_EVENTS = _CHANGE_EVENTS | {
    "坍方", "來襲", "將至", "到來", "發生", "倒塌", "上升", "下降", "消失", "逾時", "請假", "出貨",
}
_OBJECT_EVENTS = {
    "選購", "推行", "推廣", "設計", "開發", "實施", "維護", "研究", "檢查", "優化",
    "編輯", "整理", "採購", "測試", "分析", "處理", "保護", "評估", "發布", "安裝",
    "繼續",
}
_EVENT_HEADS = _SUBJECT_EVENTS | _OBJECT_EVENTS | {"盤點", "部署"}
_EVENT_MODIFIER_POS = {"a", "ad", "b", "d"}
# 「接連／陸續」可被 Jieba 標為 v，仍是事件修飾語而非事件頭。
# 時間修飾語（夜間盤點）逐詞列入：逾時等事件頭本身可被標 t，不能整類放行。
_EVENT_MODIFIER_WORDS = {
    "接連", "陸續", "漫長", "夜間", "日間", "凌晨", "深夜", "清晨", "上午", "下午", "晚間", "平日", "假日", "週末",
}
_APPLICATION_NOUNS = {"申請", "退款", "退費"}
# 常構成複合名詞的動詞修飾語（客服回應速度、處理流程）。
_NP_MODIFIER_VERBS = {
    "回應", "服務", "管理", "控制", "支援", "存取", "搜尋", "驗證", "同步", "監控",
    "備份", "連線", "處理", "測試", "開發", "維運", "營運", "備援", "推薦", "排班",
}
_GROUP_NOUN = re.compile(r"第?[0-9〇零一二兩三四五六七八九十百]+[組隊批群班]")
_LATIN_HEAD = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:[-/][A-Za-z0-9]+)*")
# 時長名詞被標 d 時，L0 會把「長期的等待」判為 DE_ADV；此處補償為定語。
_NOMINAL_LEADS = {"長期", "短期", "暫時", "永久"}
_CAUSATIVES = {"改變", "迫使", "使得", "讓", "帶給", "決定"}
_PREDICATE_CUES = {
    "正", "正在", "剛", "剛剛", "已", "已經", "尚未", "從未", "曾", "曾經", "仍", "仍在", "將", "將要",
}
_DETERMINERS = ("這", "那", "該", "此", "本")
_HUMAN_PRONOUN = re.compile(r"(?:我|你|妳|您|他|她)(?:們)?|大家|眾人")
_TECH_COMPONENT = re.compile(r"(?:模組|系統|元件|伺服器|服務|引擎|資料庫|佇列|快取|資料表|節點|API)$")


def _noun_head(token: Token) -> bool:
    # 橫貫公路被標為 i，收入則可標為 v；延遲／長期在「的」前亦作名詞中心語。
    return token.pos.startswith("n") or token.pos in {"i", "vn"} or token.surface in {"收入", "延遲", "長期"}


def _has_predicate_cue(tokens: Sequence[Token], index: int) -> bool:
    if index == 0:
        return False
    cue = tokens[index - 1].surface
    return cue in _PREDICATE_CUES or bool(
        tokens[index].pos in {"v", "vn"} and _HUMAN_PRONOUN.fullmatch(cue)
    )


def _noun_phrase_start(tokens: Sequence[Token], index: int) -> int:
    while index > 0:
        previous = tokens[index - 1]
        # 「帳務／組將／核心帳本」：把字句的「將」被 Jieba 併入前詞時，
        # NP 向左止於其前（麻將等名詞除外）。
        if len(previous.surface) > 1 and previous.surface.endswith("將") and previous.surface != "麻將":
            break
        if previous.pos == "r" and previous.surface.startswith(_DETERMINERS):
            return index - 1
        if previous.true_de_role == DE_ATTR and index >= 2:
            possessor = tokens[index - 2]
            if _noun_head(possessor) or _HUMAN_PRONOUN.fullmatch(possessor.surface):
                index -= 2
                continue
        if previous.pos == "vn" and _has_predicate_cue(tokens, index - 1):
            break
        # Jieba 可將「退款／申請」標為兩個 v，或將「通勤」標為 j。
        application = previous.surface in _APPLICATION_NOUNS and tokens[index].surface == "申請"
        if _noun_head(previous) or previous.pos in {"a", "an", "b", "j", "m", "mq", "q"} or application:
            index -= 1
            continue
        # 「客服／回應／速度」：複合名詞內的動詞修飾語仍屬同一 NP；
        # 只認常見複合動詞，避免把「完成資料庫的遷移」的謂語「完成」吞進 span。
        if (previous.pos == "v" and previous.surface in _NP_MODIFIER_VERBS
                and _noun_head(tokens[index])):
            index -= 1
            continue
        # 「本批預購商品」的量詞框架可確認「預購」修飾名詞。
        if (previous.pos == "v" and index >= 3 and tokens[index - 2].pos == "q"
                and tokens[index - 3].surface.startswith(_DETERMINERS)):
            index -= 1
            continue
        break
    return index


@dataclass(frozen=True)
class _Event:
    start: int
    marker: int
    last: int
    verb: str


def _events(tokens: Sequence[Token]) -> Iterator[_Event]:
    for index, marker in enumerate(tokens[1:], start=1):
        left = tokens[index - 1]
        # 「第一組」標 m、「API」標 x，在「的」前仍作 NP 中心語。
        noun_head = (
            _noun_head(left)
            or (left.pos == "m" and _GROUP_NOUN.fullmatch(left.surface))
            or _LATIN_HEAD.fullmatch(left.surface) is not None
        )
        if marker.true_de_role not in {DE_ATTR, DE_ADV} or not (
            noun_head or left.surface in _APPLICATION_NOUNS
        ):
            continue
        if marker.true_de_role == DE_ADV and left.surface not in _NOMINAL_LEADS:
            continue
        if left.pos == "r" or _HUMAN_PRONOUN.fullmatch(left.surface) or _has_predicate_cue(tokens, index - 1):
            continue
        right = index + 1
        while right < len(tokens):
            term = tokens[right]
            if (term.pos in _EVENT_MODIFIER_POS or term.surface in _EVENT_MODIFIER_WORDS) and term.surface != "將":
                right += 1
                continue
            # 「統一出貨」的「統一」修飾後面的動作。
            if (term.surface == "統一" and right + 1 < len(tokens)
                    and tokens[right + 1].pos in {"v", "vn"}):
                right += 1
                continue
            break
        if right == len(tokens):
            continue
        verb = tokens[right].surface
        if verb == "將" and right + 1 < len(tokens) and tokens[right + 1].surface == "至":
            right += 1
            verb = "將至"
        # 「申請」一類的 v 可作處理對象，須有已知動賓句型佐證。
        if not noun_head and verb not in _OBJECT_EVENTS:
            continue
        if verb not in _EVENT_HEADS and tokens[right].pos not in {"v", "vn"}:
            continue
        following = tokens[right + 1:right + 2]
        # 「維護流程／處理進度」的末詞仍是名詞或被 Jieba 標成 d。
        if following and (following[0].pos.startswith("n") or following[0].surface in _ASPECT
                          or following[0].surface == "進度"):
            continue
        yield _Event(_noun_phrase_start(tokens, index - 1), index, right, verb)


def _event_parts(clause: _Clause, event: _Event) -> tuple[int, int, str, str]:
    start = clause.tokens[event.start].start_char
    end = clause.tokens[event.last].end_char
    marker = clause.tokens[event.marker]
    return (start, end, clause.source[start:marker.start_char].strip(),
            clause.source[marker.end_char:end].strip())


def _event_issues(clause: _Clause, events: Sequence[_Event]) -> Iterator[Issue | None]:
    for event in events:
        start, end, noun, action = _event_parts(clause, event)
        marker = clause.tokens[event.marker]
        if event.verb in _OBJECT_EVENTS:
            verb = "保存" if event.verb == "繼續" else event.verb
            predicate = action.removesuffix(event.verb) + verb
            instruction = f"拿掉「{marker.surface}」，把受詞「{noun}」移到動詞之後，寫成「{predicate}{noun}」。"
            replacements = ((end - len(event.verb), end),) if verb != event.verb else ()
        elif event.verb in _SUBJECT_EVENTS:
            instruction = (
                f"拿掉「{marker.surface}」，在原位置寫成短句「{noun}{action}」。"
                f"「{noun}」是這個短句的主詞。"
            )
            replacements = ()
        else:
            instruction = (
                f"拿掉「{marker.surface}」，用「{event.verb}」直接述說事件。"
                f"若「{noun}」在原句是動作主體，可寫成「{noun}{action}」。"
                f"若「{noun}」是受詞，把它接到「{action}」之後，保留原施受關係。"
            )
            replacements = ()
        yield _issue(
            clause, _EVENT, start, end, "NP + DE_ATTR + V/VN", instruction,
            replacements=replacements,
        )


def _human_reference(token: Token) -> bool:
    return bool(
        _HUMAN_PRONOUN.fullmatch(token.surface)
        or token.pos.startswith("nr")
        or (token.pos.startswith("n") and (
            token.surface.endswith(("人", "者", "員", "生", "師", "戶", "眾", "客"))
            or token.surface.endswith("客服")
            or token.surface in {"老闆", "編輯"}
        ))
    )


def _inanimate_issues(
    clause: _Clause, events: Sequence[_Event], profile: RuleProfile
) -> Iterator[Issue | None]:
    tokens = clause.tokens
    for event in events:
        if event.verb not in _CHANGE_EVENTS or event.last + 2 >= len(tokens):
            continue
        start, _, noun, action = _event_parts(clause, event)
        if clause.source[clause.start:start].strip(" \t「『（"):
            continue
        if profile["name"] == "tech" and _TECH_COMPONENT.search(noun):
            continue
        predicate = event.last + 1
        while predicate < len(tokens) and tokens[predicate].pos in {"d", "ad"}:
            predicate += 1
        if predicate == len(tokens) or tokens[predicate].surface not in _CAUSATIVES:
            continue
        patient = predicate + 1
        if patient < len(tokens) and tokens[patient].surface in _ASPECT:
            patient += 1
        # 人稱受詞可能帶定語（獨立書店老闆／門市人員／候車乘客）：向前找
        # 人稱中心語，遇謂語邊界（名詞後接動詞）或虛詞即止，最多六個詞。
        person_head = None
        for offset in range(patient, min(patient + 6, len(tokens))):
            token = tokens[offset]
            if _human_reference(token):
                person_head = offset
                break
            if token.pos in {"c", "p", "y", "o", "e", "ud", "uv"} or token.surface in _ASPECT:
                break
            if token.pos in {"v", "vn"} and offset > patient and tokens[offset - 1].pos.startswith("n"):
                break
        if person_head is None:
            continue
        person = clause.source[tokens[predicate + 1].start_char:tokens[person_head].end_char]
        yield _issue(
            clause, _INANIMATE, start, tokens[-1].end_char, "NP + DE_ATTR + VN + 使動動詞 + 人稱受詞",
            f"改寫這個分句時，以「{person}」作主詞，用「因為{noun}{action}」交代原因，"
            f"再說明「{person}」受到的影響。",
        )


_JARGON_HEAD = re.compile(r"具有|頗具|更具|富於|具備|呈現出")
_JARGON_LITERAL_HEADS = {"具有", "頗具", "更具", "富於"}
_JARGON_GRAY_HEADS = {"具有", "具備", "呈現出", "更具", "頗具"}
# 「更具／頗具」的程度詞彙化在頭詞裡，改寫時要還原成副詞。
_JARGON_HEAD_DEGREE = {"更具": "更", "頗具": "頗"}
_ORDINARY_NOUNS = {"制度", "態度", "程度", "尺度", "角度", "年度", "溫度", "能見度", "高度"}
_DEGREE_PREFIX = "很|非常|相當|較|頗|甚|極|極其|偏"
_DEGREE = re.compile(rf"({_DEGREE_PREFIX})?[高大強低小弱]")
_LOW_DEGREE = re.compile(rf"(?:不(?:太|算|很|夠)?[高大強]|(?:{_DEGREE_PREFIX})?[低小弱])")
_SUFFICIENT_DEGREES = {"足夠", "充足"}
_JARGON_MODIFIER_POS = _MODIFIER_POS - {"m", "mq", "q"}
_LOW_DEGREE_WORDING = {
    "知名度": "名氣不大", "可讀性": "不太好讀", "可看性": "不太好看", "可聽性": "不太動聽",
    "前瞻性": "缺少遠見", "嚴重性": "情況不太嚴重", "必要性": "不太有必要",
}


def _property_word(term: str) -> str:
    return "容易" + term[1:-1] if term.startswith("可") else term[:-1]


def _jargon_rewrite(
    term: str, degree: str, lexicons: _Lexicons, *, technical: bool, head_degree: str = "",
) -> str:
    if _LOW_DEGREE.fullmatch(degree):
        replacement = _LOW_DEGREE_WORDING.get(term, "不太" + _property_word(term))
        if degree.startswith("極"):
            return {"知名度": "名氣極小", "前瞻性": "極缺乏遠見"}.get(
                term, replacement.replace("不太", "極不", 1),
            )
        return replacement
    if degree in _SUFFICIENT_DEGREES:
        return "夠" + _property_word(term)

    qualifier = head_degree or ("很" if degree == "高度" else "")
    if term == "可讀性":
        if qualifier:
            return qualifier + ("易讀" if technical else "好讀")
        return "清晰易讀" if technical else "很好讀"

    options = lexicons.jargon.get(term, ())
    if options:
        # 詞庫的「更有遠見／更耐看」是有比較語境的範例。
        replacement = options[0].removeprefix("更")
    else:
        replacement = {"嚴重性": "情況嚴重", "必要性": "有必要", "力度": "有力"}.get(term, "")
    if not replacement or not qualifier:
        return replacement
    if replacement.startswith("情況"):
        return f"情況{qualifier}{replacement.removeprefix('情況')}"
    return qualifier + replacement.removeprefix("很")


def _property_ends_here(tokens: Sequence[Token], end: int) -> bool:
    following = next((token for token in tokens if token.end_char > end), None)
    return following is None or (
        following.start_char >= end and not _noun_head(following)
    )


@dataclass(frozen=True)
class _JargonTarget:
    term: str
    end: int
    degree: str
    keep_term: bool = False


def _jargon_target(
    clause: _Clause, head: re.Match[str], tail: Sequence[Token], lexicons: _Lexicons
) -> _JargonTarget | None:
    text = clause.source
    if head[0] in _JARGON_LITERAL_HEADS:
        literal = lexicons.jargon_terms.search(text, head.end(), clause.end)
        if literal and _property_ends_here(tail, literal.end()):
            middle = [token for token in tail if token.start_char < literal.start()]
            degree = text[head.end():literal.start()].strip()
            if middle and middle[-1].true_de_role == DE_ATTR:
                degree = text[head.end():middle[-1].start_char].strip()
                if all(token.pos not in {"c", "p", "x"} for token in middle):
                    return _JargonTarget(literal[0], literal.end(), degree)
            if not degree or degree == "高度" or _DEGREE.fullmatch(degree) or _LOW_DEGREE.fullmatch(degree) or (
                middle and all(token.pos in _MODIFIER_POS for token in middle)
            ):
                return _JargonTarget(literal[0], literal.end(), degree)

    if head[0] not in _JARGON_GRAY_HEADS:
        return None
    modifiers = []
    for index, token in enumerate(tail):
        word = token.surface
        if word == "高度" and not modifiers:
            modifiers.append(word)
            continue
        # 「更具／頗具」自帶程度，後接裸名詞也算灰區；其他頭詞仍需修飾語。
        if (modifiers or head[0] in _JARGON_HEAD_DEGREE) and token.pos.startswith("n"):
            # 合併連續的名詞片段，例如「語意／保真度」，保留指標完整詞名。
            last = index
            while last + 1 < len(tail) and not tail[last].surface.endswith(("性", "度")):
                next_token = tail[last + 1]
                if not next_token.pos.startswith("n") or next_token.start_char != tail[last].end_char:
                    break
                last += 1
            end = tail[last].end_char
            term = text[token.start_char:end]
            if (len(term) > 1 and term.endswith(("性", "度")) and term not in _ORDINARY_NOUNS
                    and _property_ends_here(tail, end)):
                return _JargonTarget(term, end, "".join(modifiers), keep_term=last > index)
            break
        # 「計算／複雜度」：動詞性前綴與性／度名詞在原文銜接時，視為複合指標。
        if (modifiers or head[0] in _JARGON_HEAD_DEGREE) and token.pos in {"v", "vn"} and index + 1 < len(tail):
            following = tail[index + 1]
            if (following.pos.startswith("n") and following.start_char == token.end_char
                    and len(following.surface) > 1 and following.surface.endswith(("性", "度"))
                    and following.surface not in _ORDINARY_NOUNS
                    and _property_ends_here(tail, following.end_char)):
                term = text[token.start_char:following.end_char]
                return _JargonTarget(term, following.end_char, "".join(modifiers), keep_term=True)
        # 和預檢同樣辨識「可／觀察／性」，條件是三個分詞在原文銜接。
        if modifiers and word == "可" and index + 2 < len(tail):
            verb, suffix = tail[index + 1:index + 3]
            if (verb.pos in {"v", "vn"} and suffix.surface == "性"
                    and token.end_char == verb.start_char and verb.end_char == suffix.start_char
                    and _property_ends_here(tail, suffix.end_char)):
                return _JargonTarget(text[token.start_char:suffix.end_char], suffix.end_char, "".join(modifiers))
        if token.true_de_role in {DE_ATTR, DE_ADV} and modifiers:
            continue
        if (token.pos not in _JARGON_MODIFIER_POS and word not in _SUFFICIENT_DEGREES
                and not _DEGREE.fullmatch(word) and not _LOW_DEGREE.fullmatch(word)):
            break
        modifiers.append(word)
    return None


def _adjacent_negation_start(tokens: Sequence[Token], index: int) -> int:
    start = tokens[index].start_char
    if index and tokens[index - 1].end_char == start:
        previous = tokens[index - 1]
        if previous.surface == "並不":
            return previous.start_char
        if previous.surface == "不":
            if (index >= 2 and tokens[index - 2].surface == "並"
                    and tokens[index - 2].end_char == previous.start_char):
                return tokens[index - 2].start_char
            return previous.start_char
    return start


def _jargon_issues(
    clause: _Clause, lexicons: _Lexicons, profile: RuleProfile
) -> Iterator[Issue | None]:
    text = clause.source
    tokens = clause.tokens
    token_starts = {token.start_char: index for index, token in enumerate(tokens)}
    technical = profile["name"] == "tech"

    for pattern, replacement in lexicons.jargon_patterns:
        for match in pattern.finditer(text, clause.start, clause.end):
            instruction = f"用直接的謂語表達「{match[0]}」的意思，保留原有程度。"
            if replacement:
                instruction = f"將「{match[0]}」寫成「{replacement}」。"
            yield _issue(
                clause, _JARGON, *match.span(), "偽術語固定句型",
                instruction, replacements=(match.span(),),
            )

    for match in lexicons.jargon_score.finditer(text, clause.start, clause.end):
        index = token_starts.get(match.start())
        if index is None:
            continue
        term = match["term"]
        # 名詞性分數的「的」屬可移除框架的一部分。
        start = match.start()
        if index and tokens[index - 1].true_de_role == DE_ATTR:
            start = tokens[index - 1].start_char
        replacement = _jargon_rewrite(term, match["degree"], lexicons, technical=technical)
        if replacement:
            yield _issue(
                clause, _JARGON, start, match.end(), "[DE_ATTR] + 抽象名詞 + 程度謂語",
                f"將「{text[start:match.end()]}」直接寫成「{replacement}」。",
                replacements=((start, match.end()),),
            )

    for head in _JARGON_HEAD.finditer(text, clause.start, clause.end):
        index = token_starts.get(head.start())
        if index is None:
            continue
        tail = [token for token in tokens[index:] if token.start_char >= head.end()]
        target = _jargon_target(clause, head, tail, lexicons)
        if target is None:
            continue
        word, end, degree = target.term, target.end, target.degree
        start = _adjacent_negation_start(tokens, index)
        negation = text[start:head.start()]
        if target.keep_term or (negation and _LOW_DEGREE.fullmatch(degree)):
            yield _issue(
                clause, _JARGON, start, end, "抽象動詞 + 修飾語 + 性／度名詞",
                f"去掉「{head[0]}」的框架，直接說「{word}{negation}{degree}」，保留指標原詞和程度。",
                replacements=(head.span(),),
            )
            continue
        source = text[start:end]
        # 頭詞自帶程度（更具／頗具）且沒有其他修飾語時，改寫要補回該程度。
        head_degree = _JARGON_HEAD_DEGREE.get(head[0], "") if not degree else ""
        replacement = _jargon_rewrite(word, degree, lexicons, technical=technical, head_degree=head_degree)
        if replacement:
            if negation and replacement.startswith("有"):
                replacement = f"{negation.removesuffix('不')}沒{replacement}"
            else:
                replacement = negation + replacement
            instruction = f"可將「{source}」直接寫成「{replacement}」，保留原句表達的程度。"
        else:
            strength = _DEGREE.fullmatch("很高" if degree == "高度" else degree)
            qualifier = (strength[1] or "很") if strength else head_degree
            instruction = (
                f"去掉「{head[0]}」和「{word[-1]}」的名詞框架。用「{negation}{qualifier}{_property_word(word)}」"
                f"直接表達「{word}」的意思，保留原來的程度與語氣。"
            )
        yield _issue(
            clause, _JARGON, start, end, "抽象動詞 + [修飾語] + 性／度名詞",
            instruction, replacements=((start, end),),
        )


_PLURAL_WORDS = re.compile(r"人們|(?:民眾|聽眾|觀眾|讀者|球員|師生|同胞|顧客|乘客|長者|工作人員)們")
_AS_ONE_OF = re.compile(r"作為(?P<group>.+?)之一")
_ONE_OF = re.compile("之一")
_EXPLICIT_GROUP = re.compile(
    rf"{_EXACT_NUMBER}[ \t\u3000]*"
    r"(?:個(?![ \t\u3000]*(?:月|鐘頭|小時|禮拜|星期))|[大位名種項座條組家部賢寶傑強場本篇首件冊屆])"
)
_COUNTRIES = re.compile(rf"{_EXACT_NUMBER}國(?:其中)?$")
_SUPERLATIVE = re.compile(r"最(?!近|初|後|終)")
_COPULA = re.compile("是|乃")
_FRACTION_END = re.compile(rf"{_NUMBER}分$")


def _plural_issues(clause: _Clause) -> Iterator[Issue | None]:
    text = clause.source
    tokens = {token.start_char: token for token in clause.tokens}
    ends = {token.end_char for token in clause.tokens}
    previous_at = {token.end_char: token for token in clause.tokens}
    for match in _PLURAL_WORDS.finditer(text, clause.start, clause.end):
        if match.start() in tokens and match.end() in ends:
            replacement = match[0].removesuffix("們")
            previous = previous_at.get(match.start())
            if match[0] == "人們" and (previous is None or (
                not _noun_head(previous) and previous.pos not in {"a", "an", "m", "mq", "q"}
            )):
                replacement = "大家"
            yield _issue(
                clause, _PLURAL, *match.span(), "集合名詞 + 們",
                f"將「{match[0]}」寫成「{replacement}」。", replacements=(match.span(),),
            )

    framed_markers = set()
    for frame in _AS_ONE_OF.finditer(text, clause.start, clause.end):
        marker = tokens.get(frame.end())
        if frame.start() not in tokens or marker is None or marker.true_de_role != DE_ATTR:
            continue
        subject = tokens.get(marker.end_char)
        if subject is None or not (_noun_head(subject) or subject.pos in {"r", "d"}):
            continue
        framed_markers.add(frame.end() - len("之一"))
        end = clause.tokens[-1].end_char
        predicate = text[subject.start_char:end]
        yield _issue(
            clause, _PLURAL, frame.start(), end, "作為 + 集合 + 之一 + DE_ATTR + NP",
            f"先用「{predicate}」敘事，再用「是{frame['group']}之一」交代主詞的身分。",
        )

    for part in _ONE_OF.finditer(text, clause.start, clause.end):
        start, end = part.span()
        if start in framed_markers or start not in tokens or end not in ends:
            continue
        copulas = list(_COPULA.finditer(text, clause.start, start))
        group_start = copulas[-1].end() if copulas else clause.start
        prefix = text[group_start:start]
        if _EXPLICIT_GROUP.search(prefix) or _COUNTRIES.search(prefix) or _FRACTION_END.search(prefix):
            continue
        degree = _SUPERLATIVE.search(text, group_start, start)
        if degree:
            member = text[degree.end():start].strip()
            degree_token = tokens.get(degree.start())
            if degree_token:
                yield _issue(
                    clause, _PLURAL, degree.start(), end, "最 + 修飾語 + 之一",
                    f"改寫「{text[degree.start():end]}」時，用「位居前列」表達「{member}」的相對排名。"
                    "保留原比較方向與集合，仍指其中一個成員。",
                    replacements=((degree_token.start_char, degree_token.end_char), (start, end)),
                )
        elif prefix.endswith("其中"):
            start -= len("其中")
            yield _issue(
                clause, _PLURAL, start, end, "其中 + 之一",
                "省去「其中之一」，直接說明所屬類別或點明對象。若需表明集合，補出具體成員。",
                replacements=((start, end),),
            )
        elif copulas:
            yield _issue(
                clause, _PLURAL, start, end, "是／乃 + 泛稱集合 + 之一",
                "省去「之一」，以「是」或「乃」直接陳述前面的身分或類別。",
                replacements=((start, end),),
            )


_BEI = re.compile("被")
_NATURAL_PASSIVE = re.compile(r"\s*(?:殺|捕|毀|淘汰)")
_PASSIVE_PREDICATE = re.compile(
    r"(?P<adverb>(?:(?:徹底|完全|嚴重|暫時|正式|公開|一再|一度|再次|多次|直接|一致|普遍|當場|立即|堅決)\s*)*)"
    r"(?P<verb>接受|拒絕|採用|發現|認為|嚇倒|懷疑|准許|推選為|選為|指出|詢及|升為|改變|核准|駁回|鎖定|要求|否決|公告|歸類為|歸類|延後)"
)
_NATIVE_PASSIVES = {
    "准許": ("獲准", "未獲准"),
    "選為": ("當選為", "未當選為"),
    "升為": ("升為", "未升為"),
    "推選為": ("獲推選為", "未獲推選為"),
    "核准": ("獲核准", "未獲核准"),
}
# 時間／語氣副詞納入診斷 span；「才」等焦點副詞不納入。
_PASSIVE_CUES = {"仍", "已", "至今", "尚未", "從未", "已經", "曾", "曾經", "還", "並"}
_TITLE_VERBS = {"選為", "升為", "推選為", "歸類為"}
_DELAY_DURATION = re.compile(
    rf"\s*(?:{_NUMBER}|半)\s*(?:個半?\s*)?"
    r"(?:年|月|週|周|星期|禮拜|天|日|小時|分鐘|秒)(?:半|多)?\s*"
)


def _agent_phrase(tokens: Sequence[Token], start: int, end: int) -> bool:
    members = [token for token in tokens if start <= token.start_char < end]

    def allowed(index: int) -> bool:
        token = members[index]
        if (
            _noun_head(token) or token.true_de_role == DE_ATTR
            # zg 是「法務／組」這類機構名的詞尾語素。
            or token.pos in {"r", "a", "an", "m", "mq", "q", "zg"}
        ):
            return True
        # 分詞器把「風控專員」切成「風／控／專員」：動詞片段後接名詞中心語時視為複合修飾。
        return token.pos == "v" and index + 1 < len(members) and _noun_head(members[index + 1])

    return any(_noun_head(token) or token.pos == "r" for token in members) and all(
        token.end_char <= end and allowed(index) for index, token in enumerate(members)
    )


def _passive_issues(clause: _Clause) -> Iterator[Issue | None]:
    text = clause.source
    tokens = {token.start_char: token for token in clause.tokens}
    token_ends = {token.end_char: token for token in clause.tokens}
    for head in _BEI.finditer(text, clause.start, clause.end):
        if head.start() not in tokens or _NATURAL_PASSIVE.match(text, head.end(), clause.end):
            continue
        predicate = _PASSIVE_PREDICATE.search(text, head.end(), clause.end)
        if predicate is None:
            continue

        verb_end = predicate.end()
        aspect = tokens.get(verb_end)
        if aspect and aspect.surface in _ASPECT:
            verb_end = aspect.end_char
        agent = text[head.end():predicate.start()].strip()
        if agent:
            bei = tokens[head.start()]
            if bei.end_char != head.end() or not _agent_phrase(clause.tokens, head.end(), predicate.start()):
                continue

        # 否定可獨立成詞（不／未／沒），也可能是前一個副詞的詞尾（仍未／尚未／從未），
        # 或「沒有」這個動詞性否定（並沒有被公告）。
        neg_word = neg_prefix = ""
        phrase_start = head.start()
        previous = token_ends.get(head.start())
        if previous is not None:
            surface = previous.surface
            if surface == "沒" or surface.endswith("沒有"):
                neg_word = "沒"
                neg_prefix = surface[:-2] if surface.endswith("沒有") else ""
                phrase_start = previous.start_char
            elif surface[-1] in {"不", "未"} and (len(surface) == 1 or previous.pos == "d"):
                neg_word = surface[-1]
                neg_prefix = surface[:-1]
                phrase_start = previous.start_char
        negative = bool(neg_word)

        verb = predicate["verb"]
        start, end = phrase_start, verb_end
        cues = ""
        replacements = ()
        if agent:
            # 施受關係反轉時，診斷連同前面的受事一起提供，略過句首連接詞。
            members = clause.tokens
            first = 0
            while first < len(members) - 1 and members[first].pos == "c":
                first += 1
            start = members[first].start_char
            instruction = (
                f"讓施事「{agent}」作主詞，用「{predicate[0]}」作謂語，把原受事接在後面。"
                "保留原句的否定、時間、情態與程度。"
            )
        else:
            # 向左納入時間／語氣副詞（「至今仍未被核准」），到受詞或焦點副詞為止。
            while True:
                previous = token_ends.get(start)
                if previous is None or previous.surface not in _PASSIVE_CUES:
                    break
                start = previous.start_char
            cues = text[start:phrase_start]
            if verb in _TITLE_VERBS:
                # 職稱／賓語併入 span，遇「的」或 clause 邊界即止；改寫只動「被＋V」。
                # 「重大品質異常」的「異常」可被標 d：分句尾的 d／ad 仍視為賓語成分。
                for token in clause.tokens:
                    if token.start_char < end:
                        continue
                    tail_ok = (
                        _noun_head(token) or token.pos in {"a", "an", "b", "m", "mq", "q"}
                        or (token.pos in {"d", "ad"} and token is clause.tokens[-1])
                    )
                    if token.start_char != end or token.true_de_role == DE_ATTR or not tail_ok:
                        break
                    end = token.end_char
            if verb in _NATIVE_PASSIVES:
                # 否定併入原生詞（未獲核准）；副詞前綴（仍）與時間詞分開保留。
                replacement = neg_prefix + predicate["adverb"] + _NATIVE_PASSIVES[verb][negative]
                preserve = f"保留「{cues}」，" if cues else ""
                instruction = (
                    f"{preserve}用「{replacement}」代替「{text[phrase_start:verb_end]}」，"
                    "保留原句的時態與後面的事項或職稱。"
                )
                replacements = ((phrase_start, verb_end),)
            else:
                preserve = f"保留「{cues + neg_prefix}」，" if cues or neg_prefix else ""
                if verb == "懷疑":
                    replacements = ((phrase_start, verb_end),)
                    clause_end = clause.tokens[-1].end_char
                    content = text[verb_end:clause_end].strip()
                    suspicion = f"{content}的嫌疑" if content else "嫌疑"
                    replacement = ("沒有" if negative else "有") + suspicion
                    instruction = f"{preserve}可寫成「{replacement}」，保留「懷疑」在原句的程度、時間和語氣。"
                    end = clause_end
                elif verb == "改變" and not negative:
                    replacement = text[predicate.start():verb_end]
                    instruction = f"{preserve}去掉「被」，用「{replacement}」直接描述原受事的變化。"
                elif verb == "鎖定" and not negative:
                    replacement = text[predicate.start():verb_end]
                    instruction = f"{preserve}用「{replacement}」描述原受事的狀態，施事者維持未明。"
                elif verb == "延後":
                    replacement = text[predicate.start():verb_end]
                    instruction = (
                        f"用「{replacement}」代替「{text[head.start():verb_end]}」，"
                        "保留原句的受事、否定、時量與理由。"
                    )
                    duration = _DELAY_DURATION.fullmatch(text, verb_end, clause.end)
                    if duration:
                        example = text[start:head.start()] + replacement + duration[0].rstrip()
                        instruction += f"連同原有時量可寫成「{example}」。"
                elif verb == "否決":
                    replacement = "遭" + text[predicate.start():verb_end]
                    instruction = (
                        f"用「{replacement}」代替「{text[head.start():verb_end]}」，"
                        "保留原句的受事、否定、審查輪次與理由。施事者維持未明。"
                    )
                else:
                    action = "問起" if verb == "詢及" else verb
                    lead = {"不": "大家都不", "未": "還沒有人", "沒": "還沒有人"}.get(neg_word, "有人")
                    # 「從不／並不」的否定帶強調前綴，改用「沒有人」引出動作。
                    if neg_prefix and neg_word == "不":
                        lead = "沒有人"
                    example = lead + predicate["adverb"] + action
                    instruction = f"{preserve}可用「{example}」引出動作，再把原受事接回句中，保留原意與時態。"
                    if action != verb:
                        replacements = ((predicate.start("verb"), predicate.end("verb")),)
        yield _issue(
            clause, _PASSIVE, start, end, "[不／未] + 被 + [施事／修飾語] + V",
            instruction, replacements=replacements,
        )


def scan(tokens: Sequence[Token], sentence_ctx: SentenceContext, profile: RuleProfile) -> list[Issue]:
    """掃描單一整句，以句內字元座標回傳 L1 診斷。"""
    lexicons = _lexicons()
    issues = []
    for clause in _clauses(tokens, sentence_ctx):
        events = tuple(_events(clause.tokens))
        for rule_issues in (
            _weak_issues(clause, lexicons),
            _event_issues(clause, events),
            _jargon_issues(clause, lexicons, profile),
            _plural_issues(clause),
            _inanimate_issues(clause, events, profile),
            _passive_issues(clause),
        ):
            issues.extend(issue for issue in rule_issues if issue is not None)
    return sorted(issues, key=lambda issue: (issue["priority"], issue["char_idx"]))
