"""Rebuild reading order and paragraphs from OCR lines, producing IR blocks.

Reading order uses the recursive XY-cut shared by all extractors
(``sugo.extractors.reading_order``); what it cannot split further is a
paragraph.

Lines of a paragraph are joined with newlines, not spaces, so nothing is lost
(a hyphen at a line end may be a real hyphen or a line-break one); language
packs decide later how to recompose them. Boxes on the same text row are joined
with a space.

Illegible lines and, in screenshots, UI-chrome lines become blocks of their
own, so unreadable areas and interface noise are never merged into readable
text (principle 4). Readable paragraphs are then typed by the detectors
(paragraph, chat message, code).

The result does not depend on the order of the input lines (principle 6).
"""

import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum, auto

from sugo.core.models import BBox, Block, BlockFlag, BlockType, Page, PageOrigin
from sugo.extractors.image.detectors import Detection, detect, is_ui_chrome, plain_text
from sugo.extractors.image.ocr_engine import OcrLine
from sugo.extractors.reading_order import text_rows, xy_cut

Group = list[OcrLine]


class _Kind(Enum):
    TEXT = auto()
    ILLEGIBLE = auto()
    CHROME = auto()


@dataclass(frozen=True)
class _Paragraph:
    kind: _Kind
    rows: tuple[tuple[OcrLine, ...], ...]

    @property
    def members(self) -> list[OcrLine]:
        return [line for row in self.rows for line in row]


def build_page(
    lines: Sequence[OcrLine],
    *,
    width: int,
    height: int,
    origin_engine: str,
    screenshot: bool = False,
    index: int = 0,
) -> Page:
    """Build an IR page from OCR lines of an image of the given pixel size."""
    return Page(
        index=index,
        width=float(width),
        height=float(height),
        origin=PageOrigin.OCR,
        blocks=build_blocks(lines, origin_engine=origin_engine, screenshot=screenshot),
    )


def build_blocks(
    lines: Sequence[OcrLine], *, origin_engine: str, screenshot: bool = False
) -> tuple[Block, ...]:
    """Group OCR lines into typed blocks in reading order."""
    if not lines:
        return ()
    # A canonical starting order makes the result independent of the input order.
    # Every field is in the key: later sorts are stable, so any tie left here
    # would let the detector's output order leak into the document.
    ordered = sorted(lines, key=_canonical_key)
    heights = [line.bbox.y1 - line.bbox.y0 for line in ordered]
    line_height = statistics.median(heights) or max(heights) or 1.0
    paragraphs = [
        paragraph
        for group in xy_cut(ordered, line_height)
        for paragraph in _paragraphs(group, screenshot=screenshot)
    ]
    readable = [p for p in paragraphs if p.kind is _Kind.TEXT]
    detections = iter(detect([p.rows for p in readable], screenshot=screenshot))
    blocks: list[Block] = []
    for paragraph in paragraphs:
        if paragraph.kind is _Kind.ILLEGIBLE:
            detection = Detection(BlockType.PARAGRAPH, "")
        elif paragraph.kind is _Kind.CHROME:
            detection = Detection(BlockType.UI_CHROME, plain_text(paragraph.rows))
        else:
            detection = next(detections)
        blocks.append(_make_block(paragraph, detection, len(blocks), origin_engine))
    return tuple(blocks)


def _canonical_key(line: OcrLine) -> tuple[float, float, float, float, str, bool, float]:
    box = line.bbox
    return (box.y0, box.x0, box.y1, box.x1, line.text, line.illegible, line.confidence)


def _paragraphs(group: Group, *, screenshot: bool) -> list[_Paragraph]:
    """Turn a leaf of the XY-cut into paragraphs; illegible and chrome lines stand alone."""
    result: list[_Paragraph] = []
    rows: list[list[OcrLine]] = []
    last_row = -1

    def flush() -> None:
        if rows:
            result.append(_Paragraph(_Kind.TEXT, tuple(tuple(row) for row in rows)))
            rows.clear()

    for row_index, row in enumerate(text_rows(group)):
        for line in row:
            if line.illegible or (screenshot and is_ui_chrome(line)):
                flush()
                kind = _Kind.ILLEGIBLE if line.illegible else _Kind.CHROME
                result.append(_Paragraph(kind, ((line,),)))
                last_row = -1
                continue
            if row_index != last_row or not rows:
                rows.append([])
            rows[-1].append(line)
            last_row = row_index
    flush()
    return result


def _make_block(
    paragraph: _Paragraph, detection: Detection, order: int, origin_engine: str
) -> Block:
    members = paragraph.members
    return Block(
        id=f"b{order}",
        type=detection.type,
        text=detection.text,
        # The weakest line decides how far the block can be trusted.
        confidence=min(line.confidence for line in members),
        bbox=BBox(
            x0=min(line.bbox.x0 for line in members),
            y0=min(line.bbox.y0 for line in members),
            x1=max(line.bbox.x1 for line in members),
            y1=max(line.bbox.y1 for line in members),
        ),
        reading_order=order,
        speaker=detection.speaker,
        origin_engine=origin_engine,
        flags=(BlockFlag.ILLEGIBLE,) if paragraph.kind is _Kind.ILLEGIBLE else (),
    )
