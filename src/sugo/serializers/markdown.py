"""Render IR blocks as compact Markdown, the format Sugo hands to LLMs (ADR-042).

Blocks are rendered in the order given, which is their reading order, and
separated by a blank line; consecutive list items and consecutive chat
messages with a speaker by a single newline. Removed blocks are left out: they stay in the IR
with their reason (principle 3). Blocks that are not removed are always
rendered, whatever their type, so only cleaners decide what is dropped.

- headings: ``#`` repeated by level, lines joined with a space;
- list items: ``- text``; chat messages: ``left: text`` or ``right: text``,
  the neutral side of the bubble (ADR-040); their further lines are indented;
- code: a fenced block, text unchanged;
- tables: the cheapest faithful format (``sugo.serializers.tables``);
- illegible blocks: ``[illegible]``, never a guess (principle 4, ADR-026);
- anything else: the text, lines kept as they are.

Blank lines around a block's text and the indentation of its first line are
dropped: they would merge the block into the one above or make it code.

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
# A chat message without a speaker has no prefix to set it apart, so it is
# kept out of such runs (``_run_type``).
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
        run_type = _run_type(block)
        if parts:
            parts.append("\n" if run_type is not None and run_type is previous else "\n\n")
        parts.append(rendered)
        previous = run_type
    return "".join(parts)


def _run_type(block: Block) -> BlockType | None:
    """The type whose consecutive blocks are joined by one newline, if any."""
    if block.type not in _TIGHT:
        return None
    if block.type is BlockType.CHAT_MESSAGE and block.speaker is None:
        return None
    return block.type


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
        text = " ".join(line.strip() for line in block.text.splitlines() if line.strip())
        return f"{'#' * (block.heading_level or 1)} {escape_heading(text)}"
    return _prefixed(block, [escape_line(line) for line in _text_lines(block.text)])


def _text_lines(text: str) -> list[str]:
    """Lines of non-blank text, without blank lines around them or first-line indentation.

    A leading blank line would leave a list or speaker prefix empty, and an
    indented first line would continue the list item above or become code.
    """
    lines = text.splitlines()
    while not lines[0].strip():
        del lines[0]
    while not lines[-1].strip():
        del lines[-1]
    lines[0] = lines[0].lstrip()
    return lines


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
