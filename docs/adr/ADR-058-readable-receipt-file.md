# ADR-058: Write the receipt file indented

**Status:** Accepted (maintainer decision, 2026-11-07)
**Date:** 2026-11-07
**Deciders:** project author
**Amends:** ADR-056 (conversion receipt: file layout)
**Adds dependencies:** none

## Context

ADR-056 writes `NAME.receipt.json` with pydantic's `model_dump_json()`, which puts the whole receipt on a single line. The maintainer's first hands-on test (2026-11-07) found it hard to read: a receipt is meant to be opened by a person who wants to know what Sugo removed or changed, and a single line of several kilobytes is not readable in a text editor or on GitHub.

The receipt is a single JSON document, not JSON Lines (unlike the chunk file, ADR-047), so nothing requires one record per line.

## Decision

1. `NAME.receipt.json` is written indented by two spaces (`model_dump_json(indent=2)`), still UTF-8, still ending with a newline, still atomic and owner-only.
2. Nothing else changes: same fields in the same order, `schema_version` stays `"1.0"`, and `schemas/receipt-v1.schema.json` is unchanged. Any JSON reader, including `sugo verify`, reads the old one-line files and the new indented ones alike, because whitespace between JSON tokens has no meaning.
3. U+0085, U+2028 and U+2029 inside strings are still written escaped, as before.
4. The `receipt` object inside `--json` output on stdout stays compact: that output is for scripts, one JSON value per document.

## Alternatives considered

| Alternative | Why not |
|---|---|
| A `--pretty` flag | One more flag to learn for something nearly everyone wants; the file has no reason to be compact |
| Bump the schema to 1.1 | The content and the schema do not change, only whitespace |
| Also indent `--json` output | Scripts and `jq` do not need it, and it would change existing stdout output for no reader's benefit |

## Consequences

- Receipts are readable in any editor; files grow by the added whitespace (indentation and line ends), which is small compared with the document text they hold.
- Old receipts stay valid for `sugo verify`.
- A tool that compared receipt files byte for byte (not a documented use) would see a difference between files written before and after this change.
