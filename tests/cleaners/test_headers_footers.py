"""Tests for the header, footer and page number cleaners, alone and after the PDF extractor."""

import pymupdf

from sugo.analyzers.edges import EdgeAnalyzer, EdgeStats
from sugo.cleaners.headers_footers import HeaderFooterCleaner
from sugo.cleaners.hidden_text import HiddenTextCleaner
from sugo.cleaners.page_numbers import REASON, PageNumberCleaner
from sugo.core.decisions import Decision, apply_decisions
from sugo.core.models import BBox, Block, BlockFlag, BlockType, Page, PageOrigin
from sugo.extractors.pymupdf.extract import extract_pdf
from sugo.metrics.tokenizer import count_tokens
from sugo.serializers.markdown import render

TOP = BBox(x0=0.1, y0=0.03, x1=0.9, y1=0.06)
MIDDLE = BBox(x0=0.1, y0=0.4, x1=0.9, y1=0.45)
BOTTOM = BBox(x0=0.1, y0=0.94, x1=0.9, y1=0.97)
CLAUSE = "The supplier is liable for all damages caused by delays"


def block(block_id: str, text: str, bbox: BBox = BOTTOM, *flags: BlockFlag) -> Block:
    return Block(
        id=block_id, type=BlockType.PARAGRAPH, text=text, bbox=bbox, origin_engine="t", flags=flags
    )


def page(index: int, *blocks: Block) -> Page:
    return Page(index=index, width=595, height=842, origin=PageOrigin.NATIVE, blocks=blocks)


def analyze(pages: list[Page]) -> EdgeStats:
    analyzer = EdgeAnalyzer()
    for p in pages:
        analyzer.observe(p)
    return analyzer.finalize()


def clean(pages: list[Page]) -> list[Page]:
    """The step 5 cleaning order: hidden text, page numbers, then headers and footers."""
    stats = analyze(pages)
    out = []
    for p in pages:
        hidden = HiddenTextCleaner()
        p = apply_decisions(p, hidden.propose(p), cleaner=hidden.name)
        for cleaner in (PageNumberCleaner(), HeaderFooterCleaner()):
            p = apply_decisions(p, cleaner.propose(p, stats), cleaner=cleaner.name)
        out.append(p)
    return out


def test_short_running_header_is_removed_from_every_page() -> None:
    pages = [
        page(i, block("h", "ACME Annual Report", TOP), block("b", f"Body {i}", MIDDLE))
        for i in range(3)
    ]
    stats = analyze(pages)
    assert [HeaderFooterCleaner().propose(p, stats) for p in pages] == [
        [Decision(block_id="h", reason="running header repeated on 3 pages")]
    ] * 3


def test_substantive_footer_keeps_its_first_copy() -> None:
    pages = [page(i, block("c", CLAUSE)) for i in range(4)]
    stats = analyze(pages)
    proposals = [HeaderFooterCleaner().propose(p, stats) for p in pages]
    assert proposals[0] == []
    reason = "running footer repeated on 4 pages; first copy kept on page 1"
    assert proposals[1:] == [[Decision(block_id="c", reason=reason)]] * 3


def test_header_cleaner_leaves_page_numbers_to_their_cleaner() -> None:
    pages = [page(i, block("n", f"Page {i + 1} of 3")) for i in range(3)]
    stats = analyze(pages)
    assert [HeaderFooterCleaner().propose(p, stats) for p in pages] == [[]] * 3
    assert [PageNumberCleaner().propose(p, stats) for p in pages] == [
        [Decision(block_id="n", reason=REASON)]
    ] * 3


def test_cleaners_skip_blocks_already_removed() -> None:
    pages = [page(i, block("h", "Report", TOP), block("n", str(i + 1))) for i in range(3)]
    stats = analyze(pages)
    gone = page(1, *(b.mark_removed("other", "r") for b in pages[1].blocks))
    assert HeaderFooterCleaner().propose(gone, stats) == []
    assert PageNumberCleaner().propose(gone, stats) == []


def test_clause_with_hidden_copies_stays() -> None:
    pages = [page(0, block("c", CLAUSE))] + [
        page(i, block("c", CLAUSE, BOTTOM, BlockFlag.HIDDEN)) for i in range(1, 5)
    ]
    cleaned = clean(pages)
    assert not cleaned[0].blocks[0].removed
    assert all(p.blocks[0].removed_by == "hidden_text" for p in cleaned[1:])


def _report(pages: int) -> bytes:
    """A short report: running header, a long footer clause and page numbers."""
    document = pymupdf.open()
    for n in range(pages):
        p = document.new_page()
        p.insert_text((72, 40), "ACME Corporation - Annual Report 2026", fontsize=9)
        body = [f"Section {n + 1} discusses topic number {n + 1} of the annual report."]
        body += [
            f"Line {k} of the body text on this page, distinct from the others." for k in range(3)
        ]
        for row, line in enumerate(body):
            p.insert_text((72, 120 + row * 18), line, fontsize=11)
        p.insert_text((72, 780), CLAUSE + ".", fontsize=8)
        p.insert_text((290, 815), str(n + 1), fontsize=9)
    return document.tobytes()


def test_pdf_report_loses_only_its_page_furniture() -> None:
    extracted = list(extract_pdf(_report(5)))
    cleaned = clean(extracted)

    removed = [(p.index, b.removed_by, b.text) for p in cleaned for b in p.blocks if b.removed]
    assert [(i, text) for i, by, text in removed if by == "page_numbers"] == [
        (i, str(i + 1)) for i in range(5)
    ]
    headers = [i for i, by, text in removed if by == "headers_footers" and "Report" in text]
    assert headers == list(range(5))
    # The clause stays once, on the first page (THREAT_MODEL C).
    kept = [render([b for b in p.blocks if not b.removed]) for p in cleaned]
    assert [CLAUSE in text for text in kept] == [True, False, False, False, False]
    assert all(f"Section {i + 1} discusses" in text for i, text in enumerate(kept))

    before = count_tokens("\n\n".join(render(p.blocks) for p in extracted))
    after = count_tokens("\n\n".join(kept))
    # Measured 419 -> 316 tokens (ADR-044); the gate leaves room for layout changes.
    assert after <= 0.8 * before, (before, after)
