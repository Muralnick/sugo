"""Unit tests for the IR models in sugo.core.models."""

from typing import Any

import pytest
from pydantic import ValidationError

from sugo.core.models import (
    BBox,
    Block,
    BlockFlag,
    BlockType,
    ChatSide,
    Document,
    DocumentSource,
    Page,
    PageOrigin,
    Table,
    TableCell,
    TimeRange,
)


def make_block(**overrides: Any) -> Block:
    fields: dict[str, Any] = {
        "id": "b1",
        "type": BlockType.PARAGRAPH,
        "text": "Hello",
        "origin_engine": "pymupdf",
    }
    return Block(**(fields | overrides))


class TestBBox:
    def test_accepts_corners_inside_unit_square(self) -> None:
        box = BBox(x0=0.0, y0=0.1, x1=1.0, y1=0.9)
        assert (box.x0, box.y1) == (0.0, 0.9)

    def test_accepts_degenerate_box_with_zero_area(self) -> None:
        BBox(x0=0.5, y0=0.5, x1=0.5, y1=0.5)

    @pytest.mark.parametrize("value", [-0.01, 1.01])
    def test_rejects_coordinates_outside_unit_interval(self, value: float) -> None:
        with pytest.raises(ValidationError):
            BBox(x0=value, y0=0.0, x1=1.0, y1=1.0)

    def test_rejects_inverted_corners(self) -> None:
        with pytest.raises(ValidationError, match="x0 <= x1"):
            BBox(x0=0.8, y0=0.0, x1=0.2, y1=1.0)


class TestTimeRange:
    def test_rejects_end_before_start(self) -> None:
        with pytest.raises(ValidationError, match="start <= end"):
            TimeRange(start=5.0, end=1.0)


class TestTable:
    def test_accepts_grid_with_spanning_header(self) -> None:
        table = Table(
            n_rows=2,
            n_cols=2,
            header_rows=1,
            cells=(
                TableCell(row=0, col=0, text="Title", col_span=2),
                TableCell(row=1, col=0, text="a"),
                TableCell(row=1, col=1, text="b"),
            ),
        )
        assert table.cells[0].col_span == 2

    def test_rejects_cell_outside_grid(self) -> None:
        with pytest.raises(ValidationError, match="outside the grid"):
            Table(n_rows=1, n_cols=1, cells=(TableCell(row=0, col=0, col_span=2),))

    def test_rejects_overlapping_cells(self) -> None:
        with pytest.raises(ValidationError, match="overlap"):
            Table(
                n_rows=2,
                n_cols=2,
                cells=(TableCell(row=0, col=0, row_span=2), TableCell(row=1, col=0)),
            )

    def test_rejects_more_header_rows_than_rows(self) -> None:
        with pytest.raises(ValidationError, match="header_rows"):
            Table(n_rows=1, n_cols=1, header_rows=2, cells=())


