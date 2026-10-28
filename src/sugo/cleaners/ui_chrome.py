"""Remove screenshot interface noise: status-bar items and lone icon misreads.

The image detectors type such text ``ui_chrome`` (ADR-040); this cleaner only
proposes to remove those blocks, and the core applies the removal as a soft
deletion with the reason below (principle 3). The text stays in the IR, so
preview and explain can still show it.
"""

from typing import ClassVar

from sugo.core.decisions import Decision
from sugo.core.models import BlockType, Page

REASON = "screenshot interface element (status bar or icon), not document content"


class UiChromeCleaner:
    """Proposes the removal of every UI chrome block still present on a page."""

    name: ClassVar[str] = "ui_chrome"

    def propose(self, page: Page) -> list[Decision]:
        """Return one removal decision per UI chrome block not yet removed."""
        return [
            Decision(block_id=block.id, reason=REASON)
            for block in page.blocks
            if block.type is BlockType.UI_CHROME and not block.removed
        ]
