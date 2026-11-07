"""Find handwriting, such as signatures, among the OCR lines of a scanned page (ADR-063).

The bundled OCR reads pen strokes as made-up words, often with a confidence
well above the illegibility threshold. Two signals tell them apart from
typed text: a handwriting line is much taller than the page's typical text
line, and it is read with less confidence than typed text of that size.

The typical height is the median line height weighted by characters, so
long body lines set it, not the short words of a letterhead or a logo.
Colour is not used: a coloured typed heading in a real letterhead would
pass for blue ink (measured 2026-11-07).

Typed lines that a handwriting line crosses keep their text, flagged
``ink_overlap``: their letters may be damaged, but they are often the only
copy of a name. Illegible lines stay illegible.

Screenshots never get this check: their tall, uncertain lines are emoji and
interface glyphs, not ink.
"""

from collections.abc import Sequence
from dataclasses import replace

from sugo.core.constants import HANDWRITING_MAX_CONFIDENCE, HANDWRITING_MIN_HEIGHT_RATIO
from sugo.core.models import BBox
from sugo.extractors.image.ocr_engine import OcrLine


def mark_handwriting(lines: Sequence[OcrLine]) -> list[OcrLine]:
    """Return the lines with handwriting and the typed text it crosses marked.

    The result does not depend on the order of the input lines (principle 6).
    """
    typical = typical_height(lines)
    if typical is None:
        return list(lines)
    ink = [
        index
        for index, line in enumerate(lines)
        if not line.illegible
        and _height(line.bbox) >= HANDWRITING_MIN_HEIGHT_RATIO * typical
        and line.confidence < HANDWRITING_MAX_CONFIDENCE
    ]
    if not ink:
        return list(lines)
    boxes = [lines[index].bbox for index in ink]
    marked: list[OcrLine] = []
    for index, line in enumerate(lines):
        if index in ink:
            marked.append(replace(line, handwriting=True))
        elif not line.illegible and any(_overlap(line.bbox, box) for box in boxes):
            marked.append(replace(line, ink_overlap=True))
        else:
            marked.append(line)
    return marked


def typical_height(lines: Sequence[OcrLine]) -> float | None:
    """The median height of readable lines, each weighted by its number of characters."""
    weighted = sorted(
        (_height(line.bbox), len(line.text.strip()))
        for line in lines
        if not line.illegible and line.text.strip()
    )
    total = sum(weight for _, weight in weighted)
    if total == 0:
        return None
    seen = 0
    for height, weight in weighted:
        seen += weight
        if 2 * seen >= total:
            return height if height > 0 else None
    return None  # pragma: no cover - the loop always returns once total > 0


def _height(box: BBox) -> float:
    return box.y1 - box.y0


def _overlap(a: BBox, b: BBox) -> bool:
    """Whether two boxes share some area; touching edges do not count."""
    return a.x0 < b.x1 and b.x0 < a.x1 and a.y0 < b.y1 and b.y0 < a.y1
