"""Tests for the text normalisation cleaner: spacing, invisible characters,
ligatures, composition, line-break hyphens and elisions (ADR-050)."""

import time

import pytest
from hypothesis import given
from hypothesis import strategies as st

from sugo.analyzers.lexicon import Lexicon, LexiconAnalyzer
from sugo.cleaners.text_normalization import TextNormalizationCleaner
from sugo.core.decisions import apply_decisions
from sugo.core.models import Block, BlockType, Page, PageOrigin, Table, TableCell
from sugo.core.text import visible
from sugo.metrics.tokenizer import count_tokens

NBSP = chr(0xA0)
NNBSP = chr(0x202F)
FI = chr(0xFB01)
SOFT_HYPHEN = chr(0xAD)
ZWSP = chr(0x200B)
ZWJ = chr(0x200D)
ACUTE = chr(0x301)


def page(*blocks: Block) -> Page:
    return Page(index=0, width=100, height=100, origin=PageOrigin.NATIVE, blocks=blocks)


def para(text: str, block_type: BlockType = BlockType.PARAGRAPH, n: int = 0) -> Block:
    return Block(id=f"b{n}", type=block_type, text=text, origin_engine="t")


def lexicon_of(*texts: str) -> Lexicon:
    analyzer = LexiconAnalyzer()
    analyzer.observe(page(*(para(text, n=n) for n, text in enumerate(texts))))
    return analyzer.finalize()


def clean(text: str, *, also: tuple[str, ...] = (), languages: tuple[str, ...] = ("en",)) -> str:
    """Normalise ``text``; ``also`` is other text of the same document."""
    p = page(para(text))
    cleaner = TextNormalizationCleaner(languages)
    out = apply_decisions(p, cleaner.propose(p, lexicon_of(text, *also)), cleaner=cleaner.name)
    return out.blocks[0].text


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (f"de{FI}ne", "define"),
        (f"10{NBSP}km", "10 km"),
        (f"Bonjour{NNBSP}!", "Bonjour !"),
        ("one   two", "one two"),
        ("line   \nnext  ", "line\nnext"),
        (f"in{ZWSP}fo{SOFT_HYPHEN}rma", "informa"),
        (f"cafe{ACUTE}", "café"),
        ("already clean", "already clean"),
    ],
)
def test_universal_rules(text: str, expected: str) -> None:
    assert clean(text) == expected


def test_leading_indentation_is_left_alone() -> None:
    # The serializer decides what indentation means.
    assert clean("    indented") == "    indented"


def test_zero_width_joiner_stays() -> None:
    # Emoji sequences and some scripts need it.
    family = chr(0x1F468) + ZWJ + chr(0x1F469)
    assert clean(family) == family


def test_hyphen_joins_when_the_document_has_the_word() -> None:
    assert clean("the infor-\nmation", also=("more information",)) == "the information"


def test_compound_keeps_its_hyphen() -> None:
    assert clean("a well-\nknown fact", also=("well-known",)) == "a well-known fact"


def test_hyphen_stays_when_in_doubt() -> None:
    assert clean("the infor-\nmation") == "the infor-\nmation"


def test_soft_hyphen_at_line_end_always_joins() -> None:
    assert clean(f"infor{SOFT_HYPHEN}\nmation") == "information"


def test_elision_space_is_removed_in_italian_and_french() -> None:
    assert clean("dell' albero", languages=("it",)) == "dell'albero"
    assert clean("l" + chr(0x2019) + " arbre", languages=("fr",)) == "l" + chr(0x2019) + "arbre"


def test_elision_needs_the_language_and_a_known_word() -> None:
    assert clean("dell' albero") == "dell' albero"
    # "po'" is a truncation, not an elision: "un po' di" keeps its space.
    assert clean("un po' di", languages=("it",)) == "un po' di"
    # A closing quote is not an elision: quoted words keep their space.
    assert clean("'l' arbre", languages=("fr",)) == "'l' arbre"
    assert clean("the 'all' keyword", languages=("it",)) == "the 'all' keyword"
    assert clean("rock 'n' roll", languages=("fr",)) == "rock 'n' roll"


def test_unknown_language_is_refused() -> None:
    with pytest.raises(ValueError, match="no language pack"):
        TextNormalizationCleaner(("xx",))


