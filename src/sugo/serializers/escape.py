"""Minimal Markdown escaping: only where document text would create structure.

OCR text that starts with "#", "-" or "1." would turn into a heading or a list
it never was, and hostile text could fake structure the same way. A backslash
is added only at those spots, so ordinary text costs no extra tokens (ADR-042).
Raw HTML is left as is: Sugo's output is read by LLMs, and a port that renders
Markdown for people must sanitise it.
"""

import re

from sugo.core.constants import MARKDOWN_MAX_STRUCTURE_INDENT

# Marks unreadable content (principle 4, ADR-026). The same text inside a
# document is escaped, so a document cannot pretend some of it is unreadable.
ILLEGIBLE_MARKER = "[illegible]"

# Characters that open structure at the start of a line: headings, quotes,
# tables and their delimiter rows, lists, thematic breaks, setext underlines
# and code fences. A backslash before any of them is a literal character.
_STRUCTURE_START = frozenset("#>|:=+*-_`~")
_ORDERED_ITEM = re.compile(r"^(\d{1,9})([.)])(?=\s|$)")
_HEADING_CLOSER = re.compile(r"(\s)(#+)(\s*)$")


def escape_marker(text: str) -> str:
    """Escape every literal occurrence of the illegible marker."""
    return text.replace(ILLEGIBLE_MARKER, "\\" + ILLEGIBLE_MARKER)


def escape_line_start(line: str) -> str:
    """Escape the start of one line if it would open Markdown structure."""
    stripped = line.lstrip(" ")
    indent = line[: len(line) - len(stripped)]
    if len(indent) > MARKDOWN_MAX_STRUCTURE_INDENT or not stripped:
        return line
    if stripped[0] in _STRUCTURE_START:
        return f"{indent}\\{stripped}"
    return indent + _ORDERED_ITEM.sub(r"\1\\\2", stripped, count=1)


def escape_line(line: str) -> str:
    """Escape one line of document text."""
    return escape_line_start(escape_marker(line))


def escape_heading(text: str) -> str:
    """Escape heading text, which must not end with a closing ``#`` sequence."""
    return _HEADING_CLOSER.sub(r"\1\\\2\3", escape_marker(text))
