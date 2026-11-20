"""第三層規則：邏輯與銜接機制（由形入意：剝離介詞外框、砍雙重病態因果、以「而」代「及」）。

實作於 TICKET-009。
規格：zh_polish_skill_spec_v2.md §2.3、§5.2 L3 規則矩陣。

L3 是「由外而內」折疊重構的第一層（§6.3）。主語湮沒用 priority 0，
先於一般 L3 外框、銜接建議（priority 1）。
"""

from __future__ import annotations

import re
from typing import Iterator, Sequence

from ..l0_normalizer import DE_ADV, DE_ATTR
from ..tokenizer_adapter import Token
from . import Issue, RuleProfile, SentenceContext


_FRAME = "L3_PREPOSITIONAL_FRAME"
_CAUSAL = "L3_CAUSAL_MALFORMED"
_SHORT_CAUSAL_DROP = "L3_SHORT_CAUSAL_DROP"
_CONJ = "L3_CONJUNCTION_MISUSE"

_BASIS = {
    _FRAME: (
        "中文重意合，直接切入話題。英文 In the process of／Regarding 式介詞外框"
        "把話題核心包在空殼裡，使句子遲遲無法進入正題。"
    ),
    _CAUSAL: (
        "「由於…使得…」先把主句降級為介詞片語，再套使動動詞，整句喪失主詞（主語湮沒）。"
        "中文以事理順序意合銜接，無須顯性因果螺絲釘。"
    ),
    _CONJ: (
        "中文並列有詞性邊界：「及／與」只連名詞，謂詞與形容詞並列靠「而」或直接並置。"
        "無差別連接詞是英文 and 意識的形合氾濫。"
    ),
}
_PSYCH_BASIS = "心理動機可直接用「出於…」交代；「由於…的驅使」是把動機包成名詞的形合外框。"
_SHORT_BASIS = "短句事理自明，因果關係可由語序意合表達，例如「清風徐來，水波不興」。"

# 句內片語邊界：全形與 ASCII 標點、遮罩 NUL。靶心型 NP 另以頓號為界。
_PHRASE_BOUNDARY = "，。！？；：、\0,.!?;:"
_CLAUSE_BOUNDARY = "，。！？；：\0,.!?;:"

_TARGET_HEADS = {"有關", "關於", "針對", "對於"}
_SHELL_NOUNS = "問題|種種|部分|方面|事項|故事"
# 規格中「的」為可選：「有關環境污染的各種問題」不帶「的」仍是外框。
_SHELL = re.compile(rf"(?P<de>的)?(?P<shell>{_SHELL_NOUNS})")
_LEADING_QUANTITY = re.compile(r"^(?:一個|一種|一件|一名|一位|這個|那個|這位|那位)")
_SITUATION = re.compile(
    r"(在|於|從|當)([^，。！？；：、\0]{2,15}?)的"
    r"(過程(?:當)?中|背景(?:之)?下|情況下|前提下|角度來看|層面上|基礎上)"
)
_MIDDLE_PHRASE = "來到我們的中間"

_CAUSE_HEADS = {"由於", "因為", "鑑於"}
_EFFECT_VERBS = {"使得", "導致", "造成", "令"}
_CAUSAL_ADVERBS = {"因而", "因此", "所以", "於是", "可能", "可", "會", "可以", "能"}
_TIME_HEADS = {"到", "到了", "等到", "直到", "在", "於"}
# Jieba 可把「逾時」標為 t，作「導致」的主語時是事件。
_TIME_EVENTS = {"逾時", "超時"}
_PSYCH_NOUNS = {"好奇心": "好奇", "責任感": "責任感", "興趣": "興趣"}
_PSYCH_DRIVE = re.compile(rf"(由於|因為|受到)({'|'.join(_PSYCH_NOUNS)})的(驅使|影響|緣故)")
_SHORT_CAUSAL = re.compile(
    r"(由於|因為)([^，。！？；：\0]{1,8})，(所以|因此)([^，。！？；：\0]{1,8})"
    r"(?=[，。！？；：、\0]|$)"
)

