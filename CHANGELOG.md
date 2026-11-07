# Changelog

All notable changes to this project are documented here. The format loosely
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning
follows SemVer, with the 0.x caveat from `docs/ARCHITECTURE.md` (contracts may
still change, with notice, before 1.0).

## [Unreleased]

### Added

- Interactive shell (ADR-062): `sugo` alone in a terminal opens it; drag a
  file or type its name, then use slash commands such as `/save`, `/stats`,
  `/explain`, `/clip` and `/help`.
- The shell shows the page being read while a document converts.
- Handwriting in scanned pages, such as signatures, is marked
  `[handwriting]` instead of being read as made-up words (ADR-063). Typed
  text crossed by ink keeps its text and is flagged `ink_overlap` in the
  receipt. Receipts with these new flags cannot be checked by `sugo verify`
  of an older Sugo.

### Changed

- Scanned pages: text of very different sizes, such as a letterhead's small
  captions touching the body below them, is no longer merged into one
  paragraph (ADR-064, part 1).
- Scanned pages: later copies of a letterhead at the top of the page are
  removed even though the OCR reads them differently on each page; the
  first copy always stays, and each removal records its reason (ADR-064,
  part 2). On a real three-page record this saves 14% of the tokens.
- When cleaning removes nothing, the shell says the text was already clean
  instead of showing an empty "0% saved" bar.

### Fixed

- Security (review finding F3): PDF text at almost no opacity over a visible
  paragraph, or under an opaque shape with another mark in its box, is now
  marked hidden and never reaches the LLM as visible text. Each page is
  rendered a second time without its text (ADR-043 amendment); reading a PDF
  takes about 16 ms more per page.
- The shell's `/help` translates argument names (`CARTELLA`, `DIMENSIONE`,
  `RICEVUTA` in Italian).

## [0.1.2] - 2026-11-07

### Added

- Web UI level with the command line (ADR-059): an opt-in receipt with the
  list of every removed, edited and uncertain block and its reason, saved as
  `NAME.receipt.json`; a Verify tab that checks a receipt as `sugo verify`
  does; pasting a screenshot with Ctrl+V, as `sugo clip`; up to 50 files at
  once, saved together as one ZIP; a "keep a cache on disk" setting, as
  `--no-cache`; an installation check, as `sugo doctor`, run once when the
  page opens, with a warning only if something is broken.
- `sugo-cli` command, the same as `sugo`, so `uvx sugo-cli` works, and a
  `server.json` describing Sugo for the official MCP Registry (ADR-060).
- README: how to uninstall Sugo and delete its files, and what to do when
  `sugo` is not found after installing with pip.

### Changed

- `pip install sugo-cli` installs everything needed to convert: the `lite`
  packages are base dependencies now (ADR-060). `sugo-cli[lite]` still works.
- The receipt file is indented, one field per line, so people can read it
  (ADR-058). Older one-line receipts still verify.
- A file name with spaces typed without quotes gets a clear message showing
  the name in quotes, instead of "several files need an output folder".

### Fixed

- PDF and Office files failed (`PDF_EXTRACTION_FAILED`,
  `OFFICE_EXTRACTION_FAILED`) when Sugo was installed with `pip install
  --user`, which pip does on its own on Windows without admin rights: the
  reading process could not find Sugo (ADR-061).
- `sugo verify` crashed on a receipt naming a language pack this Sugo does
  not have; it now reports `RECEIPT_INVALID`.
- README: the logo and the links to files in the repository use absolute URLs,
  because PyPI shows the README without the repository around it (the logo did
  not load and the links led nowhere on the PyPI page).

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
