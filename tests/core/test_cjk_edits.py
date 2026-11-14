"""Tests for the core checks of ADR-069: CJK line joins and character width."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from sugo.core.decisions import EditDecision, InvalidDecisionError, apply_decisions
from sugo.core.models import Block, BlockType, EditKind, Page, PageOrigin
from sugo.core.text import canonical, is_cjk, joins_cjk_lines, visible

# Written with chr() so the source holds no confusable characters.
FW_A = chr(0xFF21)  # full-width A
FW_1 = chr(0xFF11)  # full-width 1
FW_COMMA = chr(0xFF0C)
HW_KA = chr(0xFF76)  # half-width Katakana KA
HW_VOICED = chr(0xFF9E)  # half-width voiced sound mark
IDEOGRAPHIC_SPACE = chr(0x3000)


def page(text: str) -> Page:
    block = Block(id="b0", type=BlockType.PARAGRAPH, text=text, origin_engine="t")
    return Page(index=0, width=100, height=100, origin=PageOrigin.NATIVE, blocks=(block,))


def edit(start: int, end: int, replacement: str, kind: EditKind) -> EditDecision:
    return EditDecision(
        block_id="b0", start=start, end=end, replacement=replacement, kind=kind, reason="r"
    )


def applied(text: str, *edits: EditDecision) -> Block:
    return apply_decisions(page(text), edits, cleaner="c").blocks[0]


@pytest.mark.parametrize(
    ("char", "expected"),
    [
        ("全", True),
        ("か", True),
        ("カ", True),
        ("ー", True),
        ("。", True),
        (FW_COMMA, True),
        (HW_KA, True),
        ("𠀋", True),  # Han extension B
        (FW_A, True),
        (FW_1, True),
        ("한", False),  # Hangul: Korean puts spaces between words
        (IDEOGRAPHIC_SPACE, False),
        ("a", False),
        ("1", False),
    ],
)
def test_cjk_characters(char: str, expected: bool) -> None:
    assert is_cjk(char) is expected


class TestCjkJoin:
    @pytest.mark.parametrize(
        ("text", "start", "end", "expected"),
        [
            ("全\n角", 1, 2, "全角"),
            ("全 \t\n 角", 1, 5, "全角"),
            ("で、\n行", 2, 3, "で、行"),
            (FW_1 + "\n" + FW_A, 1, 2, FW_1 + FW_A),  # full-width forms are CJK text
        ],
    )
    def test_line_break_between_cjk_characters_goes(
        self, text: str, start: int, end: int, expected: str
    ) -> None:
        block = applied(text, edit(start, end, "", EditKind.CJK_JOIN))
        assert block.text == expected
        assert block.original_text() == text

    @pytest.mark.parametrize(
        ("text", "start", "end", "replacement"),
        [
            ("全\n角", 1, 2, " "),  # a join removes, it never replaces
            ("全\n\n角", 1, 3, ""),  # a paragraph break
            ("全 角", 1, 2, ""),  # no line break
            ("全\nx", 1, 2, ""),  # a Latin letter after
            ("1\n角", 1, 2, ""),  # a digit before
            ("한\n국", 1, 2, ""),  # Hangul
            ("全x\n角", 1, 3, ""),  # the span holds a letter
            (HW_KA + "\n" + HW_VOICED, 1, 2, ""),  # it would compose a new letter
            ("\n角", 0, 1, ""),  # nothing before
            ("全\n", 1, 2, ""),  # nothing after
        ],
    )
    def test_anything_else_is_refused(
        self, text: str, start: int, end: int, replacement: str
    ) -> None:
        with pytest.raises(InvalidDecisionError, match="not a valid cjk_join"):
            applied(text, edit(start, end, replacement, EditKind.CJK_JOIN))


class TestWidth:
    @pytest.mark.parametrize(
        ("original", "replacement"),
        [
            (FW_A + FW_1, "A1"),
            (HW_KA, "カ"),
            (HW_KA + HW_VOICED, "ガ"),
        ],
    )
    def test_width_forms_are_a_valid_normalisation(self, original: str, replacement: str) -> None:
        text = f"x{original}y"
        block = applied(text, edit(1, 1 + len(original), replacement, EditKind.NORMALIZE))
        assert block.text == f"x{replacement}y"
        assert block.original_text() == text

    @pytest.mark.parametrize(
        ("original", "replacement"),
        [
            (FW_COMMA, ","),  # full-width punctuation stays
            ("㈱", "(株)"),  # full NFKC is still refused
            ("m²", "m2"),
            (FW_A, "B"),
        ],
    )
    def test_other_compatibility_forms_are_refused(self, original: str, replacement: str) -> None:
        with pytest.raises(InvalidDecisionError, match="not a valid normalize"):
            applied(f"x{original}y", edit(1, 1 + len(original), replacement, EditKind.NORMALIZE))

    def test_canonical_keeps_simplified_and_traditional_apart(self) -> None:
        assert canonical("简体繁體") == "简体繁體"


_PIECES = st.sampled_from(["全", "角", "か", "。", "\n", " ", FW_A, FW_1, HW_KA, HW_VOICED, "a"])


@pytest.mark.invariant
@given(st.lists(_PIECES, min_size=1, max_size=12))
def test_accepted_cjk_joins_keep_every_visible_character(pieces: list[str]) -> None:
    """Principles 3 and 4: a CJK join only removes whitespace, and can be undone."""
    text = "".join(pieces)
    edits = [
        edit(n, n + 1, "", EditKind.CJK_JOIN)
        for n in range(1, len(text) - 1)
        if text[n] == "\n" and joins_cjk_lines(text[n - 1], text[n + 1])
    ]
    if not edits:
        return
    block = applied(text, *edits)
    assert visible(block.text) == visible(text)
    assert block.original_text() == text