_CONJUNCTIONS = {"及", "以及", "與", "和"}
_LIST_CONJUNCTIONS = {"及", "以及", "和"}
_LIST_INTRODUCERS = {"有", "包括", "包含", "列出", "列舉", "陳列", "展出"}
# Jieba 會把單字謂詞與「及」併成一詞（「慢及／c」「跳及／v」）；
# 這些是詞彙化動詞，不得拆出連詞。
_MERGED_JI_WORDS = {"涉及", "波及", "惠及", "普及", "顧及", "提及", "談及", "論及", "趕及", "觸及", "兼及"}
_MERGED_JI_POS = {"c", "v", "a", "an", "d", "ad"}
_COMPARATIVE_MARKERS = {"更", "越", "較", "更加", "更為", "愈", "越發"}
_COMPARATIVE_PREFIXES = ("更", "越", "較", "愈")
# 謂詞片語的核心詞性：動詞、形容詞及其修飾語（含 Jieba 誤標為 d 的形容詞）。
_PREDICATE_POS = {"v", "vn", "a", "an", "ad", "d", "z"}
_ADJECTIVE_POS = {"a", "an", "z"}
_VERB_POS = {"v", "vn"}
_MANNER_MODIFIER_POS = _ADJECTIVE_POS | {"ad", "d", "i"}
# 這些活動在 Jieba 可能標成名詞，或與狀語標記併成一詞（「地攀岩」）。
_ACTIVITY_NAMES = {"攀岩", "溯溪", "滑雪", "唱歌", "彈琴"}
_ACTION_CUES = {"可", "可以", "能", "會", "請", "將", "正在", "已", "先", "再", "一起", "同時", "自動"}
_OBJECT_POS = {"a", "an", "b", "m", "mq", "q", "r"}
# 嚴格集合定義取同一列舉的引導語，保留冒號前的定義。
_SET_SCOPE_BOUNDARY = "，。！？；\0,.!?;"
_SET_SIZE = r"[0-9〇零一二兩三四五六七八九十百]+(?:種|類|項|個|款|目|組|套|式|級|寶)"
_SET_CUE = re.compile(
    r"(?<![不非])(?:僅限|僅有|只有|限定|限於|定義為|分為|分成|共有|計有|總共|合計)"
    rf"|共\s*{_SET_SIZE}|{_SET_SIZE}[^：:]*[：:]"
)
_SET_COUNT_TAIL = re.compile(rf"[，,]?\s*共\s*{_SET_SIZE}\s*(?=[{_SET_SCOPE_BOUNDARY}]|$)")


def _boundary_before(text: str, end: int, boundaries: str) -> int:
    for index in range(end - 1, -1, -1):
        if text[index] in boundaries:
            return index + 1
    return 0


def _boundary_after(text: str, start: int, boundaries: str) -> int:
    for index in range(start, len(text)):
        if text[index] in boundaries:
            return index
    return len(text)


def _tokens_in(tokens: Sequence[Token], start: int, end: int) -> tuple[Token, ...]:
    return tuple(
        token for token in tokens
        if start <= token.start_char and token.end_char <= end
    )


def _issue(
    text: str,
    tokens: Sequence[Token],
    rule: str,
    start: int,
    end: int,
    pattern: str,
    instruction: str,
    *,
    basis: str | None = None,
    priority: int = 1,
    replaceable: Sequence[Token] = (),
) -> Issue | None:
    # 只豁免被刪改的詞本身凍結；NP 內的凍結術語原樣保留，不影響外框診斷。
    if any(token.is_frozen for token in replaceable):
        return None
    frozen = [
        token.surface for token in tokens
        if token.is_frozen and token.start_char < end and start < token.end_char
    ]
    if frozen:
        words = "、".join(f"「{word}」" for word in dict.fromkeys(frozen))
        instruction += f"保留凍結詞{words}原樣。"
    issue: Issue = {
        "layer": "L3",
        "rule_id": rule,
        "priority": priority,
        "span": text[start:end],
        "char_idx": start,
        "pos_pattern": pattern,
        "theoretical_basis": basis or _BASIS[rule],
        "instruction": instruction,
    }
    if replaceable:
        issue["_replaceable_token_starts"] = tuple(
            token.start_char for token in replaceable if not token.is_frozen
        )
    return issue


