# Changelog

All notable changes to this project are documented here. The format loosely
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning
follows SemVer, with the 0.x caveat from `docs/ARCHITECTURE.md` (contracts may
still change, with notice, before 1.0).

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
