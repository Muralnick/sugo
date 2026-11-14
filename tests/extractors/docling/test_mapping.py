"""Tests for the mapping of Docling's JSON to IR pages (ADR-071 §5).

The documents are small hand-made copies of Docling's export format, so
these tests need neither Docling nor PyTorch.
"""

from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from sugo.core.models import BlockType
from sugo.extractors.docling.mapping import to_pages
from sugo.serializers.markdown import render

CJK_SPACE = "中" + " " + "文"


def prov(page: int, top: float = 700.0) -> list[dict[str, Any]]:
    box = {"l": 72.0, "t": top, "r": 300.0, "b": top - 12, "coord_origin": "BOTTOMLEFT"}
    return [{"page_no": page, "bbox": box, "charspan": [0, 1]}]


def text(n: int, label: str, value: str, page: int = 1, **extra: Any) -> dict[str, Any]:
    return {"self_ref": f"#/texts/{n}", "label": label, "text": value, "prov": prov(page), **extra}


def ref(path: str) -> dict[str, str]:
    return {"$ref": path}


def cell(row: int, col: int, value: str, *, header: bool = False, rows: int = 1) -> dict[str, Any]:
    return {
        "start_row_offset_idx": row,
        "end_row_offset_idx": row + rows,
        "start_col_offset_idx": col,
        "end_col_offset_idx": col + 1,
        "text": value,
        "column_header": header,
    }


def document() -> dict[str, Any]:
    texts = [
        text(0, "title", "Annual report"),
        text(1, "section_header", "Results", level=1),
        text(2, "text", "Sales grew."),
        text(3, "list_item", "first"),
        text(4, "list_item", "nested"),
        text(5, "page_header", "ACME Corp"),
        text(6, "page_footer", "Page 2", page=2),
        text(7, "caption", "Table 1: sales"),
        text(8, "text", "On the second page.", page=2),
        text(9, "checkbox_selected", "approved"),
        text(10, "text", CJK_SPACE),
    ]
    table = {
        "self_ref": "#/tables/0",
        "label": "table",
        "prov": prov(1, 500),
        "data": {
            "num_rows": 3,
            "num_cols": 2,
            "table_cells": [
                cell(0, 0, "Region", header=True),
                cell(0, 1, "Q1", header=True),
                cell(1, 0, "North", rows=2),
                cell(1, 1, "10"),
                cell(2, 1, "12"),
                cell(1, 1, "overlaps"),  # dropped: the place is taken
                cell(5, 0, "outside"),  # dropped: past the grid
            ],
        },
    }
    groups = [
        {
            "self_ref": "#/groups/0",
            "label": "list",
            "children": [ref("#/texts/3"), ref("#/groups/1")],
        },
        {"self_ref": "#/groups/1", "label": "list", "children": [ref("#/texts/4")]},
    ]
    return {
        "body": {
            "self_ref": "#/body",
            "children": [
                ref("#/texts/0"),
                ref("#/texts/1"),
                ref("#/texts/2"),
                ref("#/groups/0"),
                ref("#/texts/7"),
                ref("#/tables/0"),
                ref("#/pictures/0"),
                ref("#/texts/9"),
                ref("#/texts/10"),
                ref("#/texts/8"),
                ref("#/texts/99"),  # does not exist
                ref("#/texts/2"),  # seen already: never twice
                {"$ref": "../../etc/passwd"},
            ],
        },
        "furniture": {"self_ref": "#/furniture", "children": [ref("#/texts/5"), ref("#/texts/6")]},
        "texts": texts,
        "tables": [table],
        "pictures": [{"self_ref": "#/pictures/0", "label": "picture", "prov": prov(1, 300)}],
        "groups": groups,
        "pages": {
            "1": {"size": {"width": 600, "height": 800}},
            "2": {"size": {"width": 600, "height": 800}},
        },
    }