def _frame_shell(
    text: str, start: int, end: int, tokens: Sequence[Token], ends: dict[int, Token]
) -> tuple[re.Match[str], str, Token] | None:
    for shell in _SHELL.finditer(text, start, end):
        core = text[start:shell.start()].strip()
        if not 2 <= len(core) <= 15:
            continue
        # 「申請事項」可能是單一 token；空殼須完整落在詞尾。
        shell_token = ends.get(shell.end())
        if shell_token is None or shell_token.start_char > shell.start("shell"):
            continue
        # 「故事的查證」與「故事形式的問題」內的「故事」仍在修飾後面的名詞。
        follower = next(
            (token for token in tokens if shell.end() <= token.start_char < end
             and (token.surface == "的" or not token.pos.startswith("n"))),
            None,
        )
        if follower is not None and (follower.surface == "的" or follower.true_de_role == DE_ATTR):
            continue
        return shell, core, shell_token
    return None


def _target_frames(
    text: str, tokens: Sequence[Token], starts: dict[int, Token]
) -> Iterator[Issue | None]:
    """靶心型：(有關|關於|針對|對於) + NP(2~15字) + 的?(問題|種種|…)?。"""
    ends = {token.end_char: token for token in tokens}
    for token in tokens:
        if token.surface not in _TARGET_HEADS or token.is_frozen:
            continue
        head_end = token.end_char
        if head_end >= len(text) or text[head_end] == "的":
            # 「與帳號有關的問題」：有關作謂語，不是外框。
            continue
        segment_end = _boundary_after(text, head_end, _PHRASE_BOUNDARY)
        frame_shell = _frame_shell(text, head_end, segment_end, tokens, ends)
        if frame_shell is not None:
            shell, core, shell_token = frame_shell
            if shell["shell"] == "問題":
                topic = text[head_end:shell.end()].strip()
                instruction = (
                    f"只刪去「{token.surface}」，保留「問題」，"
                    f"讓「{topic}」直接作主語或受詞。"
                )
                replaceable = [token]
            elif shell["shell"] == "種種":
                instruction = (
                    f"刪去「{token.surface}」，以「{core}的種種」直接作主語或受詞。"
                )
                replaceable = [token]
            else:
                example = _LEADING_QUANTITY.sub("", core)
                instruction = (
                    f"剝除「{token.surface}」與空殼名詞「{shell['shell']}」，"
                    f"以「{example}」直接作主語或受詞。"
                )
                de_token = starts.get(shell.start("de")) if shell["de"] else None
                replaceable = [token, shell_token] + ([de_token] if de_token else [])
            end = shell.end()
            pattern = f"p/vn({token.surface}) + NP + [uj(的)] + n_shell({shell['shell']})"
        else:
            # 「有關部門／有關使用者身分的說明」屬詞彙化用法，無空殼名詞不視為外框。
            if token.surface == "有關":
                continue
            noun = text[head_end:segment_end].strip()
            if not 2 <= len(noun) <= 15 or noun.endswith("的"):
                continue
            end = segment_end
            while end > head_end and text[end - 1].isspace():
                end -= 1
            instruction = (
                f"刪去「{token.surface}」，讓「{noun}」直接作主語或受詞，"
                "不再用介詞外框引出話題。"
            )
            replaceable = [token]
            pattern = f"p({token.surface}) + NP"
        yield _issue(
            text, tokens, _FRAME, token.start_char, end, pattern, instruction,
            replaceable=replaceable,
        )


