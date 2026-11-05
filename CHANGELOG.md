# Changelog

All notable changes to this project are documented here. The format loosely
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning
follows SemVer, with the 0.x caveat from `docs/ARCHITECTURE.md` (contracts may
still change, with notice, before 1.0).

## [Unreleased]

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

### Changed

- Distribution renamed from `sugo-cli` back to `sugo` (ADR-033 amendment,
  2026-11-05): the name freed up on PyPI. The `0.1.0a1` pre-release stays
  published as `sugo-cli`; the real `v0.1.0` will ship as `sugo` once it is
  claimed there by hand.

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
