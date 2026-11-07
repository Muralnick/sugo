"""Tests for the exporters: atomic writes, front matter, JSONL lines and the published schema."""

import json
import os
import stat
from collections.abc import Iterator
from pathlib import Path

import pytest

from sugo.core.chunks import Chunk, chunk_json_schema
from sugo.core.models import BlockType
from sugo.core.receipt import Receipt, RemovalRecord, receipt_json_schema
from sugo.exporters.files import write_text_atomic
from sugo.exporters.jsonl import write_jsonl
from sugo.exporters.markdown import front_matter, write_markdown
from sugo.exporters.receipt import write_receipt

SCHEMA_FILE = Path(__file__).resolve().parents[2] / "schemas" / "chunk-v1.schema.json"
RECEIPT_SCHEMA_FILE = Path(__file__).resolve().parents[2] / "schemas" / "receipt-v1.schema.json"


# A line separator (U+2028) must not split a JSONL line.
def sample(text: str = "Città\nline two \u2028 end") -> Chunk:
    return Chunk(
        id="c_" + "1" * 32,
        document_id="d_" + "2" * 32,
        source="clients/agreement.pdf",
        source_sha256="a" * 64,
        text=text,
        tokens=7,
        heading_path=("Agreement", "Art. 5"),
        pages=(4, 5),
        sugo_version="0.1.0",
        config_hash="b" * 64,
    )


def test_atomic_write_replaces_the_file(tmp_path: Path) -> None:
    target = tmp_path / "out.md"
    target.write_text("old")
    write_text_atomic(target, ["new ", "text"])
    assert target.read_text() == "new text"
    assert [p.name for p in tmp_path.iterdir()] == ["out.md"]


def test_failed_write_keeps_the_old_file(tmp_path: Path) -> None:
    target = tmp_path / "out.md"
    target.write_text("old")

    def broken() -> Iterator[str]:
        yield "partial"
        raise OSError("disk full")

    with pytest.raises(OSError, match="disk full"):
        write_text_atomic(target, broken())
    assert target.read_text() == "old"
    assert [p.name for p in tmp_path.iterdir()] == ["out.md"]


@pytest.mark.skipif(os.name != "posix", reason="POSIX permissions")
def test_new_files_are_private(tmp_path: Path) -> None:
    target = tmp_path / "out.md"
    write_text_atomic(target, ["text"])
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_markdown_without_front_matter_by_default(tmp_path: Path) -> None:
    target = tmp_path / "out.md"
    write_markdown(target, "# Title\n\nText.")
    assert target.read_bytes() == b"# Title\n\nText.\n"


def test_front_matter_values_cannot_break_out(tmp_path: Path) -> None:
    target = tmp_path / "out.md"
    hostile = 'x"\n---\ninjected: true'
    write_markdown(target, "Body.", metadata={"source": hostile, "source_date": None})
    head, body = target.read_text().split("\n---\n\n", 1)
    assert head.splitlines() == [
        "---",
        f"source: {json.dumps(hostile)}",
        "source_date: null",
    ]
    assert body == "Body.\n"


def test_front_matter_refuses_odd_keys() -> None:
    with pytest.raises(ValueError, match="identifiers"):
        front_matter({"a: b": "c"})


def test_jsonl_has_one_valid_chunk_per_line(tmp_path: Path) -> None:
    target = tmp_path / "chunks.jsonl"
    chunks = [sample(), sample("Second")]
    write_jsonl(target, chunks)
    raw = target.read_bytes()
    lines = raw.decode("utf-8").splitlines()
    assert [Chunk.model_validate_json(line) for line in lines] == chunks
    assert raw.endswith(b"\n")
    # UTF-8 text is kept as is, not escaped.
    assert "Città".encode() in raw


def test_every_field_is_written_in_schema_order(tmp_path: Path) -> None:
    target = tmp_path / "chunks.jsonl"
    write_jsonl(target, [sample()])
    record = json.loads(target.read_text())
    assert list(record) == list(chunk_json_schema()["properties"])
    assert set(record) == set(chunk_json_schema()["required"])
    assert record["schema_version"] == "1.0"


