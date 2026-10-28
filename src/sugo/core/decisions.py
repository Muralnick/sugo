"""Cleaner proposals and how the core applies them (ADR-028, ADR-041).

Cleaners never change a page themselves: they return decisions, and only this
module turns them into changes. For now a decision can say one thing only:
"remove block X, for reason Y". Removal is soft: the block stays in the page,
marked with the cleaner's name and the reason (principle 3).

The core checks a cleaner's decisions as a whole before applying any of them.
If one is invalid, none is applied and the cleaner is reported, so a buggy
cleaner can never leave a page half-cleaned.

This contract is internal until the extension API exists; it is not exported
from ``sugo.api``.
"""

from collections import Counter
from collections.abc import Sequence

from sugo.core.models import NonEmptyStr, Page, _Model


class Decision(_Model):
    """A cleaner's proposal to remove one block of a page."""

    block_id: NonEmptyStr
    # Human-readable explanation, shown by preview and explain.
    reason: NonEmptyStr


class InvalidDecisionError(ValueError):
    """A cleaner proposed a change the core refuses to apply."""

    def __init__(self, cleaner: str, problem: str) -> None:
        super().__init__(f"cleaner {cleaner!r} proposed an invalid decision: {problem}")
        self.cleaner = cleaner


def apply_decisions(page: Page, decisions: Sequence[Decision], *, cleaner: str) -> Page:
    """Return a copy of the page with the decisions of one cleaner applied.

    The cleaner's name is recorded as ``removed_by`` from the caller, never
    from the decisions. It is only as trustworthy as the caller: once the
    extension API exists, the core will take it from the extension registry.

    Args:
        page: The page the cleaner examined.
        decisions: What the cleaner proposed for that page.
        cleaner: Name of the cleaner, recorded on every block it removes.

    Raises:
        InvalidDecisionError: If a decision names a block that is not on the
            page or is already removed, or two decisions name the same block.
            Nothing is applied in that case.
    """
    if not cleaner:
        raise ValueError("cleaner name must not be empty")
    # Read once: a generator would be empty on the second pass, and its
    # decisions would be validated but silently not applied.
    decisions = tuple(decisions)
    if not decisions:
        return page
    blocks = {block.id: block for block in page.blocks}
    counts = Counter(decision.block_id for decision in decisions)
    # Block ids may be document text in the future, so errors name the problem
    # and leave the ids out (principle 11).
    duplicates = sum(1 for count in counts.values() if count > 1)
    if duplicates:
        raise InvalidDecisionError(cleaner, f"{duplicates} block(s) named more than once")
    unknown = sum(1 for block_id in counts if block_id not in blocks)
    if unknown:
        raise InvalidDecisionError(cleaner, f"{unknown} block(s) not on the page")
    already_removed = sum(1 for block_id in counts if blocks[block_id].removed)
    if already_removed:
        raise InvalidDecisionError(cleaner, f"{already_removed} block(s) already removed")

    reasons = {decision.block_id: decision.reason for decision in decisions}
    return Page.model_validate(
        {
            **page.model_dump(exclude={"blocks"}),
            "blocks": tuple(
                block.mark_removed(cleaner, reasons[block.id]) if block.id in reasons else block
                for block in page.blocks
            ),
        }
    )
