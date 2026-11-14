"""Turn Docling's JSON export into Sugo's IR pages (ADR-071 §5).

Docling describes a document as a tree: ``body`` (the content, in reading
order) and ``furniture`` (page headers and footers), whose nodes point at
texts, tables, pictures and groups by ``$ref``. Each item says on which page
it sits and where (``prov``). This module walks both trees and makes one IR
block per item, page by page.

It runs inside the Docling worker on what Docling produced from an
untrusted file, so it trusts nothing: a reference that does not resolve, a
cycle, a box outside the page or a table cell outside its grid is skipped or
clamped, never followed blindly, and the walk is bounded. Sugo validates the
pages again when they arrive (ADR-037).

Between two Chinese or Japanese characters, the space Docling puts where a
line ended becomes a line break again, as ``lite`` would have it.

Docling's page header and footer labels become ``header`` and ``footer``
blocks, the same types Sugo's own Office reader gives declared headers; the
cleaners decide what to remove (ADR-007: cleaning is identical at every
level).
"""

import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any

from sugo.core.constants import MAX_HEADING_LEVEL, MAX_LIST_LEVEL
from sugo.core.models import (
    BBox,
    Block,
    BlockType,
    Page,
    PageOrigin,
    Table,
    TableCell,
)
from sugo.core.text import CJK_CHARS

ENGINE_NAME = "docling"
# More items than any document Sugo accepts can hold; a walk past this stops.
MAX_ITEMS = 1_000_000
# Docling labels and the IR block types they become; anything else is a paragraph.
_TYPES = {
    "title": BlockType.HEADING,
    "section_header": BlockType.HEADING,
    "list_item": BlockType.LIST_ITEM,
    "caption": BlockType.CAPTION,
    "footnote": BlockType.FOOTNOTE,
    "formula": BlockType.FORMULA,
    "code": BlockType.CODE,
    "page_header": BlockType.HEADER,
    "page_footer": BlockType.FOOTER,
    "picture": BlockType.IMAGE,
    "chart": BlockType.IMAGE,
    "table": BlockType.TABLE,
    "document_index": BlockType.TABLE,
}
_CHECKBOX = {"checkbox_selected": "[x] ", "checkbox_unselected": "[ ] "}
_LIST_GROUPS = frozenset({"list", "ordered_list"})
# Docling joins the lines of a paragraph with a space. Between two CJK
# characters that space was a line break: written back as one, it gets the
# same treatment as in lite (ADR-069), kept or joined by the language rules.
_CJK_LINE_SPACE = re.compile(f"(?<=[{CJK_CHARS}]) (?=[{CJK_CHARS}])")
_NEWLINE = chr(10)
# A4 in points, for an item on a page Docling did not size.
_DEFAULT_SIZE = (595.0, 842.0)


@dataclass
class _Walk:
    doc: Mapping[str, Any]
    seen: set[str] = field(default_factory=set)
    count: int = 0


def to_pages(doc: Mapping[str, Any], *, page_count: int) -> list[Page]:
    """The IR pages of a Docling document; items without a page go on the first.

    Args:
        doc: Docling's ``export_to_dict()`` output.
        page_count: How many pages the source has; at least one page is made.
    """
    count = max(page_count, 1)
    sizes = {index: _page_size(doc, index) for index in range(count)}
    body: dict[int, list[Block]] = {index: [] for index in range(count)}
    tops: dict[int, list[Block]] = {index: [] for index in range(count)}
    bottoms: dict[int, list[Block]] = {index: [] for index in range(count)}
    walk = _Walk(doc)
    for root in ("body", "furniture"):
        node = doc.get(root)
        if not isinstance(node, Mapping):
            continue
        for item, list_level in _items(walk, node, list_level=-1):
            index = _page_index(item, count)
            block = _block(item, list_level, sizes[index])
            if block is None:
                continue
            if root == "body":
                body[index].append(block)
            elif block.type is BlockType.HEADER:
                tops[index].append(block)
            else:
                bottoms[index].append(block)
    return [
        Page(
            index=index,
            width=sizes[index][0],
            height=sizes[index][1],
            origin=PageOrigin.NATIVE,
            blocks=_numbered(index, [*tops[index], *body[index], *bottoms[index]]),
        )
        for index in range(count)
    ]