def test_blocks_keep_docling_types_and_reading_order() -> None:
    first, second = to_pages(document(), page_count=2)
    kinds = [(b.type, b.text) for b in first.blocks]
    assert kinds == [
        (BlockType.HEADER, "ACME Corp"),
        (BlockType.HEADING, "Annual report"),
        (BlockType.HEADING, "Results"),
        (BlockType.PARAGRAPH, "Sales grew."),
        (BlockType.LIST_ITEM, "first"),
        (BlockType.LIST_ITEM, "nested"),
        (BlockType.CAPTION, "Table 1: sales"),
        (BlockType.TABLE, ""),
        (BlockType.IMAGE, ""),
        (BlockType.PARAGRAPH, "[x] approved"),
        (BlockType.PARAGRAPH, "中\n文"),
    ]
    assert [b.heading_level for b in first.blocks[1:3]] == [1, 2]
    assert [b.list_level for b in first.blocks[4:6]] == [0, 1]
    assert [b.reading_order for b in first.blocks] == list(range(len(first.blocks)))
    assert len({b.id for b in first.blocks}) == len(first.blocks)
    assert [(b.type, b.text) for b in second.blocks] == [
        (BlockType.PARAGRAPH, "On the second page."),
        (BlockType.FOOTER, "Page 2"),
    ]
    assert (first.width, first.height) == (600, 800)


def test_tables_keep_their_grid_and_header() -> None:
    table = next(b for b in to_pages(document(), page_count=2)[0].blocks if b.table)
    assert table.table is not None
    assert (table.table.n_rows, table.table.n_cols, table.table.header_rows) == (3, 2, 1)
    assert [c.text for c in table.table.cells] == ["Region", "Q1", "North", "10", "12"]
    assert render([table]).splitlines()[0] == "Region|Q1"


def test_boxes_are_turned_top_down_and_kept_on_the_page() -> None:
    header = to_pages(document(), page_count=2)[0].blocks[0]
    assert header.bbox is not None
    assert round(header.bbox.y0, 3) == round(100 / 800, 3)
    assert header.bbox.y0 < header.bbox.y1 <= 1


def test_items_without_a_page_and_unknown_pages_go_on_the_first() -> None:
    doc = {
        "body": {"children": [ref("#/texts/0"), ref("#/texts/1")]},
        "texts": [
            {"self_ref": "#/texts/0", "label": "text", "text": "no prov"},
            {"self_ref": "#/texts/1", "label": "text", "text": "page 9", "prov": prov(9)},
        ],
    }
    (page,) = to_pages(doc, page_count=1)
    assert [b.text for b in page.blocks] == ["no prov", "page 9"]
    assert (page.width, page.height) == (595.0, 842.0)


def test_a_cycle_of_groups_ends() -> None:
    doc = {
        "body": {"children": [ref("#/groups/0")]},
        "groups": [
            {"self_ref": "#/groups/0", "label": "list", "children": [ref("#/groups/1")]},
            {"self_ref": "#/groups/1", "label": "list", "children": [ref("#/groups/0")]},
        ],
    }
    assert to_pages(doc, page_count=1)[0].blocks == ()


_JUNK = st.recursive(
    st.none() | st.booleans() | st.integers() | st.floats() | st.text(max_size=8),
    lambda inner: (
        st.lists(inner, max_size=4) | st.dictionaries(st.text(max_size=8), inner, max_size=4)
    ),
    max_leaves=30,
)


_FIELDS = st.fixed_dictionaries(
    {},
    optional={
        "label": st.sampled_from(["text", "table", "section_header", "list_item", "page_header"])
        | _JUNK,
        "text": _JUNK,
        "level": _JUNK,
        "prov": st.lists(st.fixed_dictionaries({}, optional={"page_no": _JUNK, "bbox": _JUNK}))
        | _JUNK,
        "data": st.fixed_dictionaries(
            {},
            optional={
                "num_rows": _JUNK | st.integers(-2, 5),
                "num_cols": _JUNK | st.integers(-2, 5),
                "table_cells": st.lists(_JUNK, max_size=6),
            },
        )
        | _JUNK,
        "children": _JUNK,
    },
)


@settings(max_examples=300)
@given(_FIELDS, _FIELDS, _JUNK)
def test_any_json_gives_valid_pages(
    item: dict[str, Any], table: dict[str, Any], pages: object
) -> None:
    """Whatever Docling sends, the mapping never raises and makes only valid IR."""
    doc = {
        "body": {"children": [ref("#/texts/0"), ref("#/tables/0")]},
        "texts": [{**item, "self_ref": "#/texts/0"}],
        "tables": [{**table, "self_ref": "#/tables/0"}],
        "pages": pages,
    }
    assert len(to_pages(doc, page_count=2)) == 2