def _situation_frames(
    text: str, tokens: Sequence[Token], starts: dict[int, Token]
) -> Iterator[Issue | None]:
    """情境型：(在|於|從|當) + NP/VP(2~15字) + 的(過程當中|背景下|…)。"""
    for match in _SITUATION.finditer(text):
        head = starts.get(match.start())
        if head is None or head.surface != match[1]:
            continue
        tail_tokens = _tokens_in(tokens, match.start(3), match.end(3))
        if not tail_tokens or tail_tokens[0].start_char != match.start(3):
            continue
        noun = match[2].strip()
        if match[3].startswith("過程"):
            instruction = (
                f"剝除「{match[0]}」介詞外框，將核心事件「{noun}」轉為時間短句"
                f"「{noun}時，」。"
            )
        else:
            instruction = (
                f"剝除「{match[0]}」介詞外框，改寫為「就{noun}而言，」。"
            )
        yield _issue(
            text, tokens, _FRAME, match.start(), match.end(),
            f"p({match[1]}) + NP/VP + uj(的) + n_frame({match[3]})",
            instruction, replaceable=[head, *tail_tokens],
        )

    start = text.find(_MIDDLE_PHRASE)
    while start != -1:
        end = start + len(_MIDDLE_PHRASE)
        head = starts.get(start)
        phrase_tokens = _tokens_in(tokens, start, end)
        if head is not None and head.surface == "來到" and phrase_tokens:
            yield _issue(
                text, tokens, _FRAME, start, end,
                "v(來到) + r(我們) + uj(的) + f(中間)",
                "將「來到我們的中間」改寫為「光臨」或「來到這裡」，直接迎接來賓。",
                replaceable=list(phrase_tokens),
            )
        start = text.find(_MIDDLE_PHRASE, end)


def _causal_modifier_phrase(tokens: Sequence[Token]) -> bool:
    if all(
        (token.pos in {"d", "ad", "t"} and token.surface not in _TIME_EVENTS)
        or token.surface in _CAUSAL_ADVERBS
        for token in tokens
    ):
        return True
    # 「到了傍晚」可以隔在原因和使動詞之間，仍只交代時間。
    return (
        tokens[0].surface in _TIME_HEADS
        and any(token.pos == "t" for token in tokens[1:])
        and all(token.pos in {"t", "m", "mq", "q", "f"} or token.surface == "了"
                for token in tokens[1:])
    )


def _subjectless_effect(text: str, tokens: Sequence[Token], comma: int) -> Token | None:
    while comma < len(text) and text[comma] in "，,":
        end = _boundary_after(text, comma + 1, _CLAUSE_BOUNDARY)
        members = _tokens_in(tokens, comma + 1, end)
        for index, token in enumerate(members):
            if token.surface in _EFFECT_VERBS and token.pos == "v":
                # 「重試機制導致」前面已有主語，正常敘述到此停止。
                return token if _causal_modifier_phrase(members[:index]) else None
        if not members or not _causal_modifier_phrase(members):
            # 「他跌倒，導致……」已有事件承接後續結果。
            break
        comma = end
    return None


def _double_causal(text: str, tokens: Sequence[Token]) -> Iterator[Issue | None]:
    """原因分句後直接接使動謂語，前面可帶副詞或時間片語。"""
    for head in tokens:
        if head.surface not in _CAUSE_HEADS:
            continue
        comma = _boundary_after(text, head.end_char, _CLAUSE_BOUNDARY)
        cause = text[head.end_char:comma].strip()
        effect = _subjectless_effect(text, tokens, comma) if cause else None
        if effect is None:
            continue
        instruction = (
            f"刪去「{head.surface}」與「{effect.surface}」，還原主語，"
            f"讓「{cause}」直接作原因分句，保留原本的因果關係。"
        )
        yield _issue(
            text, tokens, _CAUSAL, head.start_char, effect.end_char,
            f"c/p({head.surface}) + 原因分句 + ， + [修飾語] + v({effect.surface})",
            instruction, priority=0, replaceable=[head, effect],
        )


