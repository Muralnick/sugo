# ADR-047: Chunker, JSONL schema v1 and exporters

**Status:** Accepted  
**Date:** 2026-10-29  
**Deciders:** project author  
**Implements:** ADR-023 (output schema), ADR-006 (pass 4, chunking), ARCHITECTURE §4 and §13  
**Amends:** ARCHITECTURE §13 example (no `processed_at`; new `source_sha256`)

## Context

Roadmap step 6 turns a converted document into what RAG pipelines load: chunks with provenance, as JSON Lines, plus the Markdown file itself. The JSONL record is a public contract (principle 12); once released, a field can only be added, never renamed or removed without a major version.

## Decision

### Chunk record, schema 1.0

`sugo.core.chunks.Chunk`, a strict pydantic model, one per JSONL line, every field always written:

| Field | Meaning |
|---|---|
| `schema_version` | `"1.0"` |
| `id` | `c_` + 32 hex digits (128 bits) of SHA-256 over the document id, the chunk text and, for text repeated in the document, its occurrence number |
| `document_id` | `d_` + 32 hex digits of the **source name** as given (e.g. `clients/agreement.pdf`); of the content hash when there is no name |
| `source` | The source as given, or null |
| `source_sha256` | SHA-256 of the source file (new, not in the ARCHITECTURE example): tells editions apart |
| `text` | The chunk's Markdown, rendered exactly as in the document output |
| `tokens` | o200k_base tokens of `text` (ADR-003) |
| `heading_path` | Headings above the chunk, outermost first |
| `pages` | Page numbers counted from 1 |
| `language`, `source_date` | Reserved, null in 1.0 (language detection and document dates come later) |
| `sugo_version`, `config_hash` | The Sugo release, and a digest of the settings that change the output (cleaners, chunk size) |

- **Identity from the name** (maintainer decision): a new edition of a document in the same place keeps its `document_id`, and every chunk whose text did not change keeps its `id`, so a vector database re-embeds only the changed chunks. The same paragraph in two different documents has two ids and never overwrites the other.
- **No `processed_at`** (maintainer decision): the same input and configuration give the same bytes (principle 6), so output can be verified by hash. A timestamp can be added later as an optional field (a minor change).
- **Published schema:** `schemas/chunk-v1.schema.json` (JSON Schema 2020-12) is generated from the model by `chunk_json_schema()`; a test fails if they differ. No new dependency.

### Chunker

`sugo.chunkers.sections.SectionChunker` streams cleaned pages (pass 4, run alongside pass 3 so each page is read once), default 512 tokens, minimum 32:

- a heading closes the chunk before it, unless that chunk holds only headings that the new one does not close (a heading at the same level or above ends the previous heading's empty section, so a chunk's heading path names every heading in it);
- **a heading always travels with the text after it:** when the first block of a section does not fit beside its headings, that block is split so its first piece does (headings taking more than half the limit form their own chunk);
- a block that does not fit starts a new chunk; tables are never split, even past the limit, and stay with their section's headings;
- a longer paragraph is split after sentence ends followed by a space (so "3.14" is not cut), after CJK sentence punctuation or after line breaks; code after line breaks (each piece stays fenced); then between words, and only as a last resort inside a word. **Pieces are exact slices of the text**, spaces and line breaks included, except at their two ends. After the first piece of a list item the rest is plain text, so one bullet never becomes several; chat messages keep their speaker on every piece;
- removed blocks are left out exactly as in the Markdown; illegible blocks stay as `[illegible]`. Property tests check on random text that every character of the Markdown reaches the chunks, in order, that split pieces are exact slices separated only by whitespace, and that no chunk passes the limit.
- Token counts are estimated from the blocks and counted exactly near the limit; the recorded `tokens` is always exact.

`convert(..., source=..., max_chunk_tokens=...)` returns the chunks with the Markdown; no chunks unless asked.

### Exporters

- `write_markdown(path, markdown, metadata=None)`: optional YAML front matter, off by default (it costs tokens on every read); values are double-quoted scalars: JSON escapes for quotes, backslashes and controls, plus `\uXXXX` escapes for what YAML forbids or reads as line breaks (C1 controls, U+2028, U+2029, U+FFFE, U+FFFF); emoji and other text are written as they are, since YAML has no surrogate-pair escapes; a lone surrogate becomes U+FFFD.
- `write_jsonl(path, chunks)`: one record per line; besides JSON's own escapes, U+0085, U+2028 and U+2029 are escaped, since some readers (Python's `str.splitlines`) treat them as line ends.
- Both write **atomically** (temporary file in the same folder, flushed, renamed): a crash or a full disk leaves the previous output intact. New files are created owner-only (0600), like everything Sugo writes with document text.
- Import-linter contracts keep chunkers and exporters away from extractors, cleaners, caches and networks.

## Alternatives considered

| Alternative | Why not |
|---|---|
| 8-hex-digit ids, as in the ARCHITECTURE example | 32 bits: collisions become likely past tens of thousands of chunks |
| Document id from the content | Every new edition would change every chunk id and re-embed everything |
| Chunk id from the text alone | Identical paragraphs of different documents would overwrite each other |
| `processed_at` in every record | Breaks byte-for-byte reproducibility |
| Overlap between chunks | Not in the design; costs tokens; can be added as an option |
| A JSON Schema validation library | The schema is generated from the strict pydantic model that already validates every record |

## Consequences

- New public contract: JSONL schema 1.0 and its published JSON Schema.
- Measured on the reference machine: chunking adds about 7 ms per dense page (about 70 pages/s on a fully cached document, against 200 without chunks).
- Residual: a source given with different spellings (`./a.pdf`, `a.pdf`) gets different document ids; the CLI will normalise paths (step 7). A heading longer than the limit makes an oversized chunk.
