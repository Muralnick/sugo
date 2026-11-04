# ADR-056: Conversion receipt and `sugo verify`

**Status:** Accepted
**Date:** 2026-11-04
**Deciders:** project author
**Implements:** ADR-050 (text edits), ADR-041 (cleaner decisions), ADR-047 (chunks, schema versioning), ADR-003 (token metrics)
**Adds dependencies:** none

## Context

Sugo's headline claim is a savings figure paired with a content-preservation figure ("−68% tokens with 99.6% of content preserved", `docs/TESTING.md`). Today the user has to take that figure on trust: `Conversion.removed` and `Conversion.edited` only carry a **count** per cleaner name, not what was removed, why, or where. For a developer building a RAG pipeline, this makes two common questions hard to answer without re-reading the source by hand:

1. "My answer is missing a fact — did Sugo drop it, or was it never in the source?"
2. "I upgraded Sugo / changed my config — did conversion of my existing corpus actually change, and where?"

This ADR adds a **conversion receipt**: an opt-in, self-contained record of exactly what a conversion did, and a `sugo verify` command that checks a receipt against a fresh re-conversion. Scope is deliberately limited to **debugging and trust for developer/RAG use** (maintainer decision, 2026-11-04). A stronger, non-repudiable version for legal/e-invoice use (signing, OCR-confidence-backed extraction guarantees) is deferred; see the "Out of scope" section.

## Decision

### What the receipt covers, and what it does not

The receipt documents the **cleaning stage** (removals and edits), which is mechanical, reversible and already fully tracked (ADR-041, ADR-050). It also surfaces the **confidence and warning flags** the extractors already attach to blocks (`Block.confidence`, `BlockFlag.ILLEGIBLE`, `LOW_AGREEMENT`, `HIDDEN`), at no extra extraction cost, since those fields already exist on the IR.

It does **not** prove the extraction itself was correct (an OCR misread is not a tracked edit) and it is **not** cryptographically signed. It answers "what did Sugo do to this text, and how sure was it of the text to begin with", not "is this text legally admissible as unaltered". A receipt is worth exactly as much trust as Sugo's own process, re-checkable by anyone who can re-run `sugo verify` — not more.

### Receipt model, schema 1.0

`sugo.core.receipt.Receipt`, a strict pydantic model, one per converted document, written as `NAME.receipt.json`:

| Field | Meaning |
|---|---|
| `schema_version` | `"1.0"` |
| `source`, `source_sha256` | Same meaning as on `Conversion` (ADR-047) |
| `sugo_version`, `config_hash` | Same meaning as on `Conversion`; a receipt is only expected to reproduce under the version and config that made it |
| `languages`, `strip_tracking_urls` | The two `convert_file` settings that actually affect cleaning (maintainer decision, 2026-11-04: the receipt must be self-sufficient for `verify`, not just carry `config_hash`'s digest of them) |
| `pages`, `failed_pages` | Same meaning as on `Conversion` |
| `tokens_before`, `tokens_after` | o200k_base tokens of the raw and cleaned text (reuses `count_raw_tokens`, ADR-003) |
| `removed` | List of `RemovalRecord`: `page`, `block_id`, `block_type`, `removed_by`, `reason`, `text` (the block's original text, via `Block.original_text()`) |
| `edited` | List of `EditRecord`: `page`, `block_id`, `edited_by`, `kind`, `reason`, `original`, `replacement` (mirrors `TextEdit`) |
| `flagged` | List of `FlaggedBlock`: `page`, `block_id`, `block_type`, `flags`, `confidence` — every block that kept at least one `BlockFlag` or a `confidence` below 1.0, whether or not it was also removed |

`removed` and `edited` are the per-block detail behind the existing `Conversion.removed`/`Conversion.edited` counts; `flagged` is new information not currently surfaced anywhere. All three are naturally bounded by limits that already exist (ADR-050's per-block/per-page edit caps; a page cannot hold more blocks than it has content), so no new size limit is needed.

Published schema: `schemas/receipt-v1.schema.json` (JSON Schema 2020-12), generated from the model, with a test that fails if they drift — the same pattern as `chunk-v1.schema.json` (ADR-047).

### Building the receipt

`Conversion` pass 3 (`sugo/core/pipeline.py`, where `removed`/`edited` counters are built today) already visits every block of every page exactly once. Building the receipt reuses that same pass: for each block, in addition to updating the counters, append to the three lists above when applicable. No second pass, no re-reading pages from the cache.

Because it holds full original text for every removal and edit — strictly more than the Markdown output already contains, so no new privacy exposure, but non-trivial extra memory for a large, heavily-cleaned document — building it is **opt-in**, following the existing pattern for `count_raw_tokens` and chunking: `convert(..., receipt=False)`. `Conversion` gains one new field, `receipt: Receipt | None = None`.

### CLI

```
sugo FILE... [-o DIR] [--chunks] [--receipt] [--max-tokens N] [--front-matter] [--no-cache] [--json]
sugo verify FILE RECEIPT [--json]
```

- `--receipt` needs `-o` or `--json` (maintainer decision, 2026-11-04: left to the author to resolve, settled the same way as `--max-tokens needs --chunks` — a receipt is structured data with no sensible inline textual form mixed with plain Markdown on stdout). With `-o`, writes `NAME.receipt.json` next to `NAME.md` (atomic, owner-only, like `NAME.jsonl`, ADR-047). With `--json` alone, adds a `receipt` object to the per-document JSON, next to `chunks` when `--chunks` is also given.
- `sugo verify FILE RECEIPT`: re-reads `FILE`, re-converts it with the `languages` and `strip_tracking_urls` stored on the receipt itself (maintainer decision, 2026-11-04: the receipt is self-sufficient — it carries the actual settings, not just `config_hash`'s digest of them, so `verify` never needs the caller to remember or re-supply the original flags), and structurally compares the result:
  - `source_sha256` differs → refuses immediately with the new error code `FILE_CHANGED`, exit 1: the receipt is for a different edition of the document.
  - A receipt that is not valid JSON or not schema 1.0 → the new error code `RECEIPT_INVALID`, exit 1.
  - `sugo_version` differs → warns (stderr) that an exact match cannot be guaranteed across versions, then still compares and reports what it finds. `config_hash` is **not** compared here: `languages` and `strip_tracking_urls` are already forced equal (they come from the receipt itself), and `config_hash` also carries `max_chunk_tokens`, which `verify` never sets — comparing it would warn on every receipt made alongside `--chunks` even when nothing relevant changed.
  - Otherwise compares `removed`, `edited`, `flagged` and `tokens_after` entry-by-entry and prints the result itself — block ids and pages only, never text (principle 11). Like `sugo doctor`, the command reports everything itself and then sets the exit code directly (0 match, 1 mismatch), rather than wrapping a already-printed result in a second error object.
  - `--json` prints `{"match": bool, "version_drifted": bool, "differences": [...]}`, each difference naming its `category` (`removed`/`edited`/`flagged`/`tokens_after`), `kind` (`missing`/`extra`/`changed`), `page` and `block_id` — again without text.

### Out of scope (deferred, maintainer decision 2026-11-04)

- **Cryptographic signing / non-repudiation.** Needed for a legal/e-invoice trust claim ("this was not tampered with by a third party"), not for debugging. Would need a signing dependency and key management, and overlaps with the already-planned v0.5 "hash-chained audit log" and "reproducible output stamped with version and config hash" (`docs/ARCHITECTURE.md` §14, §legal features). Revisit only on demonstrated demand or when preparing an EU grant application.
- **Extraction-fidelity guarantees** (e.g., character error rate against ground truth) beyond the `confidence`/flags Sugo already computes. That needs a ground-truth corpus per document, which Sugo does not have at conversion time; it is a benchmark-time concept (`docs/TESTING.md`), not a per-document receipt concept.
- **MCP exposure.** v0.1's MCP server deliberately ships only `convert_document` and `estimate_savings` (ADR-049); a receipt-producing tool is a new MCP surface, left for later.

## Alternatives considered

| Alternative | Why not |
|---|---|
| Embed removal/edit detail directly in the JSONL chunk records | Chunks are about RAG retrieval content, already a stable public schema (ADR-047); mixing in cleaning provenance would bloat every chunk even when nobody asks for it |
| Always compute the receipt, just not always write it | Still pays the memory cost of holding every removed/edited block's original text in memory for documents nobody will inspect; opt-in avoids this, matching `count_raw_tokens` |
| Make `verify` a pure hash check (receipt stores a hash of its own removed/edited list, `verify` just re-hashes) | Cheaper, but on mismatch tells the user nothing about *what* differs — defeats the debugging purpose that is the whole point of scoping this to dev/RAG |
| Sign the receipt now with a local, unmanaged keypair | Gives a false sense of non-repudiation without key management, revocation or a threat model; worse than no signature at all |

## Consequences

- New public contract: `Receipt` schema 1.0, the `--receipt` flag, the `sugo verify` command, its exit codes and the new `FILE_CHANGED` / `RECEIPT_INVALID` error codes (principle 12). Placed in `docs/ROADMAP.md` as a v0.1 follow-up, after the `v0.1.0a1` pre-release and before step 9 (maintainer decision, 2026-11-04) — it was not part of the original v0.1 scope table.
- `Conversion` gains one field (`receipt: Receipt | None`); existing callers are unaffected since it defaults to `None`.
- Strengthens principle 3 ("no silent loss... can be inspected") with a self-contained, shareable artifact: `verify` needs only `FILE` and `RECEIPT`, never the machine, cache or original command line that produced it.
- Residual: `verify` only promises a match under the `sugo_version` that produced the receipt; a version difference is reported as a warning, not a hard failure, because output can legitimately change between releases (this is the same boundary `Conversion.config_hash` already has).