def _psych_drive(
    text: str, tokens: Sequence[Token], starts: dict[int, Token]
) -> Iterator[Issue | None]:
    """心理名詞驅使：(由於|因為|受到) + 心理名詞 + 的(驅使|影響|緣故)。"""
    for match in _PSYCH_DRIVE.finditer(text):
        head = starts.get(match.start())
        if head is None or head.surface != match[1]:
            continue
        phrase_tokens = _tokens_in(tokens, match.start(), match.end())
        core = _PSYCH_NOUNS[match[2]]
        yield _issue(
            text, tokens, _CAUSAL, match.start(), match.end(),
            f"p/c({match[1]}) + 心理名詞({match[2]}) + uj(的) + {match[3]}",
            f"將「{match[0]}」簡化為「出於{core}」，直接交代動機。",
            basis=_PSYCH_BASIS, replaceable=list(phrase_tokens),
        )


def _short_causal(
    text: str, tokens: Sequence[Token], starts: dict[int, Token], causal_heads: set[int]
) -> Iterator[Issue | None]:
    """短句形合過剩：由於/因為 [A≤8字]，所以/因此 [B≤8字]。

    同一句首已由主語湮沒／心理驅使診斷時不重複發布。
    """
    for match in _SHORT_CAUSAL.finditer(text):
        head = starts.get(match.start())
        connective = starts.get(match.start(3))
        if head is None or head.surface != match[1] or match.start() in causal_heads:
            continue
        if connective is None or connective.surface != match[3]:
            continue
        cause, effect = match[2].strip(), match[4].strip()
        if not cause or not effect:
            continue
        yield _issue(
            text, tokens, _CAUSAL, match.start(), match.end(4),
            f"c({match[1]}) + 短句A + ， + c({match[3]}) + 短句B",
            f"刪去「{match[1]}」與「{match[3]}」，以逗號意合並置：「{cause}，{effect}」。",
            basis=_SHORT_BASIS, replaceable=[head, connective],
        )


def _comparative(side: Sequence[Token]) -> bool:
    return any(
        token.surface in _COMPARATIVE_MARKERS or token.surface.startswith(_COMPARATIVE_PREFIXES)
        for token in side
    )


def _run_member(token: Token, previous: Token | None) -> bool:
    if token.pos in _PREDICATE_POS or token.surface.startswith("有"):
        return True
    if token.surface in _COMPARATIVE_MARKERS or token.surface.startswith(_COMPARATIVE_PREFIXES):
        return True
    # 「越省力」的省力、「有遠見」的遠見：比較級／有字後的名詞仍屬謂詞片語。
    if token.pos.startswith("n") and previous is not None and (
        previous.surface in _COMPARATIVE_MARKERS
        or previous.surface.startswith(_COMPARATIVE_PREFIXES)
        or previous.surface.startswith("有")
    ):
        return True
    return False


def _predicate_side(side: Sequence[Token]) -> bool:
    if not side or not all(
        token.pos in _PREDICATE_POS or token.pos == "l" or token.surface.startswith("有")
        for token in side
    ):
        return False
    return any(token.pos in _PREDICATE_POS for token in side) or side[0].surface.startswith("有")


def _adjective_core(side: Sequence[Token]) -> bool:
    return any(token.pos in _ADJECTIVE_POS for token in side) or (
        len(side) == 1 and side[0].pos in {"d", "ad"}
    )


def _list_item_ok(item_tokens: Sequence[Token]) -> bool:
    # 單詞項目容忍詞性誤標（「訪客」標 v、「A」標 x）；多詞項目須以名詞類收尾。
    if len(item_tokens) == 1:
        return True
    return bool(item_tokens) and (
        item_tokens[-1].pos.startswith("n") or item_tokens[-1].pos in {"x", "r", "m", "q"}
    )


def _first_list_item(members: tuple[Token, ...]) -> tuple[tuple[Token, ...], int | None]:
    start = 0
    for index, token in enumerate(members):
        if token.surface == "的" or token.true_de_role == DE_ATTR:
            start = index + 1
    # 「包含糖的點心有…」以定語後的引導語為準；「列出來自臺灣的芒果」保留首項定語。
    for index in range(start, len(members) - 1):
        if members[index].surface in _LIST_INTRODUCERS:
            return members[index + 1:], index
    for index, token in enumerate(members[:start]):
        if token.surface in _LIST_INTRODUCERS:
            return members[index + 1:], index
    while start < len(members) and members[start].pos in {"r", "y", "p", "d"}:
        start += 1
    return members[start:], None


