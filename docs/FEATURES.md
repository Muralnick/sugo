# Features

Levels change engine power, not available features: interfaces, cleaning, chunking and metrics exist at every level.

## Common to all levels

| Area | Features |
|---|---|
| Cleaning | Headers, footers, page numbers; book running heads (alternating), index, table of contents, blank and copyright pages; recurring disclaimers, also across documents; duplicate paragraphs; decorative images; per-script Unicode normalisation; hyphenation recomposition via language packs; tracking-URL stripping; hidden text and invisible characters |
| Control | Compression levels (conservative, balanced, aggressive); recipes; removal preview; per-removal explanation; aliases and shortcuts |
| Chunking | Heading-aware, token budget, tables kept whole, CJK-aware segmentation, page and heading-path metadata, content-addressed ids |
| Outputs | Markdown (optional front matter), JSON, JSONL |
| Metrics | Tokens per stage and per cleaner; image-cost comparison for Claude, Gemini, OpenAI; OCR quality report; local savings history |
| Images | Hybrid mode: text, provider-optimised image, or both |
| Inputs | Folders, archives, emails with attachments, PDFs with attachments; plan before large jobs |
| Long documents | Streaming, checkpoint/resume, per-page cache |
| Interfaces | Python API, CLI and interactive shell, local web UI, MCP server, clipboard mode, watched folder, tray icon |
| Companies and legal | Anonymization with local restore map, offline mode, audit log, reproducible output, policies |
| Safety | Size/page/time limits, no macros, archive protections, backend fallback, backups |

## By level

| | lite | normal | quality |
|---|---|---|---|
| Hardware | CPU, < 1 GB RAM | CPU, ~2–3 GB RAM | GPU recommended |
| Native PDF | PyMuPDF | + Docling on hard pages | + VLM on hard pages |
| OCR | PP-OCRv6 tiny/small + Korean | PP-OCRv6 medium + Korean | PaddleOCR-VL-1.6 with OCR cross-check |
| Screenshots (chat, code, UI, scrolling) | Yes | Yes | Yes, more robust |
| Tables | Simple | Complex, cross-page merge | Irregular and scanned |
| Office, EPUB, email, HTML | Lightweight dedicated libraries | Docling | Docling |
| Charts to tables, formulas to LaTeX | No | Partial | Yes |
| Vertical Japanese, handwriting, damaged scans | No | Limited | Yes |

Memory and disk figures will be confirmed by benchmarks.

## Work profiles

`personal`, `dev`, `rag`, `office`, `legal`, `research`, `full` — see ARCHITECTURE §15.

## Supported formats

| Category | Formats | Backend | Notes |
|---|---|---|---|
| PDF | Native, scanned, mixed | PyMuPDF, OCR, Docling, VLM | Per-page routing |
| Images | PNG, JPEG, WEBP, BMP, TIFF (multi-page), GIF (first frame) | Image pipeline | |
| Phone photos | HEIC, HEIF | Image pipeline + `pillow-heif` | Default iPhone format |
| Modern Office | DOCX, PPTX, XLSX | lite: dedicated libraries; normal/quality: Docling | |
| Legacy Office | DOC, PPT, XLS | LibreOffice conversion | Only if LibreOffice is installed |
| OpenDocument | ODT, ODS, ODP | Docling | |
| E-books | EPUB | Docling | |
| Web | HTML, MHTML | Docling | |
| Email | EML, MSG, Italian PEC | Docling, `sugo-pack-italy` | Attachments as containers |
| Italian e-invoices | FatturaPA XML | `sugo-pack-italy` | |
| Archives | ZIP, TAR (+gz/bz2/xz); 7z via pack | Containers | RAR unsupported |
| Text | TXT, Markdown, CSV | Cleaning and chunking only | |
| Apple | Pages, Numbers, Keynote | Docling | Low priority |
| Future | Audio, video | `sugo.media` extensions | Planned |