def _items(
    walk: _Walk, node: Mapping[str, Any], *, list_level: int
) -> Iterator[tuple[Mapping[str, Any], int]]:
    """The items under ``node`` in document order, with their list depth."""
    stack: list[tuple[Mapping[str, Any], int]] = [(node, list_level)]
    while stack and walk.count < MAX_ITEMS:
        current, level = stack.pop()
        walk.count += 1
        children = current.get("children")
        is_list = _label(current) in _LIST_GROUPS
        if _is_item(current):
            yield current, level
        nested = level + 1 if is_list else level
        resolved = []
        for child in children if isinstance(children, list) else []:
            target = _resolve(walk, child)
            if target is not None:
                resolved.append((target, nested))
        # Reversed, so the first child is visited first.
        stack.extend(reversed(resolved))


def _label(node: Mapping[str, Any]) -> str:
    label = node.get("label")
    return label if isinstance(label, str) else ""


def _is_item(node: Mapping[str, Any]) -> bool:
    ref = node.get("self_ref")
    return isinstance(ref, str) and ref.startswith(("#/texts/", "#/tables/", "#/pictures/"))


def _resolve(walk: _Walk, child: object) -> Mapping[str, Any] | None:
    """The node a ``{"$ref": "#/kind/n"}`` points at, once; None if it does not exist."""
    if not isinstance(child, Mapping):
        return None
    ref = child.get("$ref")
    if not isinstance(ref, str) or ref in walk.seen:
        return None
    parts = ref.split("/")
    if len(parts) != 3 or parts[0] != "#" or not parts[2].isdigit():  # noqa: PLR2004
        return None
    collection = walk.doc.get(parts[1])
    index = int(parts[2])
    if not isinstance(collection, list) or index >= len(collection):
        return None
    target = collection[index]
    if not isinstance(target, Mapping):
        return None
    walk.seen.add(ref)
    return target


def _page_size(doc: Mapping[str, Any], index: int) -> tuple[float, float]:
    pages = doc.get("pages")
    page = pages.get(str(index + 1)) if isinstance(pages, Mapping) else None
    size = page.get("size") if isinstance(page, Mapping) else None
    if isinstance(size, Mapping):
        width, height = _number(size.get("width")), _number(size.get("height"))
        if width and height and width > 0 and height > 0:
            return width, height
    return _DEFAULT_SIZE


def _page_index(item: Mapping[str, Any], count: int) -> int:
    prov = _first_prov(item)
    page_no = prov.get("page_no") if prov else None
    if isinstance(page_no, int) and 1 <= page_no <= count:
        return page_no - 1
    return 0


def _first_prov(item: Mapping[str, Any]) -> Mapping[str, Any] | None:
    prov = item.get("prov")
    if isinstance(prov, list) and prov and isinstance(prov[0], Mapping):
        return prov[0]
    return None


def _block(item: Mapping[str, Any], list_level: int, size: tuple[float, float]) -> Block | None:
    """The block of one item, with a provisional id; None if it shows nothing."""
    label = _label(item)
    kind = _TYPES.get(label, BlockType.PARAGRAPH)
    block_id = "pending"
    bbox = _bbox(_first_prov(item), size)
    if kind is BlockType.TABLE:
        table = _table(item.get("data"))
        if table is None:
            return None
        return Block(id=block_id, type=kind, table=table, bbox=bbox, origin_engine=ENGINE_NAME)
    text = item.get("text")
    text = text if isinstance(text, str) else ""
    text = _CJK_LINE_SPACE.sub(_NEWLINE, text)
    if label in _CHECKBOX:
        text = _CHECKBOX[label] + text
    if kind is BlockType.IMAGE:
        # Words drawn inside a picture are its own children, walked as items.
        return Block(id=block_id, type=kind, bbox=bbox, origin_engine=ENGINE_NAME)
    if not text.strip():
        return None
    heading = None
    if kind is BlockType.HEADING:
        level = item.get("level")
        depth = level if isinstance(level, int) and level >= 1 else 1
        # A title is the top level; sections sit below it.
        heading = 1 if label == "title" else min(depth + 1, MAX_HEADING_LEVEL)
    nesting = None
    if kind is BlockType.LIST_ITEM:
        nesting = min(max(list_level, 0), MAX_LIST_LEVEL)
    return Block(
        id=block_id,
        type=kind,
        text=text,
        bbox=bbox,
        heading_level=heading,
        list_level=nesting,
        origin_engine=ENGINE_NAME,
    )