def _noun_list_tail(
    text: str, tokens: Sequence[Token], conj: Token, left_bound: int, right_bound: int
) -> Issue | None:
    """同類名詞串列尾綴：N1、N2、N3 (及|以及|和) N4；嚴格集合定義豁免。"""
    if conj.surface not in _LIST_CONJUNCTIONS:
        return None
    region = text[left_bound:conj.start_char]
    if "、" not in region:
        return None
    raw_items = region.split("、")
    header_start = _boundary_before(text, left_bound, _SET_SCOPE_BOUNDARY)
    header_end = left_bound + len(raw_items[0])
    first_members = _tokens_in(tokens, left_bound, header_end)
    first_item, introducer = _first_list_item(first_members)
    if introducer is not None:
        # 「僅限會員報名的課程包含…」的限制在修飾「課程」，列舉由「包含」引出。
        header_start = max(
            (token.end_char for token in first_members[:introducer]
             if token.surface == "的" or token.true_de_role == DE_ATTR),
            default=header_start,
        )
    if (
        _SET_CUE.search(text, header_start, header_end)
        or _SET_COUNT_TAIL.search(text, conj.end_char, right_bound)
        or _SET_COUNT_TAIL.match(text, right_bound)
    ):
        return None
    right_raw = text[conj.end_char:right_bound]
    right_text = right_raw.strip()
    right_tokens = _tokens_in(tokens, conj.end_char, right_bound)
    if not right_text or len(right_text) > 15 or not _list_item_ok(right_tokens):
        return None

    list_start = left_bound
    cursor = left_bound
    for index, raw in enumerate(raw_items):
        end = cursor + len(raw)
        members = first_item if index == 0 else _tokens_in(tokens, cursor, end)
        if not _list_item_ok(members):
            return None
        if index == 0:
            list_start = members[0].start_char
            raw = text[list_start:end]
        if len(raw.strip()) > 15:
            return None
        cursor = end + 1

    list_end = conj.end_char + len(right_raw.rstrip())
    example = text[list_start:conj.start_char].strip() + "、" + right_text
    return _issue(
        text, tokens, _CONJ, list_start, list_end,
        f"N1、N2、… + c({conj.surface}) + N4",
        f"同類名詞串列改用頓號並置：刪去「{conj.surface}」，寫成「{example}」。",
        replaceable=[conj],
    )


def _right_run(tokens: Sequence[Token], index: int, right_bound: int) -> list[Token]:
    right: list[Token] = []
    for i in range(index + 1, len(tokens)):
        token = tokens[i]
        if token.end_char > right_bound or not _run_member(token, tokens[i - 1]):
            break
        right.append(token)
    return right


def _right_modifier_follower(tokens: Sequence[Token], right: Sequence[Token]) -> bool:
    # 右側若接「的＋名詞」，整個片語是定語而非謂詞並列。
    follower = next((token for token in tokens if token.start_char >= right[-1].end_char), None)
    return follower is not None and follower.start_char == right[-1].end_char and (
        follower.surface == "的" or follower.true_de_role == DE_ATTR
    )


