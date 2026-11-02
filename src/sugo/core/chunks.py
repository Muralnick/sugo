"""The chunk record: one line of Sugo's JSONL output, schema v1 (ADR-023, ADR-047).

This is a public contract: RAG pipelines and vector databases are built on
it. Adding a field is a minor change; renaming or removing one is a major
change with a deprecation period (principle 12). The JSON Schema published
in ``schemas/chunk-v1.schema.json`` is generated from this model, and a test
keeps the two identical.

Ids are content-addressed: a chunk whose text does not change keeps its id
across runs and new editions of the same document, so a vector database
re-embeds only the chunks that changed. The record holds nothing that
changes from one run to the next, such as a timestamp, so the same input
and configuration always give the same bytes (principle 6).
"""

from typing import Annotated, Any, Final, Literal

from pydantic import ConfigDict, Field

from sugo.core.constants import OUTPUT_ID_HEX_DIGITS, SHA256_HEX_LENGTH
from sugo.core.models import NonEmptyStr, _Model

CHUNK_SCHEMA_VERSION: Final = "1.0"
CHUNK_SCHEMA_ID: Final = (
    "https://raw.githubusercontent.com/Muralnick/sugo/main/schemas/chunk-v1.schema.json"
)

_Sha256 = Annotated[
    str,
    Field(min_length=SHA256_HEX_LENGTH, max_length=SHA256_HEX_LENGTH, pattern=r"^[0-9a-f]+$"),
]


class Chunk(_Model):
    """A piece of a document sized for retrieval, with where it comes from."""

    # Every field is always written, defaults included, so the published
    # schema marks them all required.
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    schema_version: Literal["1.0"] = CHUNK_SCHEMA_VERSION
    # "c_" and 32 hex digits: the document id, the text and, for repeated
    # text, which occurrence this is.
    id: Annotated[str, Field(pattern=rf"^c_[0-9a-f]{{{OUTPUT_ID_HEX_DIGITS}}}$")]
    # "d_" and 32 hex digits of the source name, so new editions of a
    # document keep its id; of the content when there is no name.
    document_id: Annotated[str, Field(pattern=rf"^d_[0-9a-f]{{{OUTPUT_ID_HEX_DIGITS}}}$")]
    # The source as given, e.g. "clients/agreement.pdf", or None for raw bytes.
    source: NonEmptyStr | None
    source_sha256: _Sha256
    # Markdown, rendered exactly as in the document output.
    text: NonEmptyStr
    # o200k_base tokens of ``text`` (ADR-003).
    tokens: Annotated[int, Field(ge=1)]
    # Headings above the chunk, outermost first.
    heading_path: tuple[NonEmptyStr, ...]
    # Page numbers as people count them, from 1.
    pages: tuple[Annotated[int, Field(ge=1)], ...]
    # Reserved until language detection exists (language packs); always None in 1.0.
    language: NonEmptyStr | None = None
    # Date of the document itself, when known; None in 1.0.
    source_date: NonEmptyStr | None = None
    sugo_version: NonEmptyStr
    # Digest of everything in the configuration that changes the chunks.
    config_hash: _Sha256


def chunk_json_schema() -> dict[str, Any]:
    """The JSON Schema of one JSONL line, as published in ``schemas/``."""
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": CHUNK_SCHEMA_ID,
        **Chunk.model_json_schema(mode="serialization"),
    }