def _bbox(prov: Mapping[str, Any] | None, size: tuple[float, float]) -> BBox | None:
    box = prov.get("bbox") if prov else None
    if not isinstance(box, Mapping):
        return None
    left, top, right, bottom = (_number(box.get(key)) for key in ("l", "t", "r", "b"))
    if left is None or top is None or right is None or bottom is None:
        return None
    width, height = size
    if box.get("coord_origin") == "BOTTOMLEFT":
        top, bottom = height - top, height - bottom
    x0, x1 = sorted((_unit(left / width), _unit(right / width)))
    y0, y1 = sorted((_unit(top / height), _unit(bottom / height)))
    return BBox(x0=x0, y0=y0, x1=x1, y1=y1)


def _table(data: object) -> Table | None:
    """A table grid from Docling's cells; overlapping or out-of-grid cells are dropped."""
    if not isinstance(data, Mapping):
        return None
    rows, cols = data.get("num_rows"), data.get("num_cols")
    raw = data.get("table_cells")
    if not isinstance(rows, int) or not isinstance(cols, int) or rows < 1 or cols < 1:
        return None
    occupied: set[tuple[int, int]] = set()
    cells: list[TableCell] = []
    header_rows = rows
    for cell in raw if isinstance(raw, list) else []:
        if not isinstance(cell, Mapping):
            continue
        span = _span(cell)
        if span is None:
            continue
        row, row_end, col, col_end = span
        if not (0 <= row < row_end <= rows and 0 <= col < col_end <= cols):
            continue
        area = {(r, c) for r in range(row, row_end) for c in range(col, col_end)}
        if area & occupied:
            continue
        occupied |= area
        text = cell.get("text")
        cells.append(
            TableCell(
                row=row,
                col=col,
                text=text if isinstance(text, str) else "",
                row_span=row_end - row,
                col_span=col_end - col,
            )
        )
        if not cell.get("column_header"):
            header_rows = min(header_rows, row)
    if not cells:
        return None
    return Table(
        n_rows=rows,
        n_cols=cols,
        header_rows=header_rows if header_rows < rows else 0,
        cells=tuple(cells),
    )


def _span(cell: Mapping[str, Any]) -> tuple[int, int, int, int] | None:
    """A cell's first and past-the-end row and column, if all four are whole numbers."""
    keys = (
        "start_row_offset_idx",
        "end_row_offset_idx",
        "start_col_offset_idx",
        "end_col_offset_idx",
    )
    values = [cell.get(key) for key in keys]
    numbers = [v for v in values if isinstance(v, int) and not isinstance(v, bool)]
    if len(numbers) != len(keys):
        return None
    row, row_end, col, col_end = numbers
    return row, row_end, col, col_end


def _numbered(page: int, blocks: list[Block]) -> tuple[Block, ...]:
    """The page's blocks with their ids and reading order: Docling's order."""
    return tuple(
        block.model_validate({**block.model_dump(), "id": f"p{page}-d{n}", "reading_order": n})
        for n, block in enumerate(blocks)
    )


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    return number if number == number and abs(number) != float("inf") else None


def _unit(value: float) -> float:
    return min(max(value, 0.0), 1.0)
