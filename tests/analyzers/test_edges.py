"""Tests for the edge analyzer: which texts count as running headers and page numbers."""

import pytest

from sugo.analyzers.edges import (
    Band,
    EdgeAnalyzer,
    EdgeStats,
    NumberRule,
    NumberSystem,
    edge_texts,
)
from sugo.core.constants import MAX_EDGE_BLOCKS_PER_BAND, MAX_EDGE_TEXT_CHARS
from sugo.core.models import BBox, Block, BlockFlag, BlockType, Page, PageOrigin

TOP = BBox(x0=0.1, y0=0.03, x1=0.9, y1=0.06)
MIDDLE = BBox(x0=0.1, y0=0.4, x1=0.9, y1=0.45)
BOTTOM = BBox(x0=0.1, y0=0.94, x1=0.9, y1=0.97)


def block(
    block_id: str,
    text: str,
    bbox: BBox | None = BOTTOM,
    *flags: BlockFlag,
    kind: BlockType = BlockType.PARAGRAPH,
) -> Block:
    return Block(id=block_id, type=kind, text=text, bbox=bbox, origin_engine="t", flags=flags)


def page(index: int, *blocks: Block) -> Page:
    return Page(index=index, width=595, height=842, origin=PageOrigin.NATIVE, blocks=blocks)


def analyze(*pages: Page) -> EdgeStats:
    analyzer = EdgeAnalyzer()
    for p in pages:
        analyzer.observe(p)
    return analyzer.finalize()


def repeated(stats: EdgeStats, p: Page) -> list[str]:
    """Ids of the blocks of ``p`` that are copies of a running header or footer."""
    return [t.block_id for t in edge_texts(p) if stats.repeated_edge(t, p.index) is not None]


def numbered(stats: EdgeStats, p: Page) -> list[str]:
    return [t.block_id for t in edge_texts(p) if stats.is_page_number(t, p.index)]


def test_edge_texts_reads_only_visible_text_blocks_in_the_bands() -> None:
    p = page(
        0,
        block("top", "Title", TOP),
        block("middle", "Body", MIDDLE),
        block("bottom", "Footer"),
        block("no-box", "Footer", None),
        block("blank", "   "),
        block("hidden", "Footer", BOTTOM, BlockFlag.HIDDEN),
        block("suspicious", "Footer", BOTTOM, BlockFlag.SUSPICIOUS_INSTRUCTION),
        block("removed", "Footer").mark_removed("other", "r"),
        block("code", "x = 1", kind=BlockType.CODE),
        block("heading", "Part II", TOP, kind=BlockType.HEADING),
        block("long", "word " * MAX_EDGE_TEXT_CHARS),
    )
    assert [(t.block_id, t.band) for t in edge_texts(p)] == [
        ("top", Band.TOP),
        ("bottom", Band.BOTTOM),
    ]


def test_edge_texts_caps_blocks_per_band_nearest_the_edge_first() -> None:
    blocks = [
        block(f"b{n:03}", f"note {n}", BBox(x0=0.1, y0=0.9 + n * 0.0001, x1=0.2, y1=0.91))
        for n in range(100)
    ]
    texts = edge_texts(page(0, *blocks))
    assert len(texts) == MAX_EDGE_BLOCKS_PER_BAND
    # Nearest the bottom edge means the largest y1, then the id; all share y1 here.
    assert [t.block_id for t in texts] == [f"b{n:03}" for n in range(MAX_EDGE_BLOCKS_PER_BAND)]


def test_running_header_on_every_page_is_repeated() -> None:
    pages = [
        page(i, block("h", "ACME  Annual Report", TOP), block("b", f"Body {i}", MIDDLE))
        for i in range(4)
    ]
    stats = analyze(*pages)
    assert [repeated(stats, p) for p in pages] == [["h"]] * 4


def test_normalisation_ignores_case_spacing_and_width() -> None:
    # The last one spells "Annual" in fullwidth letters.
    texts = ["Annual Report", "ANNUAL  REPORT", "\uff21\uff4e\uff4e\uff55\uff41\uff4c Report"]
    pages = [page(i, block("h", text, TOP)) for i, text in enumerate(texts)]
    stats = analyze(*pages)
    assert [repeated(stats, p) for p in pages] == [["h"]] * 3