def test_published_schema_matches_the_model() -> None:
    # Regenerate with: uv run python -c "import json; from sugo.core.chunks import
    # chunk_json_schema; print(json.dumps(chunk_json_schema(), indent=2, ensure_ascii=False))"
    assert json.loads(SCHEMA_FILE.read_text()) == chunk_json_schema()


def receipt_sample(text: str = "Città\nline two " + chr(0x2028) + " end") -> Receipt:
    return Receipt(
        source="clients/agreement.pdf",
        source_sha256="a" * 64,
        sugo_version="0.1.0",
        config_hash="b" * 64,
        languages=("en",),
        strip_tracking_urls=True,
        pages=1,
        failed_pages=(),
        tokens_before=10,
        tokens_after=7,
        removed=(
            RemovalRecord(
                page=1,
                block_id="b1",
                block_type=BlockType.PARAGRAPH,
                removed_by="header_footer",
                reason="repeated on every page",
                text=text,
            ),
        ),
        edited=(),
        flagged=(),
    )


def test_receipt_write_round_trips(tmp_path: Path) -> None:
    receipt = receipt_sample()
    target = tmp_path / "doc.receipt.json"
    write_receipt(target, receipt)
    raw = target.read_bytes()
    assert Receipt.model_validate_json(raw) == receipt
    assert raw.endswith(b"\n")
    # UTF-8 text is kept as is, not escaped, except the line separator JSON leaves raw.
    assert "Città".encode() in raw
    assert chr(0x2028).encode() not in raw


def test_receipt_file_is_indented_for_people(tmp_path: Path) -> None:
    # ADR-058: one field per line, two-space indent, so a person can read it.
    target = tmp_path / "doc.receipt.json"
    write_receipt(target, receipt_sample())
    lines = target.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "{"
    assert lines[1] == '  "schema_version": "1.0",'
    assert lines[-1] == "}"


def test_receipt_compact_and_indented_files_read_the_same(tmp_path: Path) -> None:
    # Receipts written before ADR-058 were one line; both must still be read.
    receipt = receipt_sample()
    target = tmp_path / "doc.receipt.json"
    write_receipt(target, receipt)
    indented = Receipt.model_validate_json(target.read_bytes())
    assert indented == Receipt.model_validate_json(receipt.model_dump_json()) == receipt


@pytest.mark.skipif(os.name != "posix", reason="POSIX permissions")
def test_receipt_file_is_private(tmp_path: Path) -> None:
    target = tmp_path / "doc.receipt.json"
    write_receipt(target, receipt_sample())
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_receipt_every_field_is_written_in_schema_order(tmp_path: Path) -> None:
    target = tmp_path / "doc.receipt.json"
    write_receipt(target, receipt_sample())
    record = json.loads(target.read_text())
    assert list(record) == list(receipt_json_schema()["properties"])
    assert set(record) == set(receipt_json_schema()["required"])
    assert record["schema_version"] == "1.0"


def test_receipt_published_schema_matches_the_model() -> None:
    # Regenerate with: uv run python -c "import json; from sugo.core.receipt import
    # receipt_json_schema; print(json.dumps(receipt_json_schema(), indent=2, ensure_ascii=False))"
    assert json.loads(RECEIPT_SCHEMA_FILE.read_text()) == receipt_json_schema()


def test_front_matter_keeps_emoji_and_escapes_what_yaml_forbids() -> None:
    title = "emoji \U0001f600 line" + chr(0x2028) + "sep \x85 \x7f end"
    rendered = front_matter({"title": title})
    line = rendered.splitlines()[1]
    assert "\U0001f600" in line
    assert "\\ud83d" not in line
    assert line.endswith('"emoji \U0001f600 line\\u2028sep \\u0085 \\u007f end"')
