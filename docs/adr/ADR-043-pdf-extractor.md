# ADR-043: Native PDF extractor in an isolated worker

**Status:** Accepted.  
**Date:** 2026-10-29; amended 2026-11-02 (PyMuPDF 2.0 adopted)  
**Deciders:** project author  
**Implements:** ADR-001 (per-page routing), ADR-007 (`lite` level), ADR-018 (process isolation, first slice), ADR-031 (hardening)  
**Amends:** IR flags (ADR-005): new `hidden` flag

## Context

Roadmap step 5a reads PDFs. MuPDF, through PyMuPDF, is the native-text backend chosen in ADR-001. It is a large C library that parses untrusted files, and in 2026 AI-assisted fuzzing found many memory-safety bugs in it: MuPDF 1.28.5 (September) fixed more than 25, several reachable by opening a malicious file (out-of-bounds write on a malicious JPEG, heap overwrite in progressive loading, double free in structure-tree parsing). Its bundled Brotli decoder has an out-of-bounds write (CVE-2026-111497) fixed only in MuPDF 1.28.6, which no PyMuPDF release ships yet.

PDFs are also a vehicle for prompt injection: text a person cannot see (white on white, microscopic, off the page, drawn invisible) still reaches an LLM (THREAT_MODEL.md B).

## Decision

### Version

| Release | Date | MuPDF | Dependencies | Status |
|---|---|---|---|---|
| PyMuPDF 1.28.2 | 2026-08-06 | 1.28.2 (known bugs above) | none | Used only while step 5a was written |
| PyMuPDF 2.0 | 2026-10-19 | 1.28.5 | networkx, numpy, onnxruntime, pyyaml, psutil, tabulate, two empty compatibility packages | **Adopted** 2026-11-02, when 14 days old |

`pymupdf>=2.0,<2.1` is in the `sugo[lite]` extra; a 2.0.x with MuPDF ≥ 1.28.6 is adopted once 14 days old. Checks made on 2026-11-02 before adopting 2.0:

- **New dependencies:** numpy, onnxruntime and pyyaml were already in Sugo. networkx 3.7 (BSD-3-Clause), psutil 7.2.2 (BSD-3-Clause) and tabulate 0.10.0 (MIT) are new: permissive, on the licence allow-list (`CODE_STYLE.md`), each more than 14 days old. `pymupdf-layout` and `pymupdf4llm` 2.0 are empty compatibility packages (about 1 KB, no code).
- **No model download:** the layout module's ONNX models are inside the wheel (pinned by its hash in `uv.lock`), and the Python code of `pymupdf.layout` and `pymupdf4llm` contains no network access.
- **Layout module and `pymupdf4llm` never loaded:** the wheel also contains `pymupdf4llm` (Markdown conversion with its own OCR model). `import pymupdf` imports both whenever they are installed; `pymupdf.layout` loads its ONNX models at once, and both load onnxruntime. Sugo uses neither, so the worker blocks both imports before loading PyMuPDF, which treats them as not installed: the models, onnxruntime and their memory stay out of the worker. A test checks this in a fresh process. Sugo never calls `find_tables()`, `get_layout()` or PyMuPDF's Tesseract OCR either.

Licence: AGPL-3.0 (dual-licensed by Artifex), on the allow-list (ADR-010). The wheel (about 64 MB) bundles MuPDF's third-party C libraries, distributed by Artifex under the same terms. It also ships a `pymupdf` command-line tool affected by CVE-2026-82035 (path traversal when extracting fonts); Sugo never runs it.

### Isolation

- MuPDF runs only in a **worker process**, started as `python -I -m sugo.extractors.pymupdf.worker` with no shell. An import-linter contract forbids `pymupdf` anywhere else in Sugo.
- The PDF goes to the worker on stdin. Results come back as length-prefixed JSON frames, validated against strict pydantic models (unknown fields refused), or as raw RGB pixels of an announced size for scanned pages. **No pickle**: unpickling data from a compromised worker would run its code in Sugo. Frames are capped at 64 MB, and a scanned page at 20 megapixels.
- The worker disables core dumps (ADR-031) and, on Linux and macOS, caps its address space at 1.5 GB. Windows lacks both, and this is documented.
- Frames go to a private copy of the worker's stdout, and file descriptor 1 itself to the null device: MuPDF's C code prints to stdout on decoding errors, and nothing it prints can corrupt or forge a frame.
- Any error while reading one page marks only that page as failed; a page whose box cannot be read gets the previous page's box (US Letter for the first), and reading it then fails and marks it.
- Opening has a 60 s limit, each page 30 s. A page that stalls, crashes the worker or gets an invalid answer is **marked illegible** (never dropped), and a fresh worker continues from the next page. After 3 such restarts the document is refused.
- Two reader threads and a two-frame queue keep Sugo responsive and its memory bounded, even if the worker races ahead on a scanned book.

### Checks before parsing

