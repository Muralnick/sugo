"""Remove text a reader cannot see on the page: white on white, microscopic,
off the page, drawn invisible, or the unverified text layer of a scan.

Hidden text is a classic way to slip instructions to an LLM that no person
reviewing the document would notice. The PDF extractor flags such text
``hidden`` and keeps it apart from visible text (ADR-043); this cleaner only
proposes to remove those blocks, and the core applies the removal as a soft
deletion with the reason below (principle 3). The text stays in the IR, so
preview and explain can still show what was hidden.
"""

from typing import ClassVar

from sugo.core.decisions import Decision
from sugo.core.models import BlockFlag, Page

REASON = "text not visible on the rendered page (hidden, invisible or an unverified text layer)"


class HiddenTextCleaner:
    """Proposes the removal of every hidden block still present on a page."""

    name: ClassVar[str] = "hidden_text"

    def propose(self, page: Page, stats: object = None) -> list[Decision]:
        """Return one removal decision per hidden block not yet removed.

        ``stats`` is part of the cleaner contract and unused here: this
        cleaner needs no document-wide context.
        """
        return [
            Decision(block_id=block.id, reason=REASON)
            for block in page.blocks
            if BlockFlag.HIDDEN in block.flags and not block.removed
        ]
