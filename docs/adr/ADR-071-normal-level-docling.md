# ADR-071: The `normal` level with Docling

**Status:** Proposed (maintainer decisions of 2026-11-14: Docling with PyTorch, CPU only; no legacy Office formats; the shared engine before 0.3.0; measure on the maintainer's PC first)
**Date:** 2026-11-14
**Deciders:** project author
**Implements:** ADR-007 (`normal` level), ADR-001 (per-page routing, first slice for `normal`), ROADMAP v0.3 "`normal` level with Docling"
**Builds on:** ADR-013 and ADR-070 (model download), ADR-018 (process model), ADR-043 (isolated PDF worker), ADR-054 (Office reader), ADR-035 (dependencies)
**Amends:** ADR-070 (multi-file models; Hugging Face hosts), ADR-054 (Docling reads Office files at `normal`)
**Adds dependencies:** the `normal` extra only: `docling-slim` and what it needs, PyTorch CPU among them; none in the base install

## Context

`lite` reads tables poorly. On a four-page PDF with one ruled table per page, `lite` printed every column as a list of loose values; Docling rebuilt all four tables. That is the gap `normal` fills (ADR-007): complex layouts and tables.

Facts checked on 2026-11-14:

- **Versions** at least 14 days old: `docling` / `docling-slim` 2.145.0 (2026-10-29), `docling-core` 2.105.0, `docling-parse` 7.24.2, `docling-ibm-models` 4.0.4, `torch` 2.15.0, `transformers` 5.22.1. All MIT except PyTorch (BSD-3) and transformers (Apache-2.0). About 30 security advisories were published for Docling in 2026 (XXE, path traversal, SSRF, zip bombs, plugin loading); all are fixed at or below 2.142.1.
- **Size**: `docling==2.145.0` in a clean environment is 107 packages and 1.1 GB on disk on Windows. The PyTorch wheel is 127 MB on Windows (CPU) and 539 MB on Linux from PyPI, which is the CUDA build and pulls several GB of NVIDIA libraries; the CPU build comes from PyTorch's own index.
- **Without PyTorch**: Docling has an ONNX export of its layout model only, its code still imports `torch` and `transformers` on that path, and there is no ONNX table model. Not viable today.
- **Models**, all in safe formats, from Hugging Face:

| Model | Repository @ commit | Files | Size | Licence |
|---|---|---|---|---|
| Layout (Heron) | `docling-project/docling-layout-heron` @ `8f39ad3c0b4c58e9c2d2c84a38465abf757272d8` | `model.safetensors` (SHA-256 `00333a43…7929e0c`), `config.json`, `preprocessor_config.json` | 171.7 MB | Apache-2.0 |
| Tables (TableFormer, accurate) | `docling-project/docling-models` @ `2199320848bb9a8a519d22e4b528185a4f9a6f64` | `tableformer_accurate.safetensors` (SHA-256 `2a7d6c92…40374d9`), `tm_config.json` | 212.8 MB | CDLA-Permissive-2.0 / Apache-2.0 |

- **Measured on the maintainer's PC** (Docling with PyTorch 2.15 CPU, 4 threads, OCR off, `docling-parse` backend; `benchmarks` script to come):

| Document | Start (import, load) | Per page | Peak memory |
|---|---|---|---|
| Synthetic report, 4 pages, one table each | 24 s | 8.4 s | 1.4 GB |
| Chinese law (ADR-069 corpus), 12 pages, no tables | 22 s | 3.4 s | 1.7 GB |

  TableFormer *fast* and *accurate* took the same time here, so *accurate*. The peak stays within the 2.5 GB budget; the 20-second start is what the shared engine (next ADR, before 0.3.0) removes.

## Decision

### 1. An optional extra, CPU only

`pip install "sugo-cli[normal]"` adds `docling-slim` 2.145.0 with only the extras `normal` needs: PDF with `docling-parse`, DOCX, PPTX, XLSX, and local models; never `standard`, which brings mail, web, audio and remote-service clients. The exact list is the smallest that passes the tests, pinned in `pyproject.toml` and locked with hashes in `uv.lock`. PyTorch is the CPU build: for `uv` the lock takes it from PyTorch's CPU index; for `pip` on Linux the README gives the `--extra-index-url`. The base install does not change.

### 2. Models through Sugo's download (amends ADR-070)

Docling never downloads. Its two models join the registry as `layout-docling` and `tables-docling`, fetched by `sugo models pull` and installable from bundles. Two changes to ADR-070:

- **A model may have several files**, each with its size and SHA-256, all checked before any is used. The registry stores them in the folder layout Docling expects, so Docling gets that folder as `artifacts_path`.
- **Hugging Face hosts** join the allowed list: `huggingface.co` and the CDN it redirects to (`*.hf.co`). Every file is pinned by commit, not by branch.

`sugo models pull normal` pulls both (ARCHITECTURE §12).

### 3. Docling runs in an isolated worker

Like MuPDF (ADR-043), Docling parses untrusted files with native code, so it runs in a separate process (`spawn`) that:

- gets the document's bytes and returns plain data: Docling's own JSON export, validated by Sugo's models on return (ADR-037). Never pickle;
- has no network: `HF_HUB_OFFLINE=1`, `artifacts_path` set, remote services and external plugins off (Docling's defaults, set explicitly);
- runs with OCR off: scanned pages go to Sugo's own OCR, as in `lite`;
- is limited in memory (the 2.5 GB budget), CPU threads (4) and time per document, and is killed past them; the conversion then fails with a clear error, never a partial result presented as whole.

### 4. Choosing the level

`general.level` (reserved until now) takes `lite` or `normal`, with `SUGO_LEVEL`, the CLI's `--level` / `-l`, the shell's `/level` and the Python API's `level=` argument. The default stays `lite`. Asking for `normal` without the extra gives `LEVEL_MISSING` with the install command; without the models, `MODEL_MISSING` with `sugo models pull normal`. The MCP server reads the level from the configuration and never downloads (principle 10).

### 5. What `normal` reads

- **PDF, per page (ADR-001)**: pages with a text layer go to Docling (layout, reading order, tables); scanned pages to Sugo's OCR as today.
- **DOCX, PPTX, XLSX**: Docling's readers, with Sugo's checks before them (size, zip bombs, XML with `defusedxml`, ADR-054), so a file `lite` refuses is refused at `normal` too.
- **Images and XML**: as in `lite`.
- **DOC, PPT, XLS**: still refused with the advice to save them as DOCX, PPTX, XLSX (maintainer decision). Docling would need LibreOffice, another program to run.

Docling's output is mapped to Sugo's IR (headings with levels, paragraphs, list items, tables with cells, captions, footnotes, code, formulas, pictures). Docling's page header and footer labels are hints for Sugo's header and footer cleaners, never removals on their own: cleaning stays Sugo's, identical at every level (ADR-007). The extraction cache key names Docling's version and the models' hashes.

### 6. Order of work and release

1. Multi-file models, Hugging Face hosts, the two Docling models.
2. The worker, the IR mapping, PDF per page, then Office.
3. Level selection in every port; benchmarks on the corpus, tokens and tables, against `lite`.
4. The shared engine (its own ADR), then release 0.3.0.

## Alternatives considered

| Alternative | Why not |
|---|---|
| Docling without PyTorch (ONNX layout only) | No table model, and Docling still imports PyTorch on that path (maintainer decision) |
| `docling[standard]` | Pulls mail, web, audio and remote-service clients Sugo does not need |
| Docling in Sugo's process | Its native parsers read untrusted files; a crash or a memory blow-up would take Sugo down |
| Docling's own model download | Downloads from branches, outside the gateway's checks (ADR-036, ADR-070) |
| LibreOffice for DOC/PPT/XLS | Another program to run and secure (maintainer decision: not now) |
| Docling for every PDF page | Slower than PyMuPDF on plain pages and no better at OCR than Sugo's |

## Consequences

- `normal` is several times slower than `lite` (3–8 s per page here) and needs about 400 MB of models and 1 GB of packages; it stays opt-in.
- New public contract: the `normal` extra, `general.level` / `SUGO_LEVEL` / `--level`, the API's `level=`, the models `layout-docling` and `tables-docling`, `sugo models pull normal`.
- The release SBOM lists the extra's packages and the two models.
