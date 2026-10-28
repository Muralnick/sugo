"""Tests for minimal Markdown escaping: structure is neutralised, plain text untouched."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from sugo.serializers.escape import (
    ILLEGIBLE_MARKER,
    escape_heading,
    escape_line,
    escape_line_start,
)


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("# 1 in classifica", "\\# 1 in classifica"),
        ("- 20% sconto", "\\- 20% sconto"),
        ("* note", "\\* note"),
        ("+ plus", "\\+ plus"),
        ("> quoted", "\\> quoted"),
        ("1. first", "1\\. first"),
        ("12) twelfth", "12\\) twelfth"),
        ("```python", "\\```python"),
        ("~~~", "\\~~~"),
        ("---", "\\---"),
        ("===", "\\==="),
        ("|a|b|", "\\|a|b|"),
        (":-|-:", "\\:-|-:"),
        ("   # indented", "   \\# indented"),
    ],
)
def test_structure_at_line_start_is_escaped(line: str, expected: str) -> None:
    assert escape_line_start(line) == expected


@pytest.mark.parametrize(
    "line",
    [
        "Il contratto può essere risolto.",
        "Total 1250 EUR",
        "2026 was a good year",
        "1.5 kg of flour",
        "C# and F# are languages",
        "    # four spaces: an indented line, not a heading",
        "",
    ],
)
def test_plain_text_is_unchanged(line: str) -> None:
    assert escape_line_start(line) == line


def test_illegible_marker_in_text_is_escaped() -> None:
    assert escape_line("see [illegible] here") == "see \\[illegible] here"


def test_heading_closing_hashes_are_kept_as_text() -> None:
    assert escape_heading("Use C #") == "Use C \\#"
    assert escape_heading("Item #1") == "Item #1"


@given(st.text(alphabet=st.characters(exclude_categories=["Cs"]), max_size=40))
def test_escaping_only_adds_backslashes(line: str) -> None:
    # Nothing is lost or rewritten: removing the added backslashes gives the text back.
    escaped = escape_line(line)
    assert len(escaped) - len(line) in (0, 1, 2) or ILLEGIBLE_MARKER in line
    assert escaped.replace("\\", "") == line.replace("\\", "")
