# ADR-046: Multi-pass conversion pipeline (standalone)

**Status:** Accepted  
**Date:** 2026-10-29  
**Deciders:** project author  
**Implements:** ADR-006 (multi-pass processing), ADR-001 (routing, `lite` level), ADR-045 (page store), ARCHITECTURE §2  
**Adds error code:** `INPUT_UNSUPPORTED`  
**Amends:** ADR-043 (worker start page and stream-check argument)

## Context

Roadmap step 5d joins the pieces built so far: the PDF and image extractors, the edge analyzer, the cleaners, the Markdown serializer and the page cache. v0.1 runs in standalone mode (no shared engine, ADR-018) and has no extension registry yet, so the built-in components are wired directly.

## Decision

`sugo.core.pipeline.convert(data, cache=None)` and `convert_file(path, cache=None)` return a `Conversion`: the Markdown, the input kind, the source SHA-256, the page count and the number of blocks removed per cleaner.

- **Routing by content:** the PDF signature in the first 1 024 bytes sends the input to the isolated PDF extractor; PNG, JPEG and WEBP magic bytes to the image pipeline. The file name is never used. Anything else raises `InputUnsupportedError` with the new stable code **`INPUT_UNSUPPORTED`** (maintainer decision), whose message lists the accepted formats.
- **Pass 1, extraction:** each page goes into the page store, which is the extraction level of the page cache (ADR-045). Cached pages from an earlier run are not laid out or read with OCR again: the PDF extractor starts at the first page missing from the cache (new `start` argument) and skips cached pages after it (new `skip` argument: the worker still sends them and they are validated, but not processed; a failure on a skipped page does not replace the cached one). **The whole document is still checked** before any page: the worker's search of every decoded stream for Brotli (ADR-043) is now tied to the first worker start, not to page 0, through an explicit `check`/`trust` argument whose default is to check. Pages the worker failed to read are not cached, nor what was cleaned from them, so they are retried on the next run, and only they are.
- **Pass 2, analysis:** the edge analyzer observes every page, read back from the page store one at a time.
- **Pass 3, clean and render:** cleaners run in a fixed order with the statistics: hidden text, UI chrome, page numbers, headers and footers. Every cleaner takes `propose(page, stats)`; the core applies the decisions (ADR-041). Cleaned pages go to the output level of the cache, keyed by the extraction key, the cleaner list and **a digest of the document's statistics**: a cleaned page depends on every page, so if any page reads differently (a failed page that now reads fine), every page is cleaned again.
- **Pages joined by a blank line** (maintainer decision): no page markers in the Markdown. Page provenance comes with the JSONL chunks (step 6).
- **Memory:** one page in memory at a time; the Markdown itself is the only thing that grows with the document. Without a persistent cache the job uses an ephemeral one, deleted at the end; if even that cannot be created, the job keeps its pages in memory. An extracted page the cache refuses (disk nearly full, busy) is kept in memory instead; a page that vanished from the store (cache cleared by another process) is extracted again once, with a warning, and kept in memory. Cleaned pages the cache refuses are not kept: nothing reads them back.
- **Engine identity in the keys:** the input kind and the versions of PyMuPDF, RapidOCR, ONNX Runtime and Pillow; Sugo's code and model hashes are already in every key.

## Alternatives considered

| Alternative | Why not |
|---|---|
| Route by file extension | A renamed file would reach the wrong parser; content cannot lie about its own format to the parsers that check it |
| Page markers in the Markdown | About 6 tokens per page for information the chunks already carry |
| Keep all pages in memory between passes | Memory would grow with the document (ADR-006) |
| Skip the full stream check when resuming | A resumed job would trust bytes no worker searched in this run |
| Cache failed pages | A timeout on a busy machine would become permanent |
| Key cleaned pages by their own page only | Statistics come from the whole document; a page that changes would leave the others cleaned with stale statistics |
| Resume from the first missing page and redo everything after it | One failed page early in a scanned book would redo OCR on all the following pages on every run |

## Consequences

- New stable error code `INPUT_UNSUPPORTED`.
- Measured on the reference machine with 40-line native pages: 32–36 pages/s on a first run, 125–225 pages/s when every page is cached (the worker still opens and checks the file); peak memory 126 MB for 100 pages and 143 MB for 400, most of it the benchmark's own PDF.
- Residual: the Markdown string grows with the document; streaming output comes with the exporters (step 6). A paragraph split by a page break stays two paragraphs.
