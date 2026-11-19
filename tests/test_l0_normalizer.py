"""TICKET-004：遮罩、字元座標與「的／地／得」消歧義。"""

from __future__ import annotations

import pytest

from engine.l0_normalizer import DE_ADV, DE_ATTR, DE_COMP, L0Error, L0Result, normalize
from engine.tokenizer_adapter import JiebaPosAdapter, Token


@pytest.fixture(scope="module")
def tokenizer() -> JiebaPosAdapter:
    adapter = JiebaPosAdapter()
    adapter.tokenize("暖機")
    return adapter


def _assert_offsets(text: str, result: L0Result) -> None:
    masks_by_start = {region.original_start: region for region in result.mask_regions}
    cursor = 0
    for token in result.tokens:
        assert token.start_char == cursor
        masked = masks_by_start.get(cursor)
        if masked:
            assert token.end_char == masked.original_end
            assert token.surface == result.masked_text[masked.masked_start:masked.masked_end]
            assert token.pos == "x"
            assert not token.is_frozen
            assert not token.true_de_role
        else:
            assert text[token.start_char:token.end_char] == token.surface
        cursor = token.end_char
    assert cursor == len(text)
    assert "".join(token.surface for token in result.tokens) == result.masked_text


def test_masks_all_six_markdown_regions_and_keeps_link_text(tokenizer):
    frontmatter = "\ufeff---\r\n標題: 跑的很快\r\n..."
    fence = "````md\r\n進行研究，跑的很快。\r\n```\r\n> 程式碼範例\r\n`````"
    inline = "``跑的很快，含有 `字元` ``"
    url = "](https://example.test/跑的很快(註)/附錄)"
    latex = r"$跑的很快+\$x$"
    quote = "> 引文跑的很快。`範例`和[引用](https://example.test/字)"
    document = (
        f"{frontmatter}\r\n{fence}\r\n{inline} [可掃描：跑的很快{url}\r\n"
        f"{latex}\r\n{quote}\r\n🏃正文也跑的很快。"
    )

    result = normalize(document, tokenizer)

    protected = [frontmatter, fence, inline, url, latex, quote]
    assert [
        document[region.original_start:region.original_end]
        for region in result.mask_regions
    ] == protected
    assert "[可掃描：跑的很快__MASK_3__\r\n" in result.masked_text
    assert "進行研究" not in result.masked_text
    assert [issue["char_idx"] for issue in result.issues] == [
        document.index("可掃描：跑的") + len("可掃描：跑"),
        document.rindex("的"),
    ]
    assert [entry["char_idx"] for entry in result.de_normalization_map] == [
        issue["char_idx"] for issue in result.issues
    ]
    _assert_offsets(document, result)


@pytest.mark.parametrize(
    "destination",
    [
        'https://example.test/跑的很快(章節) "標題有 ( 字元"',
        "<https://example.test/跑的很快)括號> '標題有 ) 字元'",
        r"https://example.test/跑的很快\)附錄",
    ],
)
def test_link_destination_with_escaped_brackets_or_title(tokenizer, destination):
    text = f"[跑的很快]({destination})。跑的很快。"
    result = normalize(text, tokenizer)

    assert result.masked_text == "[跑的很快__MASK_0__。跑的很快。"
    assert [issue["char_idx"] for issue in result.issues] == [text.index("的"), text.rindex("的")]
    _assert_offsets(text, result)


def test_offsets_with_adjacent_masks_and_literal_placeholder_text(tokenizer):
    document = "__MASK_0__😺" + "`x`$x$" * 6 + "跑的很快。`尾端`"

    result = normalize(document, tokenizer)

    assert len(result.mask_regions) == 13
    assert result.masked_text.startswith("__MASK_0__😺__MASK_0____MASK_1__")
    assert "__MASK_10____MASK_11__跑的很快。__MASK_12__" in result.masked_text
    assert result.issues[0]["char_idx"] == document.index("的")
    _assert_offsets(document, result)


