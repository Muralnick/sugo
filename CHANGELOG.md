# Changelog

All notable changes to this project are documented here. The format loosely
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning
follows SemVer, with the 0.x caveat from `docs/ARCHITECTURE.md` (contracts may
still change, with notice, before 1.0).

## [Unreleased]

## [0.1.1] - 2026-11-06

### Changed

- Python 3.13 and 3.14 are supported in addition to 3.12 (ADR-057): the
  installer no longer refuses them (`requires-python = ">=3.12,<3.15"`), and
  CI runs the test suite on both, on Linux and Windows. With 0.1.0, `pip`
  on Python 3.13 or newer reported "No matching distribution found".

## [0.1.0] - 2026-11-05

First signed release, published through the pipeline below (roadmap
step 9). Still 0.x: contracts may change, with notice, before 1.0.

### Added

- Conversion receipt (`--receipt`) and `sugo verify` (ADR-056): an opt-in,
  self-contained record of every removal and edit the core made, plus the
  confidence and warning flags extractors already attach to blocks, for
  debugging and trust in RAG pipelines. `sugo verify FILE RECEIPT`
  re-converts the file with the receipt's own stored settings and reports
  what differs, by block id only, never the text. Published schema:
  `schemas/receipt-v1.schema.json`.
- Release pipeline (ADR-033, roadmap step 9, PyPI only for now): on a
  `vX.Y.Z` tag push, builds the sdist and wheel twice to check they're
  reproducible, generates a CycloneDX SBOM (including the bundled OCR
  models and the tokenizer vocabulary), attests build provenance via
  Sigstore, and publishes to PyPI over OIDC Trusted Publishing after a
  manual approval gate.

### Packaging

- Published as `sugo-cli`: the name `sugo` is still held by an unrelated,
  empty PyPI project; the open PEP 541 transfer request is unresolved. The
  installed command is unaffected — it is still `sugo`.

## [0.1.0a1] - 2026-11-03

First public pre-release.

### Added

- Intermediate representation (IR) and offline token metrics, with provider
  image-cost baselines.
- `lite`-level image pipeline: safe loading, classifier, preprocessing,
  offline OCR with hash-checked models, reading-order reconstruction.
- Screenshot chat/code detection, UI chrome cleaning and core cleaning
  decisions.
- Markdown serializer with adaptive tables.
- PDF extraction (PyMuPDF) in an isolated worker, header/footer/page-number
  removal, and a two-level SQLite page cache.
- Section chunker and Markdown/JSONL (schema v1) exporters.
- `sugo` CLI (`stats`, `clip`, `doctor`) and MCP server (`convert_document`,
  `estimate_savings`).
- Text normalisation and tracking-URL cleaners.
- Basic layered TOML configuration.
- Italian interface (gettext catalogs), with automatic language selection
  from the system locale.
- Light Office readers (DOCX, XLSX, PPTX, pictures via OCR) and generic XML,
  each isolated in its own worker process.
- Wider MCP secret exclusions; documents holding private keys are refused.
- Local web UI (`sugo ui`): single file, Markdown, tokens, removals, chunks,
  settings, questions.
- Synthetic-corpus and EUR-Lex benchmarks, with results published in the
  README.

### Known issues

- OCR is noticeably slower than the other stages on low-end hardware (see
  the 2010-desktop measurements in `docs/TESTING.md`); expected at the
  `lite` level and to be revisited with `normal`/`quality`.

### Packaging

- Published on PyPI as `sugo-cli`: the name `sugo` was already registered
  by an unrelated project. The installed command is unaffected — it is
  still `sugo`.
