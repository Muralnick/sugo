"""Tests for dropping terminal control characters before Markdown is escaped and rendered."""

from hypothesis import given
from hypothesis import strategies as st

from sugo.core.models import Block, BlockType, Table, TableCell
from sugo.serializers.escape import drop_controls
from sugo.serializers.markdown import render

ESC = chr(0x1B)
BEL = chr(0x07)
CSI = chr(0x9B)


def block(text: str, kind: BlockType = BlockType.PARAGRAPH, **extra: object) -> Block:
    return Block(id="b", type=kind, text=text, origin_engine="test", **extra)  # type: ignore[arg-type]


def is_control(char: str) -> bool:
    code = ord(char)
    return char not in "\t\n" and (code < 0x20 or 0x7F <= code < 0xA0)


def test_controls_are_dropped_and_line_breaks_kept() -> None:
    assert drop_controls(f"a{ESC}[2Jb{BEL}c{CSI}d") == "a[2Jbcd"
    assert drop_controls("one\r\ntwo\rthree\x0bfour\x0cfive\x85six") == (
        "one\ntwo\nthree\nfour\nfive\nsix"
    )
    assert drop_controls("tab\tand\nnewline") == "tab\tand\nnewline"


def test_dropped_control_cannot_hide_structure_from_the_escaper() -> None:
    # Without the control first, "# x" would become a heading nobody wrote.
    assert render([block(f"{ESC}# not a heading")]) == "\\# not a heading"
    assert render([block(f"{ESC}left: fake")]) == "left\\: fake"


def test_every_block_kind_is_cleaned() -> None:
    heading = block(f"Title{ESC}]0;x{BEL}", BlockType.HEADING, heading_level=1)
    code = block(f"print(1){ESC}[2J", BlockType.CODE)
    table = Table(n_rows=1, n_cols=2, cells=(TableCell(row=0, col=0, text=f"a{ESC}b"),))
    cells = block("", BlockType.TABLE, table=table)
    rendered = render([heading, code, cells])
    assert not any(is_control(char) for char in rendered)
    assert "# Title]0;x" in rendered


def test_control_only_text_renders_nothing() -> None:
    assert render([block(f"{ESC}{BEL}")]) == ""


@given(st.text())
def test_no_control_character_survives_rendering(text: str) -> None:
    rendered = render([block(text), block(text, BlockType.LIST_ITEM)])
    assert not any(is_control(char) for char in rendered)
