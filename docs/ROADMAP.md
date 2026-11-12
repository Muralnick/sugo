# Roadmap

## Architecture phases

All twelve phases are complete (October 2026): requirements; pipeline and IR; interfaces; platforms; configuration and extensions; model management; resources; storage; port contracts; testing; threat model; repository and release. Additional decisions: containers, guided setup and work profiles, decision cards, generative-model safeguards, disaster recovery, language packs, principles and extension requirements, project name.

## Plan after v0.1 (reviewed on 2026-11-12, maintainer decision)

v0.1 shipped on 2026-11-05 and reached v0.1.4 on 2026-11-09. The order of the next releases changed after that review: reliability and adoption come before the `normal` level, and Docling moves from v0.2 to v0.3.

| Release | Content |
|---|---|
| v0.1.x | Evaluate PDFium (`pypdfium2`) as the PDF engine in place of PyMuPDF, with a test on the real-PDF corpus; decision by ADR. Fix the PDFs refused as "broken stream" (with whichever engine wins). An uninstall command (needs an ADR). |
| v0.2 | Japanese, Chinese and Korean, as an optional extra for their OCR models. LangChain and LlamaIndex loaders (needs an ADR: package layout, dependencies, licence questions for users). The container image published to GitHub Container Registry and signed by the release pipeline (ADR-065 amendment). |
| v0.3 | `normal` level with Docling (complex Office layouts, legacy formats), the shared engine, and the safe model download it needs (ADR-013); within the 2.5 GB memory budget. |
| v0.4 | Containers (folders, archives, emails), plan-first, guided setup and work profiles. |
| v0.5 | `quality` level with VLM and cross-check; GPU benchmarks. |
| v0.6 | Legal features (anonymization, audit, policies), `sugo-pack-italy`. |
| Later | The full web UI, background service, web sources and registry (ADR-016), static-site exporter and WordPress migration recipe, audio and video, winget/Homebrew, signed installers. |

v1.0 comes when the public contracts (CLI flags, exit and error codes, JSONL schema, receipt format) have stopped changing between releases. Until then the 0.x caveat in `docs/ARCHITECTURE.md` applies.

## First release — v0.1 (shipped)

Goal: a small, finished, demonstrable release that already proves the value of the project.

Scope updated on 2026-10-30 (maintainer decision): Office and XML documents move into v0.1 through a light reader, without Docling; Japanese and Chinese move after v0.1. A GitHub pre-release (`v0.1.0a1`) came first, on 2026-11-03.

| In scope | Out of scope (later) |
|---|---|
| Level `lite` only | `normal`, `quality` |
| Images and screenshots (PNG, JPEG, WEBP), native PDFs, Office (DOCX, XLSX, PPTX) and XML through a light reader | Legacy Office formats, EPUB, email, web, archives; Docling (v0.2) |
| Core IR, multi-pass pipeline, SQLite cache | Shared engine (v0.1 runs in standalone mode) |
| Cleaners: headers/footers, page numbers, text normalisation, URL stripping, screenshot UI chrome | Book cleaners, cross-document boilerplate |
| Detectors: chat and code screenshots | Tables beyond simple ones |
| Language packs: Italian, Spanish, French, German, English (ADR-050) | Japanese, Chinese; Korean (separate OCR model); language detection |
| Markdown and JSONL export, chunker | Hybrid image mode, optimizer |
| Metrics with provider comparison (`sugo stats`) | Tray, watcher |
| CLI one-shot commands, `sugo clip`, `sugo doctor`; interactive shell (ADR-062) | Guided setup |
| MCP server: `convert_document`, `estimate_savings` with allowed roots and token budget | Other MCP tools |
| Basic TOML configuration | Policies, profiles, recipes |
| Local web UI, `sugo ui` (ADR-055, ADR-059): Markdown, tokens, removals, chunks, settings, questions; receipt with the removal and edit list, verify, paste, several files, no-cache setting, installation check | Side-by-side preview, progress events, work profiles |
| Linux CI on every push, Windows smoke tests; a Dockerfile for the MCP server built in CI (ADR-065) | Full platform matrix, published container images |

## Development steps (v0.1, all done)

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

Added on 2026-11-01 (maintainer decision, ADR-055): a minimal local web UI, `sugo ui`, after step 8 and before step 9.

Added on 2026-11-04 (maintainer decision, ADR-056): the conversion receipt and `sugo verify`, scoped to developer/RAG trust and debugging, as a v0.1 follow-up after the `v0.1.0a1` pre-release and before step 9.

Shipped in v0.1.x beyond the original scope: Python 3.13 and 3.14 (ADR-057), the readable receipt file (ADR-058), MCP Registry packaging (ADR-060), the interactive shell (ADR-062, planned for v0.2), handwriting in scans (ADR-063) and scanned letterheads (ADR-064).