@pytest.mark.parametrize("block_type", [BlockType.CODE, BlockType.FORMULA])
def test_code_and_formulas_are_left_alone(block_type: BlockType) -> None:
    p = page(para("x  =  1", block_type))
    assert TextNormalizationCleaner().propose(p, lexicon_of()) == []


def test_tables_and_removed_blocks_are_left_alone() -> None:
    table = Block(
        id="t",
        type=BlockType.TABLE,
        origin_engine="t",
        table=Table(n_rows=1, n_cols=1, cells=(TableCell(row=0, col=0, text="a  b"),)),
    )
    removed = para("a  b", n=1).mark_removed("c", "r")
    assert TextNormalizationCleaner().propose(page(table, removed), lexicon_of()) == []


def test_long_hostile_text_stays_fast() -> None:
    text = ("a" * 10_000 + "-\n") * 50 + "a"
    start = time.perf_counter()
    clean(text)
    assert time.perf_counter() - start < 2


_TEXT = st.text(
    alphabet=st.sampled_from(["a", "b", " ", "\n", "-", "'", NBSP, FI, ZWSP, ACUTE, "1"]),
    max_size=60,
)


@pytest.mark.invariant
@given(_TEXT, st.sampled_from([("en",), ("it",), ("fr", "de")]))
def test_normalisation_never_changes_what_a_reader_sees(
    text: str, languages: tuple[str, ...]
) -> None:
    """Principle 4: only spacing, equivalent forms and line-break hyphens change."""
    p = page(para(text))
    cleaner = TextNormalizationCleaner(languages)
    block = apply_decisions(p, cleaner.propose(p, lexicon_of(text)), cleaner=cleaner.name).blocks[0]
    joined = sum(1 for e in block.edits if e.kind == "hyphen_join")
    assert len(visible(block.text)) == len(visible(text)) - joined
    assert block.original_text() == text


def test_italian_contract_text_costs_fewer_tokens() -> None:
    text = (
        f"Il contratto dell' azienda prevede che l' importo sia{NBSP}versato entro "
        f"30{NBSP}giorni.   Le parti con-\ncordano. Le parti concordano{ZWSP} inoltre."
    )
    cleaned = clean(text, languages=("it",))
    assert cleaned.startswith("Il contratto dell'azienda prevede che l'importo sia versato")
    # Measured 40 -> 31 o200k_base tokens (-22%); fails below -15%.
    assert count_tokens(cleaned) <= count_tokens(text) * 0.85


@pytest.mark.parametrize("before", ["x" + chr(0xB2), chr(0x216B), "2024"])
def test_hyphen_after_a_non_letter_is_left_alone(before: str) -> None:
    # "²" and "Ⅻ" look like word characters to a regex but are not letters:
    # the cleaner must not propose a join the core refuses.
    text = f"{before}{SOFT_HYPHEN}\nfoo"
    assert visible(clean(text, also=(f"{before}foo",))) == visible(text)


def test_soft_hyphen_joins_after_a_decomposed_accent_or_twice() -> None:
    assert clean(f"e{ACUTE}{SOFT_HYPHEN}\nb") == "éb"
    assert clean(f"ab{SOFT_HYPHEN}{SOFT_HYPHEN}\ncd") == "abcd"


def test_composed_and_decomposed_spellings_vouch_for_each_other() -> None:
    assert clean("d" + chr(0xE9) + "cou-\npage", also=(f"de{ACUTE}coupage",)) == (
        "d" + chr(0xE9) + "coupage"
    )


def test_a_compound_vouches_for_its_parts() -> None:
    assert clean("infor-\nmation", also=("information-theoretic",)) == "information"


def test_compounds_written_with_unicode_hyphens_are_recognised() -> None:
    assert clean("well-\nknown", also=("well" + chr(0x2010) + "known",)) == "well-known"


def test_long_run_of_soft_hyphens_stays_fast() -> None:
    # Was quadratic: 40 000 soft hyphens took 26 s (security review).
    text = "a" + SOFT_HYPHEN * 200_000 + "b"
    start = time.perf_counter()
    clean(text)
    assert time.perf_counter() - start < 2


def test_block_needing_too_many_edits_is_left_alone() -> None:
    text = "a  " * 10_000
    assert clean(text) == text
