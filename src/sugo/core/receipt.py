"""The conversion receipt: an opt-in, self-contained record of a conversion's
cleaning stage, for developer/RAG trust and debugging (ADR-056).

This is a public contract, versioned like the chunk schema (ADR-047): adding a
field is a minor change; renaming or removing one is a major change with a
deprecation period (principle 12). The JSON Schema published in
``schemas/receipt-v1.schema.json`` is generated from this model, and a test
keeps the two identical.

A receipt documents what the core removed and edited (ADR-041, ADR-050),
which is mechanical and reversible, plus the confidence and warning flags
extractors already attach to blocks. It is not proof the extraction itself
was correct, and it is not cryptographically signed: it is worth exactly as
much trust as Sugo's own process, re-checkable with ``sugo verify``.
"""

from typing import Annotated, Any, Final, Literal

from pydantic import ConfigDict, Field

from sugo.core.constants import SHA256_HEX_LENGTH
from sugo.core.models import BlockFlag, BlockType, EditKind, NonEmptyStr, UnitInterval, _Model

RECEIPT_SCHEMA_VERSION: Final = "1.0"
RECEIPT_SCHEMA_ID: Final = (
    "https://raw.githubusercontent.com/Muralnick/sugo/main/schemas/receipt-v1.schema.json"
)

_Sha256 = Annotated[
    str,
    Field(min_length=SHA256_HEX_LENGTH, max_length=SHA256_HEX_LENGTH, pattern=r"^[0-9a-f]+$"),
]
_PageNumber = Annotated[int, Field(ge=1)]


class RemovalRecord(_Model):
    """One block the core removed, with the text it removed (principle 3)."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    page: _PageNumber
    block_id: NonEmptyStr
    block_type: BlockType
    removed_by: NonEmptyStr
    reason: NonEmptyStr
    # The block's own text; empty for blocks that never carried text, such as
    # a decorative image.
    text: str


class EditRecord(_Model):
    """One text edit the core applied, mirroring ``TextEdit`` (ADR-050)."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    page: _PageNumber
    block_id: NonEmptyStr
    edited_by: NonEmptyStr
    kind: EditKind
    reason: NonEmptyStr
    original: NonEmptyStr
    replacement: str


class FlaggedBlock(_Model):
    """A block that kept a warning flag or less than full confidence, removed or not."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    page: _PageNumber
    block_id: NonEmptyStr
    block_type: BlockType
    flags: tuple[BlockFlag, ...]
    confidence: UnitInterval | None


class Receipt(_Model):
    """Self-contained record of one conversion's cleaning stage (ADR-056)."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    schema_version: Literal["1.0"] = RECEIPT_SCHEMA_VERSION
    source: NonEmptyStr | None
    source_sha256: _Sha256
    sugo_version: NonEmptyStr
    config_hash: _Sha256
    languages: tuple[NonEmptyStr, ...]
    strip_tracking_urls: bool
    pages: Annotated[int, Field(ge=0)]
    failed_pages: tuple[_PageNumber, ...]
    tokens_before: Annotated[int, Field(ge=0)]
    tokens_after: Annotated[int, Field(ge=0)]
    removed: tuple[RemovalRecord, ...]
    edited: tuple[EditRecord, ...]
    flagged: tuple[FlaggedBlock, ...]


def receipt_json_schema() -> dict[str, Any]:
    """The JSON Schema of a receipt, as published in ``schemas/``."""
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": RECEIPT_SCHEMA_ID,
        **Receipt.model_json_schema(mode="serialization"),
    }


def diff_receipts(stored: Receipt, fresh: Receipt) -> list[dict[str, Any]]:
    """What ``sugo verify`` reports: block ids that differ, never their text.

    One entry per block that is ``"missing"`` (in ``stored`` but not
    ``fresh``) or ``"extra"`` (the opposite) in ``removed``, ``edited`` or
    ``flagged``; a block whose record changed appears as both, since it is a
    different record by value. A changed ``tokens_after`` is its own entry.
    Empty when the two receipts describe the same cleaning.
    """
    differences: list[dict[str, Any]] = [
        *_diff("removed", stored.removed, fresh.removed),
        *_diff("edited", stored.edited, fresh.edited),
        *_diff("flagged", stored.flagged, fresh.flagged),
    ]
    if stored.tokens_after != fresh.tokens_after:
        differences.append(
            {
                "category": "tokens_after",
                "kind": "changed",
                "stored": stored.tokens_after,
                "fresh": fresh.tokens_after,
            }
        )
    return differences


def _diff(
    category: str, stored_items: tuple[Any, ...], fresh_items: tuple[Any, ...]
) -> list[dict[str, Any]]:
    """Each item is a ``RemovalRecord``, ``EditRecord`` or ``FlaggedBlock``: any
    record with ``page`` and ``block_id`` fields."""
    stored_set, fresh_set = set(stored_items), set(fresh_items)
    missing = sorted(stored_set - fresh_set, key=lambda item: (item.page, item.block_id))
    extra = sorted(fresh_set - stored_set, key=lambda item: (item.page, item.block_id))
    return [
        {"category": category, "kind": kind, "page": item.page, "block_id": item.block_id}
        for kind, items in (("missing", missing), ("extra", extra))
        for item in items
    ]
