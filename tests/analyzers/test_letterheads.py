"""Tests for sugo.analyzers.letterheads and the removal of letterhead copies (ADR-064)."""

from sugo.analyzers.edges import EdgeAnalyzer, EdgeStats
from sugo.cleaners.headers_footers import HeaderFooterCleaner
from sugo.core.models import BBox, Block, BlockFlag, BlockType, Page, PageOrigin, Style

SMALL, BODY = 14.0, 40.0  # line heights in pixels, as the OCR layout records them

# The same letterhead captions, read with different OCR errors on each page.
CAPTIONS = (
    "Regional Training Consortium / Technical Institute of Industry",
    "Regonal Trainig Consortum / Technlcal Institute of lndustry",
    "Regional Traininq Consortium / Technical lnstitute of Industy",
    "Reglonal Training Consortiurn / Technical Institute af Industry",
)
BODY_TEXT = (
    "The meeting took place on 31 March 2026 by video call, and the committee examined the "
    "applications received within the deadline set by the call."
)


def block(
    block_id: str,
    text: str,
    y0: float,
    y1: float,
    *,
    size: float = BODY,
    flags: tuple[BlockFlag, ...] = (),
) -> Block:
    return Block(
        id=block_id,
        type=BlockType.PARAGRAPH,
        text=text,
        bbox=BBox(x0=0.1, y0=y0, x1=0.9, y1=y1),
        style=Style(font_size=size),
        origin_engine="t",
        flags=flags,
    )


def page(
    index: int, *blocks: Block, origin: PageOrigin = PageOrigin.OCR, letterhead: str | None = None
) -> Page:
    head = () if letterhead is None else (block("head", letterhead, 0.04, 0.12, size=SMALL),)
    body = block("body", f"{BODY_TEXT} Page {index + 1}.", 0.25, 0.6)
    return Page(index=index, width=1654, height=2339, origin=origin, blocks=(*head, *blocks, body))


def analyze(*pages: Page) -> EdgeStats:
    analyzer = EdgeAnalyzer(b"document digest")
    for p in pages:
        analyzer.observe(p)
    return analyzer.finalize()


def removed(stats: EdgeStats, p: Page) -> list[str]:
    return [decision.block_id for decision in HeaderFooterCleaner().propose(p, stats)]


def letterhead_pages(count: int = 4) -> list[Page]:
    return [page(n, letterhead=CAPTIONS[n % len(CAPTIONS)]) for n in range(count)]


def test_later_copies_of_a_scanned_letterhead_are_removed_and_the_first_kept() -> None:
    pages = letterhead_pages()
    stats = analyze(*pages)
    assert removed(stats, pages[0]) == []
    for p in pages[1:]:
        assert removed(stats, p) == ["head"]


def test_the_reason_says_where_the_first_copy_is() -> None:
    pages = letterhead_pages()
    decision = HeaderFooterCleaner().propose(pages[2], analyze(*pages))[0]
    assert "letterhead repeated on 4 nearby pages" in decision.reason
    assert "first copy kept on page 1" in decision.reason


def test_two_pages_are_not_enough() -> None:
    pages = letterhead_pages(2)
    stats = analyze(*pages)
    assert all(removed(stats, p) == [] for p in pages)


def test_body_size_text_at_the_top_is_never_matched() -> None:
    # Repeated in part from page to page, but set at body size: content.
    pages = [
        page(n, block("intro", f"Article {n + 1}. {BODY_TEXT}", 0.04, 0.12, size=BODY))
        for n in range(4)
    ]
    stats = analyze(*pages)
    assert all(removed(stats, p) == [] for p in pages)


def test_small_text_at_the_bottom_is_never_matched() -> None:
    # Footnotes: small print, alike on every page, but content.
    pages = [
        page(n, block("note", f"See the annex for the rules on item {n}.", 0.9, 0.96, size=SMALL))
        for n in range(4)
    ]
    stats = analyze(*pages)
    assert all(removed(stats, p) == [] for p in pages)


def test_native_pages_are_left_to_exact_matching() -> None:
    pages = [
        page(n, origin=PageOrigin.NATIVE, letterhead=CAPTIONS[n % len(CAPTIONS)]) for n in range(4)
    ]
    stats = analyze(*pages)
    assert stats.letterheads == {}


def test_flagged_blocks_are_never_matched() -> None:
    # Hidden copies of a caption must not make a visible one look repeated.
    pages = [
        page(n, block("logo", CAPTIONS[0], 0.04, 0.12, size=SMALL, flags=(BlockFlag.HIDDEN,)))
        for n in range(4)
    ]
    stats = analyze(*pages)
    assert stats.letterheads == {}


def test_the_result_does_not_depend_on_page_order() -> None:
    pages = letterhead_pages(5)
    assert analyze(*pages) == analyze(*reversed(pages))
    assert analyze(*pages).digest() == analyze(*reversed(pages)).digest()


def test_letterheads_change_the_statistics_digest() -> None:
    with_letterhead = analyze(*letterhead_pages())
    without = analyze(*[page(n) for n in range(4)])
    assert with_letterhead.digest() != without.digest()
