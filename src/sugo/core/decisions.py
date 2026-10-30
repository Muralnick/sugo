"""Cleaner proposals and how the core applies them (ADR-028, ADR-041, ADR-050).

Cleaners never change a page themselves: they return decisions, and only this
module turns them into changes. A decision says one of two things:

- ``Decision``: remove block X, for reason Y. Removal is soft: the block stays
  in the page, marked with the cleaner's name and the reason (principle 3).
- ``EditDecision``: replace a span of block X's text, for reason Y. The core
  accepts only three kinds of edit, each checked mechanically here (deletion,
  normalisation that keeps every visible character, line-break hyphen join),
  and records every edit on the block, so it can be inspected and undone
  (principles 3 and 4).

The core checks a cleaner's decisions as a whole before applying any of them.
If one is invalid, none is applied and the cleaner is reported, so a buggy
cleaner can never leave a page half-cleaned.

This contract is internal until the extension API exists; it is not exported
from ``sugo.api``.
"""

import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from typing import Annotated

from pydantic import Field

from sugo.core.constants import MAX_EDITS_PER_BLOCK, MAX_EDITS_PER_PAGE
from sugo.core.models import Block, EditKind, NonEmptyStr, Page, TextEdit, _Model
from sugo.core.text import (
    APOSTROPHES,
    COMPOUND_HYPHENS,
    HYPHEN_BREAK,
    canonical,
    is_letter,
    visible,
)


class Decision(_Model):
    """A cleaner's proposal to remove one block of a page."""

    block_id: NonEmptyStr
    # Human-readable explanation, shown by preview and explain.
    reason: NonEmptyStr


class EditDecision(_Model):
    """A cleaner's proposal to replace ``text[start:end]`` of one block."""

    block_id: NonEmptyStr
    start: Annotated[int, Field(ge=0)]
    end: Annotated[int, Field(ge=0)]
    replacement: str
    kind: EditKind
    reason: NonEmptyStr


Proposal = Decision | EditDecision


class InvalidDecisionError(ValueError):
    """A cleaner proposed a change the core refuses to apply."""

    def __init__(self, cleaner: str, problem: str) -> None:
        super().__init__(f"cleaner {cleaner!r} proposed an invalid decision: {problem}")
        self.cleaner = cleaner


def apply_decisions(page: Page, decisions: Sequence[Proposal], *, cleaner: str) -> Page:
    """Return a copy of the page with the decisions of one cleaner applied.

    The cleaner's name is recorded as ``removed_by`` or ``edited_by`` from the
    caller, never from the decisions. It is only as trustworthy as the caller:
    once the extension API exists, the core will take it from the extension
    registry.

    Args:
        page: The page the cleaner examined.
        decisions: What the cleaner proposed for that page.
        cleaner: Name of the cleaner, recorded on every block it changes.

    Raises:
        InvalidDecisionError: If a decision names a block that is not on the
            page or is already removed, a block is both removed and edited or
            removed twice, or an edit is out of range, overlaps another or is
            not of the kind it claims. Nothing is applied in that case.
    """
    if not cleaner:
        raise ValueError("cleaner name must not be empty")
    # Read once: a generator would be empty on the second pass, and its
    # decisions would be validated but silently not applied.
    decisions = tuple(decisions)
    if not decisions:
        return page
    blocks = {block.id: block for block in page.blocks}
    removals = [decision for decision in decisions if isinstance(decision, Decision)]
    edits: defaultdict[str, list[EditDecision]] = defaultdict(list)
    for decision in decisions:
        if isinstance(decision, EditDecision):
            edits[decision.block_id].append(decision)

    # Block ids may be document text in the future, so errors name the problem
    # and leave the ids out (principle 11).
    counts = Counter(decision.block_id for decision in removals)
    duplicates = sum(1 for count in counts.values() if count > 1)
    if duplicates:
        raise InvalidDecisionError(cleaner, f"{duplicates} block(s) named more than once")
    named = set(counts) | set(edits)
    unknown = sum(1 for block_id in named if block_id not in blocks)
    if unknown:
        raise InvalidDecisionError(cleaner, f"{unknown} block(s) not on the page")
    already_removed = sum(1 for block_id in named if blocks[block_id].removed)
    if already_removed:
        raise InvalidDecisionError(cleaner, f"{already_removed} block(s) already removed")
    both = sum(1 for block_id in counts if block_id in edits)
    if both:
        raise InvalidDecisionError(cleaner, f"{both} block(s) both removed and edited")
    # Each cleaner edits a block once: its edits are undone as one batch.
    again = sum(
        1 for block_id in edits if any(e.edited_by == cleaner for e in blocks[block_id].edits)
    )
    if again:
        raise InvalidDecisionError(cleaner, f"{again} block(s) already edited by this cleaner")
    if len(decisions) - len(removals) > MAX_EDITS_PER_PAGE or any(
        len(block_edits) > MAX_EDITS_PER_BLOCK for block_edits in edits.values()
    ):
        raise InvalidDecisionError(cleaner, "too many edits")
    for block_id, block_edits in edits.items():
        problem = _edit_problem(blocks[block_id].text, block_edits)
        if problem:
            raise InvalidDecisionError(cleaner, problem)

    reasons = {decision.block_id: decision.reason for decision in removals}

    def changed(block: Block) -> Block:
        if block.id in reasons:
            return block.mark_removed(cleaner, reasons[block.id])
        if block.id in edits:
            return _edited(block, edits[block.id], cleaner)
        return block

    return Page.model_validate(
        {
            **page.model_dump(exclude={"blocks"}),
            "blocks": tuple(changed(block) for block in page.blocks),
        }
    )


