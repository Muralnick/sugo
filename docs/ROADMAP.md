# Roadmap

## Architecture phases

All twelve phases are complete (October 2026): requirements; pipeline and IR; interfaces; platforms; configuration and extensions; model management; resources; storage; port contracts; testing; threat model; repository and release. Additional decisions: containers, guided setup and work profiles, decision cards, generative-model safeguards, disaster recovery, language packs, principles and extension requirements, project name.

## First release — v0.1 (proposed, to be confirmed by the maintainer)

Goal: a small, finished, demonstrable release that already proves the value of the project.

Scope updated on 2026-10-30 (maintainer decision): Office and XML documents move into v0.1 through a light reader, without Docling; Japanese and Chinese move after v0.1. A GitHub pre-release (`v0.1.0a1`) comes first, as soon as the stacked pull requests are merged.

| In scope | Out of scope (later) |
|---|---|
| Level `lite` only | `normal`, `quality` |
| Images and screenshots (PNG, JPEG, WEBP), native PDFs, Office (DOCX, XLSX, PPTX) and XML through a light reader | Legacy Office formats, EPUB, email, web, archives; Docling (v0.2) |
| Core IR, multi-pass pipeline, SQLite cache | Shared engine (v0.1 runs in standalone mode) |
| Cleaners: headers/footers, page numbers, text normalisation, URL stripping, screenshot UI chrome | Book cleaners, cross-document boilerplate |
| Detectors: chat and code screenshots | Tables beyond simple ones |
| Language packs: Italian, Spanish, French, German, English (ADR-050) | Japanese, Chinese; Korean (separate OCR model); language detection |
| Markdown and JSONL export, chunker | Hybrid image mode, optimizer |
| Metrics with provider comparison (`sugo stats`) | Web UI, tray, watcher |
| CLI one-shot commands, `sugo clip`, `sugo doctor` | Interactive shell, guided setup |
| MCP server: `convert_document`, `estimate_savings` with allowed roots and token budget | Other MCP tools |
| Basic TOML configuration | Policies, profiles, recipes |
| Linux CI on every push, Windows smoke tests | Full platform matrix, Docker images |

## Development steps

0. Repository scaffold: `pyproject.toml`, uv workspace, ruff, mypy, import-linter, pytest, CI on Linux, governance files.
1. `core/models.py` (IR) and `metrics/` (tokenizer, provider formulas as data, both baselines).
2. Image pipeline (`lite`): classifier, preprocessing, OCR wrapper, layout reconstruction.
3. Screenshot cleaners and chat/code detectors.
4. Markdown serializer with adaptive tables.
5. PDF extractor (PyMuPDF), header/footer analyzer and cleaners, SQLite page store and cache.
6. Chunker and exporters (Markdown, JSONL with schema v1).
7. CLI (`sugo`, `stats`, `clip`, `doctor`), MCP server (two tools).
8. Benchmarks on the synthetic corpus and EUR-Lex samples; README numbers.
9. Release v0.1 on PyPI.

Added on 2026-10-30, between steps 7 and 9: the remaining v0.1 pieces (text cleaners, ADR-050; basic TOML configuration; Italian interface; Windows smoke tests), the GitHub pre-release, and the light Office and XML reader.

## After v0.1

- v0.2: shared engine, interactive shell, Japanese, Chinese, Korean, `normal` level with Docling (complex Office layouts, legacy formats).
- v0.3: containers (folders, archives, emails), plan-first, guided setup and work profiles.
- v0.4: `quality` level with VLM and cross-check; GPU benchmarks.
- v0.5: legal features (anonymization, audit, policies), `sugo-pack-italy`.
- Later: web UI, background service, web sources and registry (ADR-016), static-site exporter and WordPress migration recipe, audio and video, winget/Homebrew, signed installers.
