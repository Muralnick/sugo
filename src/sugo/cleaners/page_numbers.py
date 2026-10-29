"""Remove page numbers that follow the page sequence of the document.

A lone "7" at the bottom of a page is a page number only if the pages
around it carry 6 and 8 in the same place; the edge analyzer checks that.
This cleaner proposes to remove those numbers, and the core applies the
removal as a soft deletion with the reason below (principle 3, ADR-041).
"""

from typing import ClassVar

from sugo.analyzers.edges import EdgeStats, edge_texts
from sugo.core.decisions import Decision
from sugo.core.models import Page

REASON = "page number"


class PageNumberCleaner:
    """Proposes the removal of the page number printed on a page."""

    name: ClassVar[str] = "page_numbers"

    def propose(self, page: Page, stats: EdgeStats) -> list[Decision]:
        """Return one removal decision per page number in the document's sequence."""
        return [
            Decision(block_id=text.block_id, reason=REASON)
            for text in edge_texts(page)
            if stats.is_page_number(text, page.index)
        ]
