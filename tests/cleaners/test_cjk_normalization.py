"""Tests for the Japanese and Chinese rules of the text normalisation cleaner (ADR-069)."""

import time

import pytest
from hypothesis import given
from hypothesis import strategies as st

from sugo.analyzers.lexicon import Lexicon, LexiconAnalyzer
from sugo.cleaners.text_normalization import TextNormalizationCleaner
from sugo.core.decisions import apply_decisions
from sugo.core.models import Block, BlockType, EditKind, Page, PageOrigin
from sugo.core.text import visible
from sugo.metrics.tokenizer import count_tokens

# Written with chr() so the source holds no confusable characters.
FW_COMMA = chr(0xFF0C)
FW_ABC123 = "".join(chr(0xFF21 + n) for n in range(3)) + "".join(chr(0xFF11 + n) for n in range(3))
HW_KA = chr(0xFF76)
HW_VOICED = chr(0xFF9E)
IDEOGRAPHIC_SPACE = chr(0x3000)


def page(text: str, block_type: BlockType = BlockType.PARAGRAPH) -> Page:
    block = Block(id="b0", type=block_type, text=text, origin_engine="t")
    return Page(index=0, width=100, height=100, origin=PageOrigin.NATIVE, blocks=(block,))


def lexicon_of(text: str) -> Lexicon:
    analyzer = LexiconAnalyzer()
    analyzer.observe(page(text))
    return analyzer.finalize()


def cleaned(text: str, languages: tuple[str, ...] = ("ja",), **kwargs: BlockType) -> Block:
    p = page(text, **kwargs)
    cleaner = TextNormalizationCleaner(languages)
    out = apply_decisions(p, cleaner.propose(p, lexicon_of(text)), cleaner=cleaner.name)
    return out.blocks[0]


def clean(text: str, languages: tuple[str, ...] = ("ja",)) -> str:
    return cleaned(text, languages).text


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("全\n角", "全角"),
        ("長い文章で\n、行の途中", "長い文章で、行の途中"),
        ("英数\n字です。", "英数字です。"),
        ("全  \n  角", "全角"),
        ("段落。\n\n次の段落", "段落。\n\n次の段落"),  # a paragraph break stays
        ("Python\nを使う", "Python\nを使う"),  # a Latin letter touches the break
        ("を\nPython", "を\nPython"),
        ("第1\n章", "第1\n章"),  # so does a digit
        ("ABC1\n23", "ABC1\n23"),
        (FW_ABC123[:4] + "\n" + FW_ABC123[4:], "ABC123"),  # full-width ones are CJK text
        (FW_ABC123 + "は", "ABC123は"),
        ("北京市" + FW_COMMA + "海淀区", "北京市" + FW_COMMA + "海淀区"),  # punctuation stays
        (HW_KA + HW_VOICED + "ス", "ガス"),
        (IDEOGRAPHIC_SPACE + "字下げ", IDEOGRAPHIC_SPACE + "字下げ"),
        ("简体\n繁體", "简体繁體"),  # never converted between the two writings
    ],
)
def test_japanese_and_chinese_rules(text: str, expected: str) -> None:
    assert clean(text) == expected
    assert clean(text, ("zh",)) == expected


def test_the_line_join_is_recorded_as_its_own_kind() -> None:
    block = cleaned("全\n角")
    assert [e.kind for e in block.edits] == [EditKind.CJK_JOIN]
    assert block.original_text() == "全\n角"


@pytest.mark.parametrize("languages", [("en",), ("it", "de")])
def test_other_languages_leave_cjk_text_alone(languages: tuple[str, ...]) -> None:
    text = "全\n角" + FW_ABC123
    assert clean(text, languages) == text


def test_mixed_languages_apply_both_packs() -> None:
    assert clean("dell' albero\n全\n角", ("it", "ja")) == "dell'albero\n全角"


def test_headings_are_joined_too() -> None:
    block = cleaned("第一章\n総則", block_type=BlockType.HEADING)
    assert block.text == "第一章総則"


def test_code_is_left_alone() -> None:
    assert cleaned("全\n角", block_type=BlockType.CODE).text == "全\n角"


def test_tokens_saved_on_a_japanese_pdf_paragraph() -> None:
    lines = [
        "日本語の文書を変換するテストです。この段落は長い文章で",
        "、行の途中で改行されています。" + FW_ABC123 + "は全角の英数",
        "字です。",
    ]
    text = "\n".join(lines * 3)
    before, after = count_tokens(text), count_tokens(clean(text))
    assert after <= before * 0.92, (before, after)


def test_long_hostile_text_stays_fast() -> None:
    text = "全\n" * 50_000 + FW_ABC123 * 10_000
    start = time.perf_counter()
    clean(text)
    assert time.perf_counter() - start < 2


_TEXT = st.text(
    alphabet=st.sampled_from(
        ["全", "か", "。", FW_COMMA, "\n", " ", "a", "1", "-", FW_ABC123[0], HW_KA, HW_VOICED]
    ),
    max_size=60,
)


@pytest.mark.invariant
@given(_TEXT, st.sampled_from([("ja",), ("zh",), ("en", "ja")]))
def test_cjk_normalisation_never_changes_what_a_reader_sees(
    text: str, languages: tuple[str, ...]
) -> None:
    """Principle 4: only spacing, width forms and line-break hyphens change."""
    block = cleaned(text, languages)
    joined = sum(1 for e in block.edits if e.kind == EditKind.HYPHEN_JOIN)
    assert len(visible(block.text)) == len(visible(text)) - joined
    assert block.original_text() == text
