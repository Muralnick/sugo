"""Render IR blocks as compact Markdown, the format Sugo hands to LLMs (ADR-042).

Blocks are rendered in the order given, which is their reading order, and
separated by a blank line; consecutive list items and consecutive chat
messages with a speaker by a single newline. Removed blocks are left out: they stay in the IR
with their reason (principle 3). Blocks that are not removed are always
rendered, whatever their type, so only cleaners decide what is dropped.

- headings: ``#`` repeated by level, lines joined with a space;
- list items: ``- text``, indented two spaces per list level but never more
  than one level below the item above, where deeper indentation would make
  code; chat messages: ``left: text`` or ``right: text``, the neutral side
  of the bubble (ADR-040); their further lines are indented;
- code: a fenced block, text unchanged but for a literal ``[illegible]``;
- tables: the cheapest faithful format (``sugo.serializers.tables``);
- illegible blocks: ``[illegible]``, never a guess (principle 4, ADR-026);
- anything else: the text, lines kept as they are.

Blank lines around a block's text and the indentation of each line that
starts a paragraph are dropped: they would merge the block into the one above
or make it code.

Document text is escaped only where it would create structure
(``sugo.serializers.escape``).
"""

import re
from collections.abc import Iterable

from sugo.core.constants import MARKDOWN_CONTINUATION_INDENT, MARKDOWN_MIN_FENCE
from sugo.core.models import Block, BlockFlag, BlockType
from sugo.serializers.escape import (
    ILLEGIBLE_MARKER,
    drop_controls,
    escape_heading,
    escape_line,
    escape_marker,
)
from sugo.serializers.tables import render_table

_BACKTICKS = re.compile(r"`+")


def render(blocks: Iterable[Block]) -> str:
    """Render blocks as Markdown, without a trailing newline."""
    parts: list[str] = []
    previous: BlockType | None = None
    # Level of the list item just rendered; -1 outside a list.
    list_level = -1
    for block in blocks:
        if block.removed:
            continue
        # Consecutive prefixed blocks of one type are one list or one
        # conversation: no blank line inside. A block without a prefix (a chat
        # message without a speaker) has nothing to set it apart, so it is not.
        run_type = block.type if _prefix(block) is not None else None
        level = 0
        if block.type is BlockType.LIST_ITEM:
            above = list_level if previous is BlockType.LIST_ITEM else -1
            level = min(block.list_level or 0, above + 1)
        rendered = _render_block(block, level)
        if rendered is None:
            continue
        if parts:
            parts.append("\n" if run_type is not None and run_type is previous else "\n\n")
        parts.append(rendered)
        previous = run_type
        list_level = level
    return "".join(parts)


def render_widest(block: Block) -> str:
    """One block as wide as it can render in any list: a list item at its own level.

    Alone, a nested item renders at level 0; after the items above it, at
    most at its own level. The chunker counts tokens with this, so its
    estimates never fall below what the chunk renders.
    """
    if block.removed:
        return ""
    return _render_block(block, block.list_level or 0) or ""


def _render_block(block: Block, level: int = 0) -> str | None:
    """One block as Markdown, or None if it has nothing to show; ``level`` nests a list item."""
    if BlockFlag.ILLEGIBLE in block.flags:
        return _prefixed(block, [ILLEGIBLE_MARKER], level)
    if block.type is BlockType.TABLE and block.table is not None:
        return render_table(block.table)
    # First of all: escaping must see the text as it will be printed.
    text = drop_controls(block.text)
    if not text.strip():
        return None
    if block.type is BlockType.CODE:
        return _fenced(text)
    if block.type is BlockType.HEADING:
        heading = " ".join(line.strip() for line in text.splitlines() if line.strip())
        return f"{'#' * (block.heading_level or 1)} {escape_heading(heading)}"
    return _prefixed(block, [escape_line(line) for line in _text_lines(text)], level)


def _text_lines(text: str) -> list[str]:
    """Lines of non-blank text, ready to be escaped and prefixed.

    Blank lines around the text are dropped, blank lines inside it are made
    empty, and a line that starts a paragraph (the first, or one after a blank
    line) loses its indentation: a leading blank line would leave a list or
    speaker prefix empty, and an indented paragraph would continue the list
    item above or become code.
    """
    lines = [line if line.strip() else "" for line in text.splitlines()]
    while not lines[0]:
        del lines[0]
    while not lines[-1]:
        del lines[-1]
    return [line.lstrip() if n == 0 or not lines[n - 1] else line for n, line in enumerate(lines)]


def _prefix(block: Block) -> str | None:
    """The list or speaker prefix the block type calls for, if any."""
    if block.type is BlockType.LIST_ITEM:
        return "- "
    if block.type is BlockType.CHAT_MESSAGE and block.speaker is not None:
        return f"{block.speaker.value}: "
    return None


def _prefixed(block: Block, lines: list[str], level: int = 0) -> str:
    """Escaped lines with the block's prefix; further lines are indented under it."""
    prefix = _prefix(block)
    if prefix is None:
        return "\n".join(lines)
    # A nested item starts where the text of the item above starts.
    prefix = " " * (MARKDOWN_CONTINUATION_INDENT * level) + prefix
    indent = " " * (MARKDOWN_CONTINUATION_INDENT * (level + 1))
    # Empty lines stay empty: indenting them would add whitespace and no content.
    return "\n".join([prefix + lines[0], *(indent + line if line else "" for line in lines[1:])])


def _fenced(code: str) -> str:
    """Code in a fence, unchanged but for a literal marker; the fence adds the last newline."""
    code = escape_marker(code.rstrip("\r\n"))
    longest = max((len(run) for run in _BACKTICKS.findall(code)), default=0)
    fence = "`" * max(MARKDOWN_MIN_FENCE, longest + 1)
    return f"{fence}\n{code}\n{fence}"
