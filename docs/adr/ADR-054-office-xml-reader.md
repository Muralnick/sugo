# ADR-054: Light Office and XML reader

**Status:** Proposed  
**Date:** 2026-10-31  
**Deciders:** project author  
**Implements:** ROADMAP v0.1 "Office (DOCX, XLSX, PPTX) and XML through a light reader", ADR-007 (`lite` level), ADR-018 (process isolation), THREAT_MODEL (XXE, hidden text)  
**Updates:** ADR-007 ("Office via lightweight dedicated libraries" becomes Sugo's own reader), ADR-046 (routing by content), ADR-043 (its worker plumbing becomes shared)  
**Amends:** IR flags (ADR-005): new `secret` flag  
**Requires:** ADR-053 merged first  
**Adds error codes:** `OFFICE_INVALID`, `OFFICE_UNSUPPORTED`, `OFFICE_TOO_LARGE`, `XML_INVALID`, `XML_TOO_LARGE`, `OFFICE_EXTRACTION_FAILED`

## Context

On 2026-10-30 the maintainer moved Office and XML into v0.1, through a light reader and without Docling, which stays the `normal` engine of v0.2 (complex layouts, legacy formats).

DOCX, XLSX and PPTX are ZIP archives of XML parts (Office Open XML). They bring three risks: XML attacks (external entities, entity expansion), ZIP bombs (a few kilobytes that expand to gigabytes), and content a person does not see but an LLM reads (hidden text, hidden sheets, comments, speaker notes).

The libraries ADR-007 had in mind, `python-docx` and `python-pptx`, parse with `lxml`, not `defusedxml`, against a hard rule of the project; together with `openpyxl` they add three or four packages. Sugo needs only the text, the structure and the tables.

## Decision

### Own reader on `zipfile` and `defusedxml` (maintainer decision)

- Sugo reads Office Open XML itself with the standard library's `zipfile` and **`defusedxml` 0.7.1** (PSF-2.0, on the allow-list, pure Python, no dependencies). It is a base dependency: the reader itself needs nothing from the `lite` extra. In v0.1 the pipeline module still loads the `lite` packages for every input, so in practice `sugo[lite]` is installed anyway; loading them only for PDF and images is a later clean-up.
- Parsing uses `defusedxml.ElementTree.iterparse` with **`forbid_dtd=True`**, entities and external references forbidden. Office parts never carry a DTD. A generic XML file with one (old DocBook, `<!DOCTYPE html>`) is refused with `XML_INVALID`.
- Each part is held as a tree while it is laid out, since numbering, notes and records refer to each other; the part and element limits below keep that tree well inside the worker's memory cap. A spreadsheet may need streaming in its own PR.
- `defusedxml` has had no release since 2021. It only wraps the standard library's parser, so it moves with Python's own fixes; if it stops working with a future Python, the same checks can be done with `xml.parsers.expat` handlers in one module, with an ADR.

### Isolation

The reader runs in a **worker process**, like the PDF extractor (ADR-043): `python -I -m sugo.extractors.office.worker`, no shell, the file on stdin, results as length-prefixed JSON frames validated by strict pydantic models, never pickle. The frames, the process handling, the resource limits and the private stdout of ADR-043 move to a shared module, `sugo.extractors.worker`; the PDF extractor uses it unchanged. The worker gets the same core-dump switch and, on Linux and macOS, 1.5 GB address-space cap. Pure Python code cannot be interrupted from inside the same process, so the worker is what makes the time limits real: opening 60 s, each page 30 s, the whole file 300 s. A page that fails, stalls or crashes the worker is marked illegible and a fresh worker continues; after 3 restarts the file is refused with `OFFICE_EXTRACTION_FAILED`.

### Recognising the file by its content

| Content | Kind |
|---|---|
| ZIP (`PK\x03\x04`) with `[Content_Types].xml` whose main part is a Word document, template or macro-enabled document | `docx` |
| The same for a workbook (`.xlsx`, `.xltx`, `.xlsm`; not the binary `.xlsb`) | `xlsx` |
| The same for a presentation (`.pptx`, `.potx`, `.pptm`) | `pptx` |
| Text that starts, after an optional BOM and white space, with `<?xml` or `<` and a name character | `xml` |
| OLE compound file (`D0 CF 11 E0`): legacy `.doc/.xls/.ppt` or a password-protected Office file | refused, `OFFICE_UNSUPPORTED` |
| Any other ZIP | refused as before (`INPUT_UNSUPPORTED`) |

Macro-enabled files are read like the others: macros are never run nor output. The `kind` field of the CLI's `--json` and of MCP responses gains the values `docx`, `xlsx`, `pptx` and `xml`, an additive change. SVG and XHTML are XML and are read as generic XML in v0.1.

### Limits

| Limit | Value | Refusal |
|---|---|---|
| File size | Office: 200 MB, as for PDF. Generic XML: 50 MB, as its tree takes about ten times its size | `OFFICE_TOO_LARGE` / `XML_TOO_LARGE` |
| ZIP entries | 10 000 | `OFFICE_TOO_LARGE` |
| Uncompressed size of one part | 50 MB, counted while decompressing (header sizes are not trusted) | `OFFICE_TOO_LARGE` |
| Uncompressed size of all parts read | 300 MB | `OFFICE_TOO_LARGE` |
| Compression ratio of a part over 1 MB | 200 : 1 | `OFFICE_TOO_LARGE` |
| XML nesting depth | 256 | `OFFICE_INVALID` / `XML_INVALID` |
| XML elements | 2 000 000 in one Office part; 1 000 000 in a generic XML file | `OFFICE_TOO_LARGE` / `XML_TOO_LARGE` |
| Spreadsheet cells read | 2 000 000 | `OFFICE_TOO_LARGE` |
| Encrypted ZIP entries, broken archive, missing main part | — | `OFFICE_INVALID` |

Nothing is ever extracted to disk, so entry names with `..` or absolute paths do no harm; parts are found only through the package's relationships, and **external relationships are never followed** (no download of linked images, templates or data). An external hyperlink is kept as text and goes through the tracking URL cleaner (ADR-050).

### Pages

The IR keeps Document → Page → Block (ADR-005):

- **DOCX:** a new page at every section break and explicit page break; a document without them is one page. Page numbers are therefore not Word's printed page numbers, and the output says so nowhere it could be mistaken for them.
- **XLSX:** one page per sheet, in workbook order.
- **PPTX:** one page per slide, in presentation order.
- **XML:** one page.

Each page is cached like a PDF page (ADR-045); the reader's version is part of the key.

### What is read

**DOCX**
- Paragraphs, with headings from the paragraph's outline level or the built-in `Title` and `Heading 1–9` styles; lists from numbering, bullets or numbered, with their level; tables as table blocks (ADR-042), a merged cell's text in its first cell only; hyperlinks as Markdown links; text boxes in document order; fields as their displayed result.
- Footnotes and endnotes after the page that cites them, with their number.
- Each section's header and footer once, flagged as running header or footer, so the existing cleaner proposes their removal with a reason (ADR-044).
- Equations and embedded objects are not guessed: each becomes a block marked not converted. Until the image PR, images are marked the same way.
- Numbered items keep Word's label ("2.1."); the IR has no list levels, and the label carries the structure. The serializer escapes a label such as "1." that would open a Markdown list inside the item.
- `mc:AlternateContent` is read from its first choice only; the fallback repeats the same text box for older readers.
- The whole document is laid out before its first page, since numbering and notes depend on what comes before; a layout error therefore refuses the file (`OFFICE_EXTRACTION_FAILED`) instead of marking one page. A DOCX is laid out again on every run, in well under a second; its cleaned pages are still cached.
- Recognised in Sugo's own process from the ZIP directory and a byte search in `[Content_Types].xml`, without parsing XML; the worker parses everything else.
- Measured on o200k_base: a five-article contract with a ten-row table is 1 805 tokens as `document.xml`, 325 as plain extracted text and **314** as Sugo's Markdown, with one hidden instruction removed.

**XLSX**
- Each sheet becomes one or more tables; empty outer rows and columns are trimmed. A sheet over 200 rows is split into tables of 200 rows; when the first row is all text it is treated as the header and repeated.
- Cells show their **cached value**: formulas are never evaluated and their text is not output. Dates (built-in date formats and custom formats with day, month or year codes) become ISO 8601; other numbers are written with at most 15 significant digits, as Excel's "General" format shows them. Shared and inline strings are both read.
- Charts, pivot caches and images in sheets are marked not converted in v0.1, except images, below.

**PPTX**
- Shapes in reading order by position, through the XY-cut shared with the image and PDF extractors; group shapes are entered. The title placeholder becomes a heading, body text keeps its bullet levels, tables become tables.
- Text shown only by layouts and masters (placeholder prompts such as "Click to add title") is not read.

**XML**
- An indented outline, two spaces per level: `name: text`, attributes as `@name: value`, namespace prefixes dropped, white space collapsed. Elements with neither text, attributes nor children carry no content and are left out; so are comments, processing instructions and the `xsi:schemaLocation` attributes, which only point at schemas. Text between child elements (mixed content) keeps its place as a line of its own.
- Three or more consecutive sibling records with the same name and distinct leaf fields (such as invoice lines) become a table under a line with their name; columns are the record's attributes (`@id`) and fields, in first-seen order, and a missing field is an empty cell. Tables over 200 rows are split, the header repeated.
- A Markdown paragraph loses the indentation of its first line (ADR-042), so the paragraph that resumes after a table starts with its parent's line again.
- Measured on o200k_base: an electronic invoice (FatturaPA layout, 20 lines) goes from 2 293 to 873 tokens (**−62%**); a small configuration file from 57 to 47 (−18%).

### Hidden content is marked removed (maintainer decision)

What a reader of the document does not see stays in the IR, flagged `hidden`, and a cleaner proposes its removal with a reason; the core applies a soft deletion (principle 3, ADR-041), as for hidden PDF text (ADR-043). Covered:

- DOCX: runs with `vanish` (directly or through their style), text under 2 pt, white text without shading or highlight (not in tables, whose styles often paint the cell dark); comments; deleted and moved-away text of tracked changes (the output shows the document **with changes accepted**: insertions kept, deletions removed). A text box anchored in such a run is hidden with everything in it, tables included (security review).
- XLSX: hidden and very hidden sheets, hidden rows and columns; cell comments and notes.
- PPTX: hidden slides, speaker notes, comments, shapes marked hidden or placed entirely outside the slide.

### Images inside Office files (maintainer decision)

- With `sugo[lite]` installed, embedded PNG, JPEG and WEBP images (recognised by content) go through the same OCR pipeline as image files, with its pixel and size limits, at the position where they are anchored. At most 200 images per document; the rest are marked not converted.
- Images under 32 × 32 pixels are decoration: flagged and removed with a reason.
- Without `sugo[lite]`, and for other formats (EMF, WMF, GIF, TIFF), each image becomes a block marked not converted. Nothing is ever described or guessed.
- OCR runs in Sugo's process as for image files, not in the Office worker, which never loads the image stack.

## Alternatives considered

| Alternative | Why not |
|---|---|
| `python-docx`, `openpyxl`, `python-pptx` | `lxml` instead of `defusedxml` (an exception to a hard rule), three or four more packages, more than Sugo uses |
| Docling's Office backend now | Heavier, parses with `lxml`, many security advisories in 2026; planned for v0.2 (`normal`) |
| Reading in Sugo's own process | No way to stop a stalled parse, and a parser bug would hit Sugo itself |
| Hidden content in the output | Instructions hidden in a document would reach the agent |
| Word's last rendered page breaks as pages | Saved by Word only, often missing or stale |
| Evaluating formulas | A formula engine is large and could disagree with the file; the cached value is what the author saw |
| Generic XML as plain text nodes | Loses which value belongs to which field; an outline costs few tokens and keeps it |

## Consequences

- New base dependency `defusedxml`; new stable error codes listed above; new `kind` values; new IR flag `secret` (ADR-053), not part of the chunk schema.
- Agents can now ask for XML files, so ADR-053 must be merged before this reader.
- Each Office file pays a worker start (about 0.3 s). Speed and token savings are measured on DOCX, XLSX, PPTX and XML samples in the implementation PR and in step 8.
- Residual risks:
  - text hidden by means not listed above (text the same colour as a background image or shape, tiny text set through a theme) reaches the LLM;
  - complex layouts (multi-column DOCX, SmartArt, floating shapes) may come out in a different order; Docling handles them in v0.2;
  - the XML outline is cleaned like prose, so the hyphen-join rule (ADR-050) could fuse a value ending in "-" with the next field name; it needs the fused word to appear elsewhere in the document, which field names make very unlikely. A block type for structured data, which text cleaners skip, would close it;
  - Windows has no memory cap or core-dump switch in the worker (as ADR-043).
