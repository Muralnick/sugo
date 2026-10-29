"""Reading order of text boxes on a page, shared by every extractor.

A recursive XY-cut: the region is split at the widest horizontal whitespace
bands (between paragraphs), then at vertical ones (between columns), and each
part is processed the same way, top to bottom and left to right. What cannot
be split further is a leaf, usually a paragraph or a column fragment.

Works on anything with a normalised ``bbox``: OCR lines from images, text
lines from PDFs.
"""

from typing import Protocol

from sugo.core.constants import LAYOUT_COLUMN_GAP, LAYOUT_PARAGRAPH_GAP, LAYOUT_SAME_ROW_OVERLAP
from sugo.core.models import BBox


class Boxed(Protocol):
    """Something placed on a page."""

    @property
    def bbox(self) -> BBox:
        """Position on the page, normalised to 0-1."""
        ...


def xy_cut[T: Boxed](items: list[T], line_height: float) -> list[list[T]]:
    """Split boxes at whitespace bands, recursively, in reading order."""
    if len(items) <= 1:
        return [items]
    by_rows = _split(items, line_height * LAYOUT_PARAGRAPH_GAP, vertical=True)
    if len(by_rows) > 1:
        return [leaf for part in by_rows for leaf in xy_cut(part, line_height)]
    by_columns = _split(items, line_height * LAYOUT_COLUMN_GAP, vertical=False)
    if len(by_columns) > 1:
        return [leaf for part in by_columns for leaf in xy_cut(part, line_height)]
    return [items]


def text_rows[T: Boxed](items: list[T]) -> list[list[T]]:
    """Group boxes into text rows (vertical overlap), each sorted left to right."""
    result: list[list[T]] = []
    for item in sorted(items, key=lambda item: (item.bbox.y0, item.bbox.x0)):
        row = result[-1] if result else None
        if row is not None and _same_row(row[0], item):
            row.append(item)
        else:
            result.append([item])
    return [sorted(row, key=lambda item: (item.bbox.x0, item.bbox.y0)) for row in result]


def _split[T: Boxed](items: list[T], min_gap: float, *, vertical: bool) -> list[list[T]]:
    """Split boxes at gaps wider than ``min_gap`` along one axis, in axis order."""

    def span(item: T) -> tuple[float, float]:
        box = item.bbox
        return (box.y0, box.y1) if vertical else (box.x0, box.x1)

    groups: list[list[T]] = []
    end = float("-inf")
    for item in sorted(items, key=lambda item: (*span(item), item.bbox.x0, item.bbox.y0)):
        start, stop = span(item)
        if not groups or start - end > min_gap:
            groups.append([])
        groups[-1].append(item)
        end = max(end, stop)
    return groups


def _same_row(a: Boxed, b: Boxed) -> bool:
    overlap = min(a.bbox.y1, b.bbox.y1) - max(a.bbox.y0, b.bbox.y0)
    shorter = min(a.bbox.y1 - a.bbox.y0, b.bbox.y1 - b.bbox.y0)
    return shorter > 0 and overlap > LAYOUT_SAME_ROW_OVERLAP * shorter
