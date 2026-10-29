"""Turn the text lines of a native PDF page into typed IR blocks.

Visible lines are put in reading order with the XY-cut shared by every
extractor (``sugo.extractors.reading_order``); each leaf is then split into
paragraphs where the style changes (size, bold, monospace) or a bullet starts
a new item. A paragraph becomes:

- **code** when every line is in a monospaced font; indentation, which PDFs
  express as position rather than spaces, is rebuilt from each row's offset
  in character widths;
- **a list item** when it starts with a bullet (``•``, ``◦``, ``▪``, ``‣``,
  ``●``, ``○``, ``■``, ``·``); each bullet starts a new item, and the bullet itself
  is dropped as it is structure. Dashes are not bullets: a dialogue line may
  start with one;
- **heading** when its font is at least ``PDF_HEADING_MIN_SIZE_RATIO`` times
  the body size of the page and it is short; the largest size on the page is
  level 1, the next level 2, and so on;
- **paragraph** otherwise.

Lines of a paragraph are joined with newlines, as in the image layout:
language packs decide later how to recompose them.

Hidden lines (ADR-043) never join visible text: they form one block of their
own per page, flagged ``hidden``, after the visible blocks. A cleaner then
proposes to remove it, with a reason.
"""

import statistics
from collections.abc import Sequence
from dataclasses import dataclass

from sugo.core.constants import MAX_HEADING_LEVEL, PDF_HEADING_MAX_LINES, PDF_HEADING_MIN_SIZE_RATIO
from sugo.core.models import BBox, Block, BlockFlag, BlockType, Style
from sugo.extractors.pymupdf.protocol import NativeLine
from sugo.extractors.reading_order import text_rows, xy_cut

ENGINE_NAME = "pymupdf"

_BULLETS = frozenset("•◦▪‣●○■·")
# Font sizes closer than this ratio are the same style: PDF writers round
# sizes, and subsetting can shift them by a fraction of a point.
_SAME_SIZE_RATIO = 1.1


@dataclass(frozen=True)
class _Placed:
    """A line with a position on the page, as the reading order needs."""

    line: NativeLine
    bbox: BBox


@dataclass(frozen=True)
class _Paragraph:
    lines: tuple[_Placed, ...]

    @property
    def font_size(self) -> float:
        return max(placed.line.font_size for placed in self.lines)

    @property
    def monospace(self) -> bool:
        return all(placed.line.monospace for placed in self.lines)


def build_blocks(lines: Sequence[NativeLine], *, first_id: int = 0) -> tuple[Block, ...]:
    """Typed blocks in reading order, then the page's hidden text as one block."""
    visible = [
        _Placed(line, line.bbox) for line in lines if not line.hidden and line.bbox is not None
    ]
    hidden = [line for line in lines if line.hidden or line.bbox is None]
    paragraphs = _paragraphs(visible)
    levels = _heading_levels(paragraphs, _body_size(visible))
    blocks: list[Block] = []
    for paragraph in paragraphs:
        typed = _typed(paragraph, levels)
        if typed is not None:
            block_type, text = typed
            level = levels.get(paragraph.font_size)
            blocks.append(_block(first_id + len(blocks), block_type, paragraph, text, level))
    if hidden:
        blocks.append(hidden_block(hidden, first_id + len(blocks)))
    return tuple(blocks)


def hidden_block(lines: Sequence[NativeLine], order: int) -> Block:
    """One block holding a page's hidden lines, flagged so a cleaner can remove it.

    Lines placed on the page come in reading order, then those outside it.
    """
    placed = [_Placed(line, line.bbox) for line in lines if line.bbox is not None]
    ordered = [p.line for leaf in _leaves(placed) for row in text_rows(leaf) for p in row]
    ordered += [line for line in lines if line.bbox is None]
    return Block(
        id=f"b{order}",
        type=BlockType.PARAGRAPH,
        text="\n".join(line.text.strip() for line in ordered),
        bbox=_union(placed) if placed else None,
        reading_order=order,
        origin_engine=ENGINE_NAME,
        flags=(BlockFlag.HIDDEN,),
    )


def _leaves(lines: list[_Placed]) -> list[list[_Placed]]:
    """XY-cut leaves in reading order, independent of the order lines arrive in."""
    if not lines:
        return []
    height = statistics.median(p.bbox.y1 - p.bbox.y0 for p in lines) or 1.0
    return xy_cut(sorted(lines, key=_canonical_key), height)