def test_currency_escaped_delimiters_and_cross_line_math_stay_visible(tokenizer):
    text = r"付款 $100 和 $200。轉義 \`文字\` 及 \$費用。未閉合 $x" + "\ny$。計算 $a+b$。"

    result = normalize(text, tokenizer)

    assert result.masked_text == text.replace("$a+b$", "__MASK_0__")
    _assert_offsets(text, result)


def test_quoted_delimiters_do_not_consume_prose_and_unclosed_fence_is_protected(tokenizer):
    text = "破損的 `開頭\n>引文的 `開頭\n跑的很快。\n~~~python\ntext = '跑的很快'"

    result = normalize(text, tokenizer)

    assert result.masked_text == "破損的 `開頭\n__MASK_0__\n跑的很快。\n__MASK_1__"
    assert [issue["char_idx"] for issue in result.issues] == [text.index("跑的") + 1]
    _assert_offsets(text, result)


def test_inline_code_may_span_lines_but_not_paragraphs(tokenizer):
    text = "同段 `程式碼\n跑的很快`。\n\n未閉合 `段落\n\n另一段 `範例`跑的很快。"

    result = normalize(text, tokenizer)

    assert result.masked_text == "同段 __MASK_0__。\n\n未閉合 `段落\n\n另一段 __MASK_1__跑的很快。"
    assert [issue["char_idx"] for issue in result.issues] == [text.rindex("的")]
    _assert_offsets(text, result)


def test_mask_placeholder_is_a_boundary_for_the_pos_window(tokenizer):
    text = "跑的`跑的很快`很快。"
    result = normalize(text, tokenizer)

    assert result.de_normalization_map == [
        {"char_idx": 1, "surface": "的", "true_role": DE_ATTR}
    ]
    assert result.issues == []
    _assert_offsets(text, result)


def test_token_crossing_mask_boundaries_is_retokenized_with_whitelist():
    class CrossingTokenizer(JiebaPosAdapter):
        def tokenize(self, text: str) -> list[Token]:
            if "__MASK_0__" in text:
                return [Token(text, "x", 0, len(text), False)]
            return super().tokenize(text)

    adapter = CrossingTokenizer([{"term": "介面追蹤碼", "pos": "nz"}])
    text = "介面追蹤碼`範例`跑的很快"

    result = normalize(text, adapter)

    assert result.tokens[0] == Token("介面追蹤碼", "nz", 0, len("介面追蹤碼"), True)
    assert result.issues[0]["char_idx"] == text.rindex("的")
    _assert_offsets(text, result)


@pytest.mark.parametrize(
    ("text", "surface", "role"),
    [
        ("她跑的太慢。", "的", DE_COMP),
        ("她跑的極好。", "的", DE_COMP),
        ("她跑的更遠。", "的", DE_COMP),
        ("她講的十分明白。", "的", DE_COMP),
        ("她跑的不夠快。", "的", DE_COMP),
        ("他說的相當清楚。", "的", DE_COMP),
        ("他累的要命。", "的", DE_COMP),
        ("他洗的一乾二淨。", "的", DE_COMP),
        ("他跑的多。", "的", DE_COMP),
        ("他唱的嘹亮。", "的", DE_COMP),
        ("清楚得很", "得", DE_COMP),
        ("清楚得很。", "得", DE_COMP),
        ("她跑得很快。", "得", DE_COMP),
        ("她跑地很快。", "地", DE_COMP),
        ("她曬的太陽穴。", "的", DE_ATTR),
        ("她買的很多書。", "的", DE_ATTR),
        ("我說的更新內容。", "的", DE_ATTR),
        ("說的好話。", "的", DE_ATTR),
        ("紅的蘋果。", "的", DE_ATTR),
        ("我的。", "的", DE_ATTR),
        ("高興的跳起來。", "的", DE_ADV),
        ("欣然的去研究。", "的", DE_ADV),
        ("他詳細的評估了這個方案。", "的", DE_ADV),
        ("詳細的評估這個方案。", "的", DE_ADV),
        ("詳細地評估了。", "地", DE_ADV),
        ("一份詳細的評估報告。", "的", DE_ATTR),
        ("這項詳細的評估報告。", "的", DE_ATTR),
        ("進行詳細的評估報告。", "的", DE_ATTR),
        ("詳細的評估。", "的", DE_ATTR),
        ("他的研究報告。", "的", DE_ATTR),
    ],
)
def test_de_roles_and_typo_diagnostics(tokenizer, text, surface, role):
    result = normalize(text, tokenizer)
    index = text.index(surface)

    assert result.de_normalization_map == [
        {"char_idx": index, "surface": surface, "true_role": role}
    ]
    assert next(token for token in result.tokens if token.start_char == index).true_de_role == role
    if role == DE_COMP and surface != "得":
        assert result.issues == [
            {
                "layer": "L0",
                "rule_id": "L0_TYPO_DE_COMP",
                "char_idx": index,
                "surface": surface,
                "suggestion": "得",
                "theoretical_basis": "補語標記應用「得」",
            }
        ]
    else:
        assert result.issues == []


