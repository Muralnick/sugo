"""Remove running headers and footers: text repeated at the same page edge.

The edge analyzer finds which edge texts repeat across the document; this
cleaner proposes to remove each copy on a page, and the core applies the
removal as a soft deletion with a reason (principle 3, ADR-041).

Short boilerplate ("Annual Report 2026", "Confidential") goes from every
page. Longer text may be a clause someone repeated on every page so that it
would be dropped as a footer (THREAT_MODEL C): its first copy is kept, and
only the later identical copies go, so no content leaves the output.
"""

from typing import ClassVar

from sugo.analyzers.edges import Band, EdgeStats, edge_texts
from sugo.core.decisions import Decision
from sugo.core.models import Page

_NAMES = {Band.TOP: "header", Band.BOTTOM: "footer"}


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
        return decisions
