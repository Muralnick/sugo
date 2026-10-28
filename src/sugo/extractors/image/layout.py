"""Rebuild reading order and paragraphs from OCR lines, producing IR blocks.

Reading order uses a recursive XY-cut: the region is split at the widest
horizontal whitespace bands (between paragraphs), then at vertical ones
(between columns), and each part is processed the same way, top to bottom and
left to right. What cannot be split further is a paragraph.

Lines of a paragraph are joined with newlines, not spaces, so nothing is lost
(a hyphen at a line end may be a real hyphen or a line-break one); language
packs decide later how to recompose them. Boxes on the same text row are joined
with a space.

Illegible lines become blocks of their own, flagged and without text, so
unreadable areas are never merged into readable text (principle 4).

The result does not depend on the order of the input lines (principle 6).
"""

import statistics
from collections.abc import Sequence

from sugo.core.constants import LAYOUT_COLUMN_GAP, LAYOUT_PARAGRAPH_GAP, LAYOUT_SAME_ROW_OVERLAP
from sugo.core.models import BBox, Block, BlockFlag, BlockType, Page, PageOrigin
from sugo.extractors.image.ocr_engine import OcrLine

Group = list[OcrLine]


def build_page(
    lines: Sequence[OcrLine], *, width: int, height: int, origin_engine: str, index: int = 0
) -> Page:
    """Build an IR page from OCR lines of an image of the given pixel size."""
    return Page(
        index=index,
        width=float(width),
        height=float(height),
        origin=PageOrigin.OCR,
        blocks=build_blocks(lines, origin_engine=origin_engine),
    )


def build_blocks(lines: Sequence[OcrLine], *, origin_engine: str) -> tuple[Block, ...]:
    """Group OCR lines into paragraph blocks in reading order."""
    if not lines:
        return ()
    # A canonical starting order makes the result independent of the input order.
    # Every field is in the key: later sorts are stable, so any tie left here
    # would let the detector's output order leak into the document.
    ordered = sorted(lines, key=_canonical_key)
    heights = [line.bbox.y1 - line.bbox.y0 for line in ordered]
    line_height = statistics.median(heights) or max(heights) or 1.0
    blocks: list[Block] = []
    for group in _xy_cut(ordered, line_height):
        for members, text in _paragraphs(group):
            blocks.append(_make_block(members, text, len(blocks), origin_engine))
    return tuple(blocks)


def _canonical_key(line: OcrLine) -> tuple[float, float, float, float, str, bool, float]:
    box = line.bbox
    return (box.y0, box.x0, box.y1, box.x1, line.text, line.illegible, line.confidence)


def _xy_cut(lines: Group, line_height: float) -> list[Group]:
    """Split lines at whitespace bands, recursively, in reading order."""
    if len(lines) <= 1:
        return [lines]
    by_rows = _split(lines, line_height * LAYOUT_PARAGRAPH_GAP, vertical=True)
    if len(by_rows) > 1:
        return [leaf for part in by_rows for leaf in _xy_cut(part, line_height)]
    by_columns = _split(lines, line_height * LAYOUT_COLUMN_GAP, vertical=False)
    if len(by_columns) > 1:
        return [leaf for part in by_columns for leaf in _xy_cut(part, line_height)]
    return [lines]


def _split(lines: Group, min_gap: float, *, vertical: bool) -> list[Group]:
    """Split lines at gaps wider than ``min_gap`` along one axis, in axis order."""

    def span(line: OcrLine) -> tuple[float, float]:
        box = line.bbox
        return (box.y0, box.y1) if vertical else (box.x0, box.x1)

    groups: list[Group] = []
    end = float("-inf")
    for line in sorted(lines, key=lambda line: (*span(line), line.bbox.x0, line.bbox.y0)):
        start, stop = span(line)
        if not groups or start - end > min_gap:
            groups.append([])
        groups[-1].append(line)
        end = max(end, stop)
    return groups


def _paragraphs(group: Group) -> list[tuple[Group, str]]:
    """Turn a leaf of the XY-cut into paragraphs; illegible lines stand alone."""
    result: list[tuple[Group, str]] = []
    members: Group = []
    rows: list[list[str]] = []
    last_row = -1

    def flush() -> None:
        if members:
            result.append((list(members), "\n".join(" ".join(row) for row in rows)))
            members.clear()
            rows.clear()

    for row_index, row in enumerate(_rows(group)):
        for line in row:
            if line.illegible:
                flush()
                result.append(([line], ""))
                last_row = -1
                continue
            if row_index != last_row or not rows:
                rows.append([])
            rows[-1].append(line.text)
            members.append(line)
            last_row = row_index
    flush()
    return result


def _rows(group: Group) -> list[Group]:
    """Group lines into text rows (vertical overlap), each sorted left to right."""
    rows: list[Group] = []
    for line in sorted(group, key=lambda line: (line.bbox.y0, line.bbox.x0)):
        row = rows[-1] if rows else None
        if row is not None and _same_row(row[0], line):
            row.append(line)
        else:
            rows.append([line])
    return [sorted(row, key=lambda line: (line.bbox.x0, line.bbox.y0)) for row in rows]


def _same_row(a: OcrLine, b: OcrLine) -> bool:
    overlap = min(a.bbox.y1, b.bbox.y1) - max(a.bbox.y0, b.bbox.y0)
    shorter = min(a.bbox.y1 - a.bbox.y0, b.bbox.y1 - b.bbox.y0)
    return shorter > 0 and overlap > LAYOUT_SAME_ROW_OVERLAP * shorter


def _make_block(members: Group, text: str, order: int, origin_engine: str) -> Block:
    illegible = all(line.illegible for line in members)
    return Block(
        id=f"b{order}",
        type=BlockType.PARAGRAPH,
        text=text,
        # The weakest line decides how far the block can be trusted.
        confidence=min(line.confidence for line in members),
        bbox=BBox(
            x0=min(line.bbox.x0 for line in members),
            y0=min(line.bbox.y0 for line in members),
            x1=max(line.bbox.x1 for line in members),
            y1=max(line.bbox.y1 for line in members),
        ),
        reading_order=order,
        origin_engine=origin_engine,
        flags=(BlockFlag.ILLEGIBLE,) if illegible else (),
    )