| Check | Where | Refusal code |
|---|---|---|
| Size ≤ 200 MB | Sugo | `PDF_TOO_LARGE` |
| `%PDF-` in the first 1 024 bytes | Sugo | `PDF_INVALID` |
| No Brotli name (`/Br`, `/BrotliDecode`, in any `#xx` spelling) anywhere in the raw bytes | Sugo | `PDF_UNSUPPORTED` |
| Every `/Filter` is a name or an array of names, and so is every `/F` in a stream's dictionary (a reference's name could hide in compressed data) | Sugo | `PDF_UNSUPPORTED` |
| A scan cut short by its work cap, or a file MuPDF keeps repairing during the check | Sugo, worker | `PDF_UNSUPPORTED` |
| Opens, ≤ 5 000 pages | Worker | `PDF_INVALID`, `PDF_TOO_LARGE` |
| No password needed (a PDF restricted only by an owner password opens normally) | Worker | `PDF_ENCRYPTED` |
| No Brotli name in any object, as MuPDF parsed and prints it, **before any stream is decoded** | Worker | `PDF_UNSUPPORTED` |
| No Brotli name anywhere in a stream MuPDF may run as content (anything but an image, and whatever pages, Type 3 glyphs, patterns, appearances and soft masks use), nor in each page's content joined as MuPDF joins it; in an image's pixels, no Brotli name after a filter key (first worker start only; restarts read the same checked bytes); a stream MuPDF refuses to decode is refused too | Worker | `PDF_UNSUPPORTED` |
| Worker failed to open, or kept failing | Sugo | `PDF_EXTRACTION_FAILED` |

**Brotli is refused wherever its name appears**, not only where a parser would read it as a filter. A first version matched MuPDF's parser: three security review rounds on 2026-11-02 each found new places where its reading of the bytes differed from MuPDF's (`/F` as the filter key, signed and unspaced references such as `5+0R`, `#xx` escapes that become delimiters, comments and strings in arrays, an inline image split across content streams, `stream` followed by a space, object streams decoded while opening). The maintainer chose the simpler rule: a whole name `/Br` or `/BrotliDecode` has no other use, so it refuses the file wherever it is, and a filter must be written as names, so no reference needs recognising. MuPDF decodes object streams and cross-reference streams while opening the file, before the worker can check anything; their dictionaries are never compressed, so the raw check covers them. The worker then checks every object as MuPDF itself prints it, which covers any filter given by reference, and every stream MuPDF may run as content, whatever its `/Subtype` claims. Only in an image's pixels does the abbreviation occur by chance: there only a name after a filter key counts. Measured on 74 PDFs from the maintainer's PCs (2.3 GB decoded): none refused for Brotli; the "/Br anywhere" rule applied to pixels too would have refused 2. Names are read up to the next delimiter before their escapes are undone, arrays and dictionaries token by token, with a total work cap (four times the input plus 64 KB) that refuses; the patterns are possessive and cannot backtrack. If MuPDF repairs the file during the check, the list of streams is taken again until it stops changing; a file still changing after four attempts is refused. The Brotli checks are removed once a PyMuPDF with MuPDF ≥ 1.28.6 is adopted.

### Pages

- **Native page:** text lines with font size, bold and monospace; reading order by the XY-cut shared with the image extractor (`sugo.extractors.reading_order`, which also holds the shared code-indentation and box helpers). Paragraphs split on style changes and bullets. Block types: heading (font ≥ 1.2 × the page's body size, ≤ 3 lines; levels by size rank on the page, sizes within 10% of each other sharing a level), list item (bullet `•◦▪‣●○■·` dropped; dashes are not bullets), code (all monospaced; indentation rebuilt from position and leading spaces), paragraph.
- **Hidden text:** a span is hidden when it is drawn invisible (render mode 3, zero alpha, clipped away), smaller than 2 pt, outside the page, or does not stand out on the page rendered at 72 DPI (its colour is within 32 levels of the background, or nothing at all is drawn in its box, as for text under an opaque shape). Hidden spans are split from visible ones on the same line; a run's visibility is set by its first span with text, so a hidden space cannot carry a hidden word into visible text. A page's hidden lines form **one block flagged `hidden`**, after the visible blocks. The new `HiddenTextCleaner` proposes removing it with a reason; the core applies it as a soft deletion (principle 3).
- **Scanned page:** images cover ≥ 50% of the page and fewer than 20 visible characters exist. The page is rendered at 200 DPI (less for very large pages) and read by the image OCR pipeline, with screenshot rules (chat, status bar) switched off. **Its own text layer is not trusted:** it may differ from what the page shows. It is kept as a hidden block.

### Measured

On the reference machine: 100 dense native pages in 3.1 s (**32 pages/s**, target ≥ 20), including the visibility render and worker start-up.

## Alternatives considered

| Alternative | Why not |
|---|---|
| PyMuPDF in Sugo's own process | A memory-safety bug in MuPDF would compromise Sugo itself |
| `multiprocessing` with pickled results | Unpickling a compromised worker's output runs its code |
| Trusting the text layer of scans | Fast, but a PDF could show one text and feed the LLM another |
| Removing hidden text in the extractor | Extractors do not remove; cleaners propose and the core applies (ADR-041) |
| Only marking scanned pages illegible | Loses content; the maintainer chose OCR |
| `find_tables()` for ruled tables in this step | Left for a follow-up: table text is still extracted as paragraphs, nothing is lost |

## Consequences

- New stable error codes: `PDF_INVALID`, `PDF_ENCRYPTED`, `PDF_TOO_LARGE`, `PDF_UNSUPPORTED`, `PDF_EXTRACTION_FAILED`.
- New IR flag `hidden`, part of the output schema.
- Each document pays for a worker start (about 0.3 s) and one decoding of all its streams, and each page for a 72 DPI render.
- Residual risks:
  - text hidden by other means stays visible to the LLM: clipping paths MuPDF does not report, colour tricks over images, or a text layer that disagrees with an image on a page that is not a scan;
  - headings are judged page by page, so levels may differ between pages; harmonising them needs a cleaner decision that changes a block, deferred to the extension API (ADR-044);
  - Windows has no memory cap or core-dump switch in the worker.
  - until MuPDF 1.28.6, false refusals: a document whose text or objects contain the name `/Br` or `/BrotliDecode` (a manual about PDF filters), and any document with one stream MuPDF cannot decode (6 of the 74 measured PDFs). The latter is to be revisited in step 8.
