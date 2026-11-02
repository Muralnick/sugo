"""Minimal Markdown escaping: only where document text would create structure.

OCR text that starts with "#", "-" or "1." would turn into a heading or a list
it never was, and hostile text could fake structure the same way. A backslash
is added only at those spots, so ordinary text costs no extra tokens (ADR-042).
Raw HTML is left as is: Sugo's output is read by LLMs, and a port that renders
Markdown for people must sanitise it.
"""

import re

from sugo.core.constants import MARKDOWN_MAX_STRUCTURE_INDENT, MARKDOWN_TAB_STOP
from sugo.core.models import ChatSide

# Marks unreadable content (principle 4, ADR-026). The same text inside a
# document is escaped, so a document cannot pretend some of it is unreadable.
ILLEGIBLE_MARKER = "[illegible]"

# Characters that open structure at the start of a line: headings, quotes,
# tables and their delimiter rows, lists, thematic breaks, setext underlines
# and code fences. A backslash before any of them is a literal character.
_STRUCTURE_START = frozenset("#>|:=+*-_`~")
_ORDERED_ITEM = re.compile(r"^(\d{1,9})([.)])(?=\s|$)")
# Text starting with a speaker label would pass for a chat message (ADR-040).
_SPEAKER = re.compile(rf"^({'|'.join(side.value for side in ChatSide)}):")
# A heading ending with "#"s, or made only of them, would lose them as a closer.
_HEADING_CLOSER = re.compile(r"(^|\s)(#+)(\s*)$")
# Backslashes already in the text before the marker are doubled, so they stay
# literal and the marker's own backslash still escapes it.
_MARKER = re.compile(rf"(\\*){re.escape(ILLEGIBLE_MARKER)}")
# C0 controls but tab and line feed, DEL and C1. The line-breaking ones (CR,
# VT, FF, FS, GS, RS, NEL) become line feeds; the rest are dropped.
_LINE_BREAKS = frozenset({0x0D, 0x0B, 0x0C, 0x1C, 0x1D, 0x1E, 0x85})
_CONTROLS: dict[int, str | None] = {
    code: "\n" if code in _LINE_BREAKS else None
    for code in (*range(0x00, 0x20), *range(0x7F, 0xA0))
    if code not in (0x09, 0x0A)
}


def drop_controls(text: str) -> str:
    """Remove the control characters a document could use to drive a terminal.

    Escape sequences in the output could clear the screen, fake a prompt or
    write the clipboard of whoever reads it in a terminal (security review of
    ADR-048). Controls that ``str.splitlines`` treats as line breaks become
    ``\\n``, so lines split as before; the others never print and are dropped.
    Called before any escaping, so a dropped character cannot hide structure
    from the escaper.
    """
    return text.replace("\r\n", "\n").translate(_CONTROLS)


def escape_marker(text: str) -> str:
    """Escape every literal occurrence of the illegible marker."""
    return _MARKER.sub(lambda m: m[1] * 2 + "\\" + ILLEGIBLE_MARKER, text)


def escape_line_start(line: str) -> str:
    """Escape the start of one line if it would open structure.

    Tabs in the indentation become spaces, so the width that decides whether
    the line can open Markdown structure is the one a Markdown reader sees.
    A speaker label is escaped at any indentation: it is structure for an
    LLM, not for Markdown.
    """
    stripped = line.lstrip(" \t")
    indent = line[: len(line) - len(stripped)].expandtabs(MARKDOWN_TAB_STOP)
    if not stripped:
        return line
    if len(indent) <= MARKDOWN_MAX_STRUCTURE_INDENT:
        if stripped[0] in _STRUCTURE_START:
            return f"{indent}\\{stripped}"
        stripped = _ORDERED_ITEM.sub(r"\1\\\2", stripped, count=1)
    return indent + _SPEAKER.sub(r"\1\\:", stripped, count=1)


def escape_line(line: str) -> str:
    """Escape one line of document text."""
    return escape_line_start(escape_marker(line))


def escape_heading(text: str) -> str:
    """Escape heading text, which must not end with a closing ``#`` sequence."""
    return _HEADING_CLOSER.sub(r"\1\\\2\3", escape_marker(text))