def test_text_on_two_pages_is_not_repeated() -> None:
    pages = [page(i, block("f", "Draft")) for i in range(2)]
    assert analyze(*pages).repeated == {}


def test_text_recurring_far_apart_is_not_repeated() -> None:
    # Three pages out of a hundred: a heading that recurs, not a running header.
    pages = [page(i, block("h", "Summary", TOP)) for i in (0, 50, 99)]
    assert analyze(*pages).repeated == {}


def test_header_on_every_other_page_is_repeated() -> None:
    pages = [page(i, block("h", "Book Title" if i % 2 else "Chapter One", TOP)) for i in range(8)]
    stats = analyze(*pages)
    assert all(repeated(stats, p) == ["h"] for p in pages)


def test_same_text_in_the_other_band_is_a_different_pattern() -> None:
    pages = [
        page(0, block("a", "Draft", TOP)),
        page(1, block("a", "Draft")),
        page(2, block("a", "Draft")),
    ]
    assert analyze(*pages).repeated == {}


def test_numbers_following_the_page_index_are_repeated() -> None:
    pages = [page(i, block("f", f"ACME 2026 - sheet {i + 1}")) for i in range(5)]
    stats = analyze(*pages)
    assert all(repeated(stats, p) == ["f"] for p in pages)
    (edge,) = stats.repeated.values()
    assert edge.numbers == (
        NumberRule(constant=2026),
        NumberRule(offset=1),
    )


def test_numbers_neither_constant_nor_following_pages_are_not_repeated() -> None:
    # "Section 3" at the top of consecutive pages is a heading, not a header.
    pages = [page(i, block("h", f"Section {n}", TOP)) for i, n in enumerate((3, 7, 9, 12))]
    assert analyze(*pages).repeated == {}


def test_one_disagreeing_copy_cancels_the_pattern() -> None:
    texts = ["Rev 2", "Rev 2", "Rev 3", "Rev 2"]
    pages = [page(i, block("f", text)) for i, text in enumerate(texts)]
    assert analyze(*pages).repeated == {}


def test_copy_with_another_number_on_a_new_page_does_not_match() -> None:
    stats = analyze(*(page(i, block("f", "Rev 2")) for i in range(3)))
    assert repeated(stats, page(3, block("f", "Rev 5"))) == []
    assert repeated(stats, page(3, block("f", "Rev 2"))) == ["f"]


def test_hidden_copies_cannot_make_a_visible_clause_repeat() -> None:
    clause = "The buyer may cancel at any time without penalty"
    pages = [page(0, block("c", clause))] + [
        page(i, block("c", clause, BOTTOM, BlockFlag.HIDDEN)) for i in range(1, 6)
    ]
    stats = analyze(*pages)
    assert stats.repeated == {}
    assert repeated(stats, pages[0]) == []


def test_substantive_text_is_marked_with_its_first_page() -> None:
    clause = "Payment is due within 30 days"
    stats = analyze(*(page(i, block("c", clause)) for i in (5, 3, 4)))
    (edge,) = stats.repeated.values()
    assert (edge.pages, edge.first_page, edge.substantive) == (3, 3, True)
    short = analyze(*(page(i, block("c", "Confidential")) for i in range(3)))
    assert [e.substantive for e in short.repeated.values()] == [False]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("7", (NumberSystem.ARABIC, 7)),
        ("- 7 -", (NumberSystem.ARABIC, 7)),
        ("Page 7 of 90", (NumberSystem.ARABIC, 7)),
        ("p. 7", (NumberSystem.ARABIC, 7)),
        ("Pagina 7 di 90", (NumberSystem.ARABIC, 7)),
        ("Seite 7/90", (NumberSystem.ARABIC, 7)),
        ("[7]", (NumberSystem.ARABIC, 7)),
        ("xiv", (NumberSystem.ROMAN, 14)),
        ("IV", (NumberSystem.ROMAN, 4)),
        ("mcmxcix", (NumberSystem.ROMAN, 1999)),
        ("iiii", None),
        ("Chapter 7", None),
        ("7 apples", None),
        ("1" * MAX_EDGE_TEXT_CHARS, None),
        ("Page " + "9" * 20, None),
    ],
)
def test_page_number_forms(text: str, expected: tuple[NumberSystem, int] | None) -> None:
    (found,) = edge_texts(page(0, block("n", text)))
    assert found.page_number == expected