def _predicate_conjunction(
    text: str, tokens: Sequence[Token], index: int, conj: Token,
    left_bound: int, right_bound: int,
) -> Issue | None:
    """連接謂詞／形容詞片語或比較級：左右鄰居須同為謂詞性，名詞並列不觸發。"""
    # 向左、向右都只收謂詞性鄰居；名詞僅在緊鄰比較級／「有」時納入（越省力）。
    left: list[Token] = []
    for i in range(index - 1, -1, -1):
        token = tokens[i]
        if token.start_char < left_bound or not _run_member(token, tokens[i - 1] if i else None):
            break
        left.insert(0, token)
    right = _right_run(tokens, index, right_bound)
    if not left or not right or _right_modifier_follower(tokens, right):
        return None

    left_text = text[left[0].start_char:left[-1].end_char]
    right_text = text[right[0].start_char:right[-1].end_char]
    if _comparative(left) and _comparative(right):
        if len(left_text) == 4 and len(right_text) == 4:
            instruction = f"對稱四字比較級改用逗號並置：「{left_text}，{right_text}」。"
        else:
            instruction = f"比較級並列改用「而」：「{left_text}而{right_text}」。"
        pattern = f"更／越比較級 + c({conj.surface}) + 更／越比較級"
    else:
        if not (_predicate_side(left) and _predicate_side(right)):
            return None
        # 純動詞＋動詞（「閱讀與寫作」）常是名物化的活動並列，要求至少一側為
        # 形容詞核心或「有…」片語，才判為謂詞並列。
        if not (
            _adjective_core(left) or _adjective_core(right)
            or left[0].surface.startswith("有") or right[0].surface.startswith("有")
        ):
            return None
        instruction = f"謂詞並列改用「而」：「{left_text}而{right_text}」。"
        pattern = f"vp/ap + c({conj.surface}) + vp/ap"
    return _issue(
        text, tokens, _CONJ, left[0].start_char, right[-1].end_char, pattern, instruction,
        replaceable=[conj],
    )


def _verb_objects(tokens: Sequence[Token]) -> bool:
    return all(token.pos.startswith("n") or token.pos in _OBJECT_POS for token in tokens)


def _manner_action(tokens: Sequence[Token], index: int) -> bool:
    if index + 1 >= len(tokens):
        return False
    modifier, marker = tokens[index:index + 2]
    if modifier.end_char != marker.start_char or (
        modifier.pos not in _MANNER_MODIFIER_POS and marker.true_de_role != DE_ADV
    ):
        return False

    if marker.surface.startswith("地") and marker.surface[1:] in _ACTIVITY_NAMES:
        return _verb_objects(tokens[index + 2:])
    if index + 2 >= len(tokens) or (marker.surface != "地" and marker.true_de_role != DE_ADV):
        return False
    action = tokens[index + 2]
    return (
        marker.end_char == action.start_char
        and (action.pos in _VERB_POS or action.surface in _ACTIVITY_NAMES)
        and _verb_objects(tokens[index + 3:])
    )


def _verb_phrase_conjunction(
    text: str, tokens: Sequence[Token], conj: Token, left_bound: int, right_bound: int
) -> Issue | None:
    left = _tokens_in(tokens, left_bound, conj.start_char)
    right = _tokens_in(tokens, conj.end_char, right_bound)
    if _manner_action(right, 0):
        for index in range(len(left) - 2, -1, -1):
            if not _manner_action(left, index):
                continue
            start, end = left[index].start_char, right[-1].end_char
            left_text = text[start:conj.start_char].rstrip()
            right_text = text[conj.end_char:end].lstrip()
            return _issue(
                text, tokens, _CONJ, start, end, f"狀語 + vp + c({conj.surface}) + 狀語 + vp",
                f"帶狀語的動作片語可用逗號並置：「{left_text}，{right_text}」。",
                replaceable=[conj],
            )

    left_verb = next(
        (index for index in range(len(left) - 1, -1, -1)
         if left[index].pos in _VERB_POS and left[index].surface not in _ACTION_CUES),
        None,
    )
    right_verb = next(
        (index for index, token in enumerate(right)
         if token.surface not in _ACTION_CUES and token.pos not in {"d", "ad"}),
        None,
    )
    if left_verb is None or right_verb is None or right[right_verb].pos not in _VERB_POS:
        return None

    left_object = left[left_verb + 1:]
    right_object = right[right_verb + 1:]
    if not (_verb_objects(left_object) and _verb_objects(right_object)):
        return None
    # 「先檢查及核對」有動作線索，句首的雙動賓片語也屬謂詞並列。
    cues = (*left[max(0, left_verb - 1):left_verb], *right[:right_verb])
    sentence_initial_pair = left_verb == 0 and left_object and right_object
    if not sentence_initial_pair and not any(token.surface in _ACTION_CUES for token in cues):
        return None

    start, end = left[left_verb].start_char, right[-1].end_char
    example = text[start:conj.start_char].rstrip() + "而" + text[conj.end_char:end].lstrip()
    return _issue(
        text, tokens, _CONJ, start, end, f"vp + c({conj.surface}) + vp",
        f"謂詞並列改用「而」：「{example}」。", replaceable=[conj],
    )