@pytest.mark.parametrize(
    ("words", "expected"),
    [
        ([("說", "v"), ("的", "uj"), ("好", "a"), ("話", "n")], DE_ATTR),
        ([("紅", "a"), ("的", "uj"), ("小", "a"), ("蘋果", "n")], DE_ATTR),
        ([("能", "v"), ("的", "uj"), ("很快", "d")], DE_ATTR),
        ([("會", "v"), ("的", "uj"), ("很快", "d")], DE_ATTR),
        ([("可以", "v"), ("的", "uj"), ("很快", "d")], DE_ATTR),
        ([("無情", "a"), ("的", "uj"), ("被", "p"), ("淘汰", "v")], DE_ADV),
        ([("謹慎", "a"), ("的", "uj"), ("將", "d"), ("研究", "vn")], DE_ADV),
        ([("平靜", "a"), ("的", "uj"), ("被", "p"), ("現象", "n")], DE_ATTR),
        ([("快", "a"), ("的", "uj"), ("走", "v")], DE_ATTR),
    ],
)
def test_pos_window_guardrails(tokenizer, monkeypatch, words, expected):
    tokens = []
    cursor = 0
    for word, pos in words:
        tokens.append(Token(word, pos, cursor, cursor + len(word), False))
        cursor += len(word)
    monkeypatch.setattr(tokenizer, "tokenize", lambda text: tokens)

    result = normalize("".join(word for word, _ in words), tokenizer)

    assert result.de_normalization_map[0]["true_role"] == expected
    assert result.issues == []


def test_excludes_embedded_de_modal_dei_and_noun_di(tokenizer):
    text = "獲得、得到、覺得、值得、記得。我得去。我得回家。我得馬上走。他買了一塊地。"
    result = normalize(text, tokenizer)

    assert result.de_normalization_map == []
    assert result.issues == []
    assert all(not token.true_de_role for token in result.tokens)


def test_frozen_terms_keep_their_spans_and_are_not_annotated():
    prefix = "`code`"
    term = "水流的渦旋模式"
    adapter = JiebaPosAdapter([{"term": term, "pos": "nz"}])

    result = normalize(f"{prefix}{term}。", adapter)

    assert result.tokens[1] == Token(term, "nz", len(prefix), len(prefix) + len(term), True)
    assert result.de_normalization_map == []
    assert result.issues == []


def test_golden_case_2_l0_assertions():
    text = "老師苦口婆心的勸了那個長得像你兄弟說話也有點像他的陌生男人半天，但他還是跑的很快。"
    result = normalize(text)

    adverbial = text.index("的勸")
    complement = text.index("的很快")
    assert {
        token.start_char: token.true_de_role
        for token in result.tokens
        if token.start_char in {adverbial, complement}
    } == {adverbial: DE_ADV, complement: DE_COMP}
    assert result.issues == [
        {
            "char_idx": complement,
            "layer": "L0",
            "rule_id": "L0_TYPO_DE_COMP",
            "surface": "的",
            "suggestion": "得",
            "theoretical_basis": "補語標記應用「得」",
        }
    ]


def test_empty_and_invalid_input(tokenizer):
    assert normalize("", tokenizer) == L0Result("", [], [], [], [])
    with pytest.raises(L0Error, match="字串"):
        normalize(None, tokenizer)  # type: ignore[arg-type]
