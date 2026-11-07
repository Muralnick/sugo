"""Tests for sugo.extractors.image.handwriting and handwriting blocks in the layout (ADR-063)."""

import pytest

from sugo.core.models import BBox, BlockFlag
from sugo.extractors.image.handwriting import mark_handwriting, typical_height
from sugo.extractors.image.layout import build_blocks
from sugo.extractors.image.ocr_engine import OcrLine

LINE = 0.02  # typed line height, as a share of the page


def line(
    text: str,
    y: float,
    *,
    x: float = 0.1,
    width: float = 0.6,
    height: float = LINE,
    confidence: float = 0.99,
    illegible: bool = False,
) -> OcrLine:
    return OcrLine(
        text="" if illegible else text,
        confidence=confidence,
        bbox=BBox(x0=x, y0=y, x1=x + width, y1=y + height),
        illegible=illegible,
    )


BODY = [
    line(f"Body line {n} of the record, long enough to count.", 0.1 + n * 0.03) for n in range(6)
]


def marked(*extra: OcrLine) -> list[OcrLine]:
    return mark_handwriting([*BODY, *extra])


def test_a_tall_uncertain_line_is_handwriting() -> None:
    signature = line("dliise Matep", 0.5, width=0.25, height=2.2 * LINE, confidence=0.70)
    assert marked(signature)[-1].handwriting


def test_a_tall_confident_heading_stays_text() -> None:
    heading = line("ANNUAL REPORT", 0.02, height=3 * LINE, confidence=0.99)
    assert not marked(heading)[-1].handwriting


def test_a_short_uncertain_line_stays_text() -> None:
    blurry = line("blurry but typed", 0.5, confidence=0.6)
    assert not marked(blurry)[-1].handwriting


def test_an_illegible_line_stays_illegible() -> None:
    scribble = line("", 0.5, height=3 * LINE, confidence=0.3, illegible=True)
    result = marked(scribble)[-1]
    assert result.illegible
    assert not result.handwriting


def test_typed_text_crossed_by_ink_is_flagged_and_kept() -> None:
    name = line("Lara Costa", 0.60, width=0.2)
    signature = line("do e coste", 0.59, x=0.08, width=0.3, height=2.5 * LINE, confidence=0.9)
    above = line("Maria Luisa Motta", 0.50, width=0.2)
    result = marked(name, signature, above)
    assert result[-3].ink_overlap
    assert result[-3].text == "Lara Costa"
    assert not result[-1].ink_overlap  # Near the ink, not under it.


def test_short_logo_words_do_not_set_the_typical_height() -> None:
    # A letterhead of many short small words must not make body lines look tall.
    logos = [line("Erasmus+", 0.01 * n, x=0.7, width=0.05, height=0.4 * LINE) for n in range(10)]
    assert typical_height([*logos, *BODY]) == pytest.approx(LINE)


def test_no_readable_text_marks_nothing() -> None:
    lines = [line("", 0.5, illegible=True, confidence=0.1)]
    assert mark_handwriting(lines) == lines
    assert mark_handwriting([]) == []


def test_the_result_does_not_depend_on_line_order() -> None:
    lines = [
        *BODY,
        line("Lara Costa", 0.60, width=0.2),
        line("do e coste", 0.59, x=0.08, width=0.3, height=2.5 * LINE, confidence=0.9),
    ]
    expected = {(item.text, item.handwriting, item.ink_overlap) for item in mark_handwriting(lines)}
    shuffled = lines[::-1]
    assert {
        (item.text, item.handwriting, item.ink_overlap) for item in mark_handwriting(shuffled)
    } == expected


def test_layout_keeps_handwriting_apart_with_its_flags() -> None:
    name = line("Lara Costa", 0.60, width=0.2)
    signature = line("do e coste", 0.59, x=0.08, width=0.3, height=2.5 * LINE, confidence=0.9)
    blocks = build_blocks(mark_handwriting([*BODY, name, signature]), origin_engine="test")
    ink = [block for block in blocks if BlockFlag.HANDWRITING in block.flags]
    crossed = [block for block in blocks if BlockFlag.INK_OVERLAP in block.flags]
    assert [block.text for block in ink] == ["do e coste"]
    assert [block.text for block in crossed] == ["Lara Costa"]
    # Never merged into the typed text beside it.
    assert all("do e coste" not in block.text for block in blocks if block not in ink)