def _edit_problem(text: str, edits: list[EditDecision]) -> str | None:
    """Why these edits of one block's text are refused, or None if they are valid."""
    previous_end = 0
    for edit in sorted(edits, key=lambda edit: edit.start):
        if not edit.start < edit.end <= len(text):
            # Empty spans would be insertions: new text the source never had.
            return "an edit is outside the text or empty"
        if edit.start < previous_end:
            return "edits overlap"
        previous_end = edit.end
        if not _allowed(edit.kind, text, edit.start, edit.end, edit.replacement):
            # The kind, never the text: the text is the document's (principle 11).
            return f"an edit is not a valid {edit.kind.value}"
    return None


_HYPHEN_BREAK = re.compile(HYPHEN_BREAK)
# Characters around an edit compared with it; words further away cannot change.
_CONTEXT = 64


def _allowed(kind: EditKind, text: str, start: int, end: int, replacement: str) -> bool:
    """Check mechanically that an edit is what its kind promises."""
    original = text[start:end]
    if original == replacement:
        return False
    if kind is EditKind.DELETE:
        return replacement == ""
    if kind is EditKind.NORMALIZE:
        return _normalization(text, start, end, replacement)
    # A hyphen join removes exactly a hyphen and the line break after it,
    # between two letters: "infor-\nmation" -> "information".
    return (
        replacement == ""
        and _HYPHEN_BREAK.fullmatch(original) is not None
        and start > 0
        and end < len(text)
        and is_letter(text[start - 1])
        and is_letter(text[end])
    )


def _normalization(text: str, start: int, end: int, replacement: str) -> bool:
    """Same visible characters, spacing that only shrinks, words joined only where allowed."""
    original = text[start:end]
    if visible(original) != visible(replacement):
        return False
    # No new line, no extra or other whitespace: a normalisation cannot open a
    # paragraph, indent a line into a code block or split a word.
    spaces = [char for char in replacement if char.isspace()]
    if any(char not in " \n" for char in spaces) or len(spaces) > sum(
        char.isspace() for char in original
    ):
        return False
    if replacement.count("\n") > original.count("\n"):
        return False
    if not any(char.isspace() for char in original):
        # No space removed, so no words joined: a ligature, an invisible
        # character, a composed accent. Cheap, and the common case.
        return True
    if replacement and original.isspace() and replacement.isspace():
        # Spaces for fewer spaces: the words on both sides stay apart.
        return True
    before = text[max(0, start - _CONTEXT) : start]
    after = text[end : end + _CONTEXT]
    return _joins_allowed(
        canonical(before + original + after).split(),
        canonical(before + replacement + after).split(),
    )


def _joins_allowed(old: list[str], new: list[str]) -> bool:
    """Whether ``new`` is ``old`` with words joined only after an apostrophe or hyphen.

    "dell' albero" may become "dell'albero" and "well- known" "well-known";
    "now here" may not become "nowhere".
    """
    index = 0
    for word in new:
        if index >= len(old):
            return False
        joined = old[index]
        index += 1
        while joined != word:
            if (
                index >= len(old)
                or joined[-1] not in _JOINERS
                or not word.startswith(joined + old[index][:1])
            ):
                return False
            joined += old[index]
            index += 1
    return index == len(old)


_JOINERS = APOSTROPHES + COMPOUND_HYPHENS


def _edited(block: Block, edits: list[EditDecision], cleaner: str) -> Block:
    text = block.text
    records: list[TextEdit] = []
    for edit in sorted(edits, key=lambda edit: edit.start):
        records.append(
            TextEdit(
                start=edit.start,
                end=edit.end,
                original=text[edit.start : edit.end],
                replacement=edit.replacement,
                kind=edit.kind,
                edited_by=cleaner,
                reason=edit.reason,
            )
        )
    # Built in one pass: splicing edit by edit would copy the text each time.
    pieces: list[str] = []
    position = 0
    for record in records:
        pieces += (text[position : record.start], record.replacement)
        position = record.end
    text = "".join((*pieces, text[position:]))
    # model_copy skips validation, so rebuild through the validator instead.
    return block.model_validate(
        {**block.model_dump(), "text": text, "edits": (*block.edits, *records)}
    )


def within_limits(per_block: Iterable[list[EditDecision]]) -> list[EditDecision]:
    """A cleaner's edits for a page, keeping only what the core accepts.

    A block that needs more than ``MAX_EDITS_PER_BLOCK`` edits is left as it
    is, and once the page reaches ``MAX_EDITS_PER_PAGE`` the remaining
    blocks are too: when in doubt, leave it (ADR-025).
    """
    kept: list[EditDecision] = []
    for block_edits in per_block:
        if len(block_edits) > MAX_EDITS_PER_BLOCK:
            continue
        if len(kept) + len(block_edits) > MAX_EDITS_PER_PAGE:
            break
        kept += block_edits
    return kept