def test_page_numbers_following_the_pages_are_found() -> None:
    pages = [page(i, block("n", str(i + 1))) for i in range(4)]
    stats = analyze(*pages)
    assert [numbered(stats, p) for p in pages] == [["n"]] * 4
    # A number out of sequence on a later page is left alone.
    assert numbered(stats, page(9, block("n", "3"))) == []


def test_roman_front_matter_and_arabic_body_are_separate_sequences() -> None:
    labels = ["i", "ii", "iii", "1", "2", "3", "4"]
    pages = [page(i, block("n", label)) for i, label in enumerate(labels)]
    stats = analyze(*pages)
    assert all(numbered(stats, p) == ["n"] for p in pages)


def test_the_same_number_on_every_page_is_not_a_page_number() -> None:
    pages = [page(i, block("n", "5")) for i in range(5)]
    stats = analyze(*pages)
    assert stats.page_numbers == frozenset()
    # Nor is it treated as a running footer: page-number-like text is left
    # to the page number rules alone.
    assert stats.repeated == {}


def test_too_few_page_numbers_are_not_a_sequence() -> None:
    assert analyze(page(0, block("n", "1")), page(1, block("n", "2"))).page_numbers == frozenset()


def test_statistics_do_not_depend_on_page_order() -> None:
    pages = [
        page(i, block("h", "Report", TOP), block("f", f"Draft {i + 10}"), block("n", str(i + 1)))
        for i in range(6)
    ]
    assert analyze(*pages) == analyze(*reversed(pages))


def test_observing_a_page_twice_is_refused() -> None:
    analyzer = EdgeAnalyzer()
    analyzer.observe(page(0))
    with pytest.raises(ValueError, match="observed twice"):
        analyzer.observe(page(0))


def test_headings_at_the_top_of_pages_are_never_edge_text() -> None:
    # Part numerals and numbered headings, one per page, look like page
    # numbers and running headers; headings are content and stay.
    pages = [
        page(
            i,
            block("h", label, TOP, kind=BlockType.HEADING),
            block("x", f"Exercise {i + 1}", TOP, kind=BlockType.HEADING),
        )
        for i, label in enumerate(["I", "II", "III"])
    ]
    stats = analyze(*pages)
    assert (stats.repeated, stats.page_numbers) == ({}, frozenset())


def test_hash_signs_and_digits_never_share_a_pattern() -> None:
    # Masking digits with "#" once made these one pattern with different
    # counts of numbers, and finalize() crashed.
    pages = [page(i, block("f", text)) for i, text in enumerate(["Ref # 1", "Ref 1 1", "Ref # #"])]
    assert analyze(*pages).repeated == {}


def test_statistics_hold_no_long_digit_strings() -> None:
    account = "Account 123456789012"
    stats = analyze(*(page(i, block("f", account)) for i in range(3)))
    (edge,) = stats.repeated.values()
    (rule,) = edge.numbers
    assert isinstance(rule.constant, bytes)
    assert b"123456789012" not in rule.constant
    assert repeated(stats, page(3, block("f", account))) == ["f"]
    assert repeated(stats, page(3, block("f", "Account 123456789013"))) == []


@pytest.mark.parametrize(
    "clause",
    [
        "供应商对延误造成的所有损失承担责任",  # Chinese liability clause
        "ผู้ขายต้องรับผิดชอบต่อความเสียหายทั้งหมดที่เกิดจากความล่าช้า",  # Thai, no spaces
        "The\u3164buyer\u3164waives\u3164all\u3164refund\u3164rights\u3164forever",
    ],
)
def test_clauses_without_spaces_are_substantive(clause: str) -> None:
    stats = analyze(*(page(i, block("c", clause)) for i in range(3)))
    assert [e.substantive for e in stats.repeated.values()] == [True]


def test_substantive_text_with_changing_numbers_is_not_repeated() -> None:
    # Later copies would not be identical to the kept one: their figures differ.
    texts = [f"Late fee in month {i + 1} is {i + 2} percent of the price" for i in range(4)]
    assert analyze(*(page(i, block("f", text)) for i, text in enumerate(texts))).repeated == {}