def _paragraphs(lines: list[_Placed]) -> list[_Paragraph]:
    result: list[_Paragraph] = []
    for leaf in _leaves(lines):
        current: list[_Placed] = []
        for row in text_rows(leaf):
            first = row[0].line
            if current and (
                not _same_style(current[-1].line, first) or first.text.lstrip()[0] in _BULLETS
            ):
                result.append(_Paragraph(tuple(current)))
                current = []
            current.extend(row)
        if current:
            result.append(_Paragraph(tuple(current)))
    return result


def _typed(paragraph: _Paragraph, levels: dict[float, int]) -> tuple[BlockType, str] | None:
    """The paragraph's block type and text, or None for a lone bullet."""
    if paragraph.monospace:
        return BlockType.CODE, _code_text(paragraph)
    text = "\n".join(_rows_text(paragraph))
    if text[0] in _BULLETS:
        item = text[1:].strip()
        return (BlockType.LIST_ITEM, item) if item else None
    if paragraph.font_size in levels:
        return BlockType.HEADING, text
    return BlockType.PARAGRAPH, text


def _rows_text(paragraph: _Paragraph) -> list[str]:
    """Text of each row; pieces on one row are joined with a space."""
    rows = text_rows(list(paragraph.lines))
    return [" ".join(p.line.text.strip() for p in row) for row in rows]


def _code_text(paragraph: _Paragraph) -> str:
    """Rows of monospaced text, indented by their offset from the leftmost row."""
    rows = text_rows(list(paragraph.lines))
    # In a monospaced font every character, spaces included, has the same width.
    char_width = statistics.median(
        (p.bbox.x1 - p.bbox.x0) / len(p.line.text) for p in paragraph.lines
    )
    left = min(row[0].bbox.x0 for row in rows)
    lines = []
    for row in rows:
        indent = round((row[0].bbox.x0 - left) / char_width) if char_width > 0 else 0
        # The first piece keeps its own leading spaces: they are indentation too.
        pieces = [row[0].line.text, *(p.line.text.strip() for p in row[1:])]
        lines.append(" " * indent + " ".join(pieces))
    return "\n".join(lines)


def _body_size(lines: list[_Placed]) -> float:
    """The font size that carries most characters on the page."""
    weights: dict[float, int] = {}
    for placed in lines:
        size = placed.line.font_size
        weights[size] = weights.get(size, 0) + len(placed.line.text.strip())
    return max(weights, key=lambda size: (weights[size], -size)) if weights else 0.0


def _heading_levels(paragraphs: list[_Paragraph], body: float) -> dict[float, int]:
    """Heading level per font size: the largest is 1, capped at Markdown's 6."""
    sizes = sorted(
        {
            p.font_size
            for p in paragraphs
            if body > 0
            and p.font_size >= body * PDF_HEADING_MIN_SIZE_RATIO
            and len(_rows_text(p)) <= PDF_HEADING_MAX_LINES
            and not p.monospace
        },
        reverse=True,
    )
    return {size: min(rank + 1, MAX_HEADING_LEVEL) for rank, size in enumerate(sizes)}


def _same_style(a: NativeLine, b: NativeLine) -> bool:
    small, large = sorted((a.font_size, b.font_size))
    return large <= small * _SAME_SIZE_RATIO and a.bold == b.bold and a.monospace == b.monospace


def _block(
    order: int,
    block_type: BlockType,
    paragraph: _Paragraph,
    text: str,
    heading_level: int | None,
) -> Block:
    lines = [p.line for p in paragraph.lines]
    main = max(lines, key=lambda line: len(line.text.strip()))
    return Block(
        id=f"b{order}",
        type=block_type,
        text=text,
        bbox=_union(list(paragraph.lines)),
        style=Style(
            font_size=main.font_size,
            bold=all(line.bold for line in lines),
            monospace=paragraph.monospace,
        ),
        heading_level=heading_level if block_type is BlockType.HEADING else None,
        reading_order=order,
        origin_engine=ENGINE_NAME,
    )


def _union(lines: list[_Placed]) -> BBox:
    return BBox(
        x0=min(p.bbox.x0 for p in lines),
        y0=min(p.bbox.y0 for p in lines),
        x1=max(p.bbox.x1 for p in lines),
        y1=max(p.bbox.y1 for p in lines),
    )


def _canonical_key(p: _Placed) -> tuple[float, float, float, float, str, float, bool, bool]:
    # Every field is in the key, so the order never depends on the worker's.
    box, line = p.bbox, p.line
    return (box.y0, box.x0, box.y1, box.x1, line.text, line.font_size, line.bold, line.monospace)
