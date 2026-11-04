"""Tests for the receipt model and the differences ``sugo verify`` reports (ADR-056)."""

from sugo.core.models import BlockType, EditKind
from sugo.core.receipt import EditRecord, Receipt, RemovalRecord, diff_receipts


def receipt(*, block_id: str = "b1", reason: str = "repeated on every page") -> Receipt:
    removal = RemovalRecord(
        page=1,
        block_id=block_id,
        block_type=BlockType.PARAGRAPH,
        removed_by="header_footer",
        reason=reason,
        text="ACME Corp",
    )
    return Receipt(
        source="a.pdf",
        source_sha256="a" * 64,
        sugo_version="0.1.0",
        config_hash="b" * 64,
        languages=("en",),
        strip_tracking_urls=True,
        pages=1,
        failed_pages=(),
        tokens_before=10,
        tokens_after=7,
        removed=(removal,),
        edited=(),
        flagged=(),
    )


def test_identical_receipts_have_no_differences() -> None:
    assert diff_receipts(receipt(), receipt()) == []


def test_a_block_missing_from_the_fresh_conversion_is_reported() -> None:
    stored, fresh = receipt(), receipt(block_id="b2")
    differences = diff_receipts(stored, fresh)
    assert {"category": "removed", "kind": "missing", "page": 1, "block_id": "b1"} in differences
    assert {"category": "removed", "kind": "extra", "page": 1, "block_id": "b2"} in differences


def test_a_changed_record_counts_as_missing_and_extra() -> None:
    # Same block id, different reason: a different record by value.
    stored, fresh = receipt(), receipt(reason="a different reason")
    differences = diff_receipts(stored, fresh)
    kinds = {(d["category"], d["kind"], d["block_id"]) for d in differences}
    assert kinds == {("removed", "missing", "b1"), ("removed", "extra", "b1")}


def test_changed_tokens_after_is_its_own_entry() -> None:
    stored = receipt()
    fresh = Receipt(**{**stored.model_dump(), "tokens_after": 99, "removed": stored.removed})
    differences = diff_receipts(stored, fresh)
    assert {
        "category": "tokens_after",
        "kind": "changed",
        "stored": 7,
        "fresh": 99,
    } in differences


def without_removed(base: Receipt, **edited_override: object) -> Receipt:
    return Receipt(**{**base.model_dump(), "removed": (), **edited_override})


def test_two_edits_on_the_same_block_sort_deterministically() -> None:
    # Same (page, block_id): the tie-break must not depend on hash randomization.
    edits = (
        EditRecord(
            page=1,
            block_id="b1",
            edited_by="text_normalization",
            kind=EditKind.NORMALIZE,
            reason="ligature",
            original="ﬁ",
            replacement="fi",
        ),
        EditRecord(
            page=1,
            block_id="b1",
            edited_by="tracking_urls",
            kind=EditKind.DELETE,
            reason="tracker",
            original="?utm_source=x",
            replacement="",
        ),
    )
    stored = without_removed(receipt())
    fresh = without_removed(receipt(), edited=edits)
    first = diff_receipts(stored, fresh)
    second = diff_receipts(stored, fresh)
    assert first == second
    assert {d["kind"] for d in first} == {"extra"}
    assert len(first) == 2


def test_never_quotes_removed_text() -> None:
    stored, fresh = receipt(), receipt(block_id="b2")
    differences = diff_receipts(stored, fresh)
    assert all("text" not in d and "ACME" not in str(d) for d in differences)