def _merged_ji_conjunction(
    text: str, tokens: Sequence[Token], index: int, merged: Token, right_bound: int
) -> Issue | None:
    """「慢及可靠」：Jieba 把單字謂詞與「及」併成一詞，拆出字尾連詞診斷。"""
    right = _right_run(tokens, index, right_bound)
    if not right or _right_modifier_follower(tokens, right):
        return None
    if not _predicate_side(right):
        return None
    if not (
        merged.pos == "c" or _adjective_core(right) or right[0].surface.startswith("有")
    ):
        return None
    left_char = merged.surface[0]
    right_text = text[right[0].start_char:right[-1].end_char]
    replaceable = [merged] if merged.pos in {"v", "vn", "a", "an"} else []
    return _issue(
        text, tokens, _CONJ, merged.start_char, right[-1].end_char,
        f"單字謂詞＋及（併詞） + {merged.pos} + vp/ap",
        f"謂詞並列改用「而」：「{left_char}而{right_text}」。",
        replaceable=replaceable,
    )


def _conjunction_issues(
    text: str, tokens: Sequence[Token]
) -> Iterator[Issue | None]:
    for index, token in enumerate(tokens):
        if token.is_frozen:
            continue
        if token.surface in _CONJUNCTIONS:
            left_bound = _boundary_before(text, token.start_char, _CLAUSE_BOUNDARY)
            right_bound = _boundary_after(text, token.end_char, _PHRASE_BOUNDARY)
            issue = _noun_list_tail(text, tokens, token, left_bound, right_bound)
            if issue is None and "、" not in text[left_bound:token.start_char]:
                issue = _predicate_conjunction(
                    text, tokens, index, token, left_bound, right_bound
                ) or _verb_phrase_conjunction(text, tokens, token, left_bound, right_bound)
            yield issue
        elif (
            len(token.surface) == 2 and token.surface.endswith("及")
            and token.surface not in _MERGED_JI_WORDS and token.pos in _MERGED_JI_POS
        ):
            left_bound = _boundary_before(text, token.start_char, _CLAUSE_BOUNDARY)
            if "、" in text[left_bound:token.start_char]:
                continue
            right_bound = _boundary_after(text, token.end_char, _PHRASE_BOUNDARY)
            yield _merged_ji_conjunction(text, tokens, index, token, right_bound)


def scan(tokens: Sequence[Token], sentence_ctx: SentenceContext, profile: RuleProfile) -> list[Issue]:
    """掃描單一整句，以句內字元座標回傳 L3 診斷。"""
    text = sentence_ctx.text
    visible = tuple(token for token in tokens if not token.surface.isspace())
    starts = {token.start_char: token for token in visible}
    issues: list[Issue] = []
    for generator in (
        _target_frames(text, visible, starts),
        _situation_frames(text, visible, starts),
        _double_causal(text, visible),
        _psych_drive(text, visible, starts),
    ):
        issues.extend(issue for issue in generator if issue is not None)
    if _SHORT_CAUSAL_DROP not in profile["disabled_rules"]:
        causal_heads = {issue["char_idx"] for issue in issues if issue["rule_id"] == _CAUSAL}
        issues.extend(
            issue for issue in _short_causal(text, visible, starts, causal_heads)
            if issue is not None
        )
    issues.extend(issue for issue in _conjunction_issues(text, visible) if issue is not None)
    return sorted(issues, key=lambda issue: (issue["priority"], issue["char_idx"]))
