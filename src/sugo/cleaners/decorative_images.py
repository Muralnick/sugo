"""Remove decorative pictures: bullets, rules and icons too small to hold content.

The Office reader flags a picture under 32 x 32 pixels ``decorative``
(ADR-054); this cleaner only proposes to remove those blocks, and the core
applies the removal as a soft deletion with the reason below (principle 3).
"""

from typing import ClassVar

from sugo.core.decisions import Decision
from sugo.core.models import BlockFlag, Page

REASON = "decorative picture under 32 x 32 pixels, too small to hold content"


class DecorativeImageCleaner:
    """Proposes the removal of every decorative picture still present on a page."""

    name: ClassVar[str] = "decorative_images"

    def propose(self, page: Page, stats: object = None) -> list[Decision]:
        """Return one removal decision per decorative block not yet removed.

        ``stats`` is part of the cleaner contract and unused here: this
        cleaner needs no document-wide context.
        """
        return [
            Decision(block_id=block.id, reason=REASON)
            for block in page.blocks
            if BlockFlag.DECORATIVE in block.flags and not block.removed
        ]