class TestBlock:
    def test_is_immutable(self) -> None:
        block = make_block()
        with pytest.raises(ValidationError):
            block.text = "changed"  # type: ignore[misc]

    def test_rejects_unknown_fields(self) -> None:
        with pytest.raises(ValidationError):
            make_block(colour="red")

    def test_rejects_unknown_block_type(self) -> None:
        with pytest.raises(ValidationError):
            make_block(type="banner")

    def test_does_not_coerce_numbers_into_text(self) -> None:
        # Strict mode: an extractor bug that passes a number must fail loudly.
        with pytest.raises(ValidationError):
            make_block(text=42)

    def test_requires_origin_engine(self) -> None:
        with pytest.raises(ValidationError):
            Block(id="b1", type=BlockType.PARAGRAPH)  # type: ignore[call-arg]

    def test_sorts_and_deduplicates_flags(self) -> None:
        block = make_block(
            flags=(
                BlockFlag.SUSPICIOUS_INSTRUCTION,
                BlockFlag.LOW_AGREEMENT,
                BlockFlag.LOW_AGREEMENT,
            )
        )
        assert block.flags == (BlockFlag.LOW_AGREEMENT, BlockFlag.SUSPICIOUS_INSTRUCTION)

    def test_accepts_heading_level_on_heading(self) -> None:
        assert make_block(type=BlockType.HEADING, heading_level=2).heading_level == 2

    def test_rejects_heading_level_on_paragraph(self) -> None:
        with pytest.raises(ValidationError, match="heading_level"):
            make_block(heading_level=2)

    @pytest.mark.parametrize("level", [0, 7])
    def test_rejects_heading_level_outside_markdown_range(self, level: int) -> None:
        with pytest.raises(ValidationError):
            make_block(type=BlockType.HEADING, heading_level=level)

    def test_rejects_table_on_non_table_block(self) -> None:
        with pytest.raises(ValidationError, match="table"):
            make_block(table=Table(n_rows=1, n_cols=1, cells=()))

    def test_accepts_speaker_on_chat_message(self) -> None:
        block = make_block(type=BlockType.CHAT_MESSAGE, speaker=ChatSide.RIGHT)
        assert block.speaker is ChatSide.RIGHT

    def test_rejects_speaker_on_paragraph(self) -> None:
        with pytest.raises(ValidationError, match="speaker"):
            make_block(speaker=ChatSide.LEFT)

    @pytest.mark.parametrize("script", ["latin", "han-kana", "hangul"])
    def test_accepts_script_identifiers(self, script: str) -> None:
        assert make_block(script=script).script == script

    @pytest.mark.parametrize("script", ["Latin", "han_kana", "", "-latin"])
    def test_rejects_malformed_script_identifiers(self, script: str) -> None:
        with pytest.raises(ValidationError):
            make_block(script=script)

    def test_rejects_removal_fields_on_kept_block(self) -> None:
        with pytest.raises(ValidationError, match="only allowed on removed"):
            make_block(removed_by="page_numbers")

    def test_mark_removed_keeps_content_and_records_reason(self) -> None:
        block = make_block(text="Page 3")
        removed = block.mark_removed("page_numbers", "isolated page number")
        assert removed.removed
        assert (removed.removed_by, removed.reason) == ("page_numbers", "isolated page number")
        assert removed.text == "Page 3"
        assert not block.removed, "the original block must be left untouched"

    def test_mark_removed_twice_is_rejected(self) -> None:
        removed = make_block().mark_removed("c", "r")
        with pytest.raises(ValueError, match="already removed"):
            removed.mark_removed("c", "r")


class TestPage:
    def test_rejects_rotation_outside_quarter_turns(self) -> None:
        with pytest.raises(ValidationError, match="rotation"):
            Page(index=0, width=100.0, height=100.0, rotation=45, origin=PageOrigin.NATIVE)

    @pytest.mark.parametrize("dimension", ["width", "height"])
    def test_rejects_non_positive_dimensions(self, dimension: str) -> None:
        fields: dict[str, Any] = {"index": 0, "width": 10.0, "height": 10.0, "origin": "ocr"}
        with pytest.raises(ValidationError):
            Page(**(fields | {dimension: 0.0}))

    def test_rejects_duplicate_block_ids(self) -> None:
        with pytest.raises(ValidationError, match="unique"):
            Page(
                index=0,
                width=100.0,
                height=100.0,
                origin=PageOrigin.OCR,
                blocks=(make_block(), make_block()),
            )


class TestDocumentSource:
    def test_accepts_container_entry(self) -> None:
        document = Document(
            source=DocumentSource(
                location="clients.zip",
                container_path="2025/agreement.pdf",
                media_type="application/pdf",
                sha256="ab" * 32,
                page_count=12,
                languages=("it",),
            )
        )
        assert document.source.container_path == "2025/agreement.pdf"

    @pytest.mark.parametrize("digest", ["ab" * 31, "AB" * 32, "zz" * 32])
    def test_rejects_malformed_sha256(self, digest: str) -> None:
        with pytest.raises(ValidationError):
            DocumentSource(location="a.png", media_type="image/png", sha256=digest, page_count=1)
