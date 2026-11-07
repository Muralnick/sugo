"""Remove running headers and footers: text repeated at the same page edge.

The edge analyzer finds which edge texts repeat across the document; this
cleaner proposes to remove each copy on a page, and the core applies the
removal as a soft deletion with a reason (principle 3, ADR-041).

Short boilerplate ("Annual Report 2026", "Confidential") goes from every
page. Longer text may be a clause someone repeated on every page so that it
would be dropped as a footer (THREAT_MODEL C): its first copy is kept, and
only the later identical copies go, so no content leaves the output.

Scanned letterheads are read with different OCR errors on each page, so
they are matched by similar text instead (ADR-064): their first copy always
stays, and only the later copies go.

Headers and footers a document declares itself, such as Word's, have no
place on the page and appear once per section: the first copy stays, even a
short one, which may say what the document is ("DRAFT"), and the identical
copies of later sections go (ADR-054).
"""

from typing import ClassVar

from sugo.analyzers.edges import Band, EdgeStats, declared_texts, edge_texts
from sugo.core.decisions import Decision
from sugo.core.models import BlockType, Page

_NAMES = {Band.TOP: "header", Band.BOTTOM: "footer"}
_DECLARED = {
    BlockType.HEADER: "running header declared by the document",
    BlockType.FOOTER: "running footer declared by the document",
}


class HeaderFooterCleaner:
    """Proposes the removal of running headers and footers on a page."""

    name: ClassVar[str] = "headers_footers"

    def propose(self, page: Page, stats: EdgeStats) -> list[Decision]:
        """Return one removal decision per copy of a running header or footer."""
        decisions = []
        for text in edge_texts(page):
            if text.page_number is not None:
                continue  # Left to the page number cleaner.
            repeated = stats.repeated_edge(text, page.index)
            if repeated is None:
                continue
            reason = f"running {_NAMES[text.band]} repeated on {repeated.pages} pages"
            if repeated.substantive:
                if page.index == repeated.first_page:
                    continue
                reason += f"; first copy kept on page {repeated.first_page + 1}"
            decisions.append(Decision(block_id=text.block_id, reason=reason))
        decided = {decision.block_id for decision in decisions}
        for block in page.blocks:
            letterhead = stats.letterhead(page.index, block.id)
            if letterhead is None or block.id in decided:
                continue
            reason = (
                f"letterhead repeated on {letterhead.pages} nearby pages (similar text read"
                f" with OCR); first copy kept on page {letterhead.first_page + 1}"
            )
            decisions.append(Decision(block_id=block.id, reason=reason))
        for declared in declared_texts(page):
            first = stats.first_declared(declared)
            if declared.type in _DECLARED and first is not None and first < page.index:
                reason = f"{_DECLARED[declared.type]}; first copy kept on page {first + 1}"
                decisions.append(Decision(block_id=declared.block_id, reason=reason))
        return decisions
