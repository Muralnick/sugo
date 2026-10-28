"""Render IR blocks as compact Markdown, the format Sugo hands to LLMs (ADR-042).

Blocks are rendered in the order given, which is their reading order, and
separated by a blank line; consecutive list items and consecutive chat
messages by a single newline. Removed blocks are left out: they stay in the IR
with their reason (principle 3). Blocks that are not removed are always
rendered, whatever their type, so only cleaners decide what is dropped.

- headings: ``#`` repeated by level, lines joined with a space;
- list items: ``- text``; chat messages: ``left: text`` or ``right: text``,
  the neutral side of the bubble (ADR-040); their further lines are indented;
- code: a fenced block, text unchanged;
- tables: the cheapest faithful format (``sugo.serializers.tables``);
- illegible blocks: ``[illegible]``, never a guess (principle 4, ADR-026);
- anything else: the text, lines kept as they are.

Document text is escaped only where it would create structure
(``sugo.serializers.escape``).
"""

import re
from collections.abc import Iterable

from sugo.core.constants import MARKDOWN_CONTINUATION_INDENT, MARKDOWN_MIN_FENCE
from sugo.core.models import Block, BlockFlag, BlockType
from sugo.serializers.escape import ILLEGIBLE_MARKER, escape_heading, escape_line
from sugo.serializers.tables import render_table

# Runs of these blocks are one list or one conversation: no blank line inside.
_TIGHT = frozenset({BlockType.LIST_ITEM, BlockType.CHAT_MESSAGE})
_BACKTICKS = re.compile(r"`+")


def render(blocks: Iterable[Block]) -> str:
    """Render blocks as Markdown, without a trailing newline."""
    parts: list[str] = []
    previous: BlockType | None = None
    for block in blocks:
        if block.removed:
            continue
        rendered = _render_block(block)
        if rendered is None:
            continue
        if parts:
            parts.append("\n" if block.type is previous and block.type in _TIGHT else "\n\n")
        parts.append(rendered)
        previous = block.type
    return "".join(parts)


def _render_block(block: Block) -> str | None:
    """One block as Markdown, or None if it has nothing to show."""
    if BlockFlag.ILLEGIBLE in block.flags:
        return _prefixed(block, [ILLEGIBLE_MARKER])
    if block.type is BlockType.TABLE and block.table is not None:
        return render_table(block.table)
    if not block.text.strip():
        return None
    if block.type is BlockType.CODE:
        return _fenced(block.text)
    if block.type is BlockType.HEADING:
        text = " ".join(line.strip() for line in block.text.splitlines())
        return f"{'#' * (block.heading_level or 1)} {escape_heading(text)}"
    return _prefixed(block, [escape_line(line) for line in block.text.splitlines()])


def _prefixed(block: Block, lines: list[str]) -> str:
    """Escaped lines with the list or speaker prefix the block type calls for."""
    if block.type is BlockType.LIST_ITEM:
        prefix = "- "
    elif block.type is BlockType.CHAT_MESSAGE and block.speaker is not None:
        prefix = f"{block.speaker.value}: "
    else:
        return "\n".join(lines)
    indent = " " * MARKDOWN_CONTINUATION_INDENT
    return "\n".join([prefix + lines[0], *(indent + line for line in lines[1:])])


def _fenced(code: str) -> str:
    longest = max((len(run) for run in _BACKTICKS.findall(code)), default=0)
    fence = "`" * max(MARKDOWN_MIN_FENCE, longest + 1)
    return f"{fence}\n{code}\n{fence}"
