# Sugo — Architecture

Status: design complete, October 2026. Decisions are recorded in [`adr/`](adr/). Security analysis: [THREAT_MODEL.md](THREAT_MODEL.md). Testing: [TESTING.md](TESTING.md).

---

## 1. Context and goals

Sugo converts documents and images into clean Markdown for RAG systems, agents and LLM chats, removing noise to minimise tokens while preserving meaning, structure and tables. All processing is local.

### Target users

| User | Main need |
|---|---|
| Developers and agent users (Claude Code, Codex, …) | MCP integration, fast CLI, JSON output |
| RAG database maintainers | Ready chunks, metadata, JSONL, incremental updates |
| Companies and law firms | Offline mode, anonymization, audit log, reproducibility |
| Everyday users | Clipboard mode, simple graphical interface |

### Non-functional requirements

- Fully local and offline after model download; no telemetry.
- **Minimum hardware**: 8 GB RAM, 4-core CPU, no GPU. Default memory budget: 2.5 GB.
- **Recommended for `quality`**: NVIDIA GPU with 4–6 GB VRAM.
- **Reference machine for benchmarks**: 8 GB RAM, Intel Core i5 10th gen (H series), GTX 1660 Ti 6 GB.
- **Languages**: Italian, Spanish, English, French, German, Japanese, Mandarin Chinese, Korean.
- **Platforms, by priority**: Linux, Windows, macOS. Python 3.12.

### Terminology

| Term | Meaning |
|---|---|
| Level | Engine power: `lite`, `normal`, `quality` |
| Profile | Work profile: `personal`, `dev`, `rag`, `office`, `legal`, `research`, `full` |
| Recipe | Treatment of a document type: `book`, `contract`, `chat-screenshot`, `code-docs`, … |
| Pack | Optional functional distribution (e.g. `sugo-pack-anonymize`) |
| Port | Interface over the core: Python API, CLI/shell, web UI, MCP server, background service |
| Container | Something holding other inputs: folder, archive, email, PDF with attachments |
| IR | Intermediate representation: Document → Page → Block |

---

## 2. Pipeline

```
input ─► Source/Container ─► Router ─► Extractor ─► IR ─► Analyzer ─► Cleaners ─► Serializer ─► Chunker ─► Exporter
                               │        (per page)        (global)    (chain)     (Markdown)                 │
                               │                                                                             ▼
                               └─ picks a backend per page by type,        MetricsTracker: tokens per stage and per
                                  text layer, complexity and hardware       cleaner; image-cost baseline per provider
```

The v0.1 standalone pipeline, its routing by content and pass order are in ADR-046. **Routing is per page, not per document** (ADR-001): native-text pages go through PyMuPDF; complex tables, Office and scans through Docling (`normal`); the hardest pages through a VLM (`quality`).

### Multi-pass processing (ADR-006)

```
Pass 1 · Extraction     page → page store (SQLite), doubling as checkpoint
Pass 2 · Analysis       lightweight document-wide statistics (repeated bands, fonts, patterns)
Pass 3 · Clean + render page by page, using the statistics
Pass 4 · Chunking       chunks with metadata
```

Memory use does not depend on document length. Pages may be processed **out of order**, grouped by backend, and reassembled (ADR-018).

---

## 3. Intermediate representation (ADR-005)

```
Document
├── source: path or URL, container path, type, SHA-256, page count, detected languages
└── pages: [Page]                       (never all in memory)

Page
├── index, width, height, rotation
├── origin: native | ocr | vlm
└── blocks: [Block]

Block
├── id
├── type: heading | paragraph | list_item | table | code | chat_message | image | caption |
│         footnote | formula | header | footer | page_number | ui_chrome
├── text, script (latin | han-kana | hangul | …), language, confidence
├── bbox normalised to 0–1
├── style: font size, bold, monospace (when available)
├── heading_level, reading_order
├── table: cell grid with spans and header rows (type = table)
├── speaker: left | right (type = chat_message; neutral side, ADR-040)
├── origin_engine, flags (illegible, suspicious_instruction, low_agreement, hidden, …)
├── time_range: reserved for audio/video
└── removed, removed_by, reason
```

Models are immutable, strictly validated pydantic models (ADR-037): a change is a new validated copy, so no stage can bypass the invariants. Normalised coordinates let the same positional rules work on phone screenshots, 4K monitors and A4 pages. **Soft deletion** makes every removal explainable, enables per-cleaner metrics and the preview, and enforces principle 3.

---

## 4. Module contracts

| Module | Contract | Notes |
|---|---|---|
| Source | `fetch(ref) → content + metadata` | Reaches the internet only through the network gateway (ADR-016, ADR-036) |
| Container | `list() → entries`, `open(entry) → content` | Folders, archives, emails, PDFs with attachments (ADR-020) |
| Extractor | `supports(input) → score`, `extract(input) → stream of Page` | Router picks the best score; PDFs are parsed in an isolated worker (ADR-043) |
| Analyzer | `observe(page)`, `finalize() → stats` | For cleaners needing document-wide context; repeated page edges in ADR-044 |
| Cleaner | `propose(page, stats) → [Decision]` | **Proposes** removals or checked text edits; the core validates and applies (ADR-028); internal form in ADR-041 and ADR-050 |
| Detector | `detect(page) → [Annotation]` | Chat, code, tables, UI chrome, injection attempts |
| Language pack | Recomposition and normalisation rules per language | ADR-025 |
| Serializer | `render(blocks) → Markdown` | Cheapest table format that preserves structure (ADR-002); format in ADR-042 |
| Chunker | `chunk(document) → [Chunk]` | Heading path, pages, token budget, tables kept whole |
| Exporter | `export(...) → files` | Markdown, JSON, JSONL |
| Optimizer | `optimize(image, provider) → image` | Provider-aware image budget (ADR-017) |
| MetricsTracker | Hook after each stage | Text and image baselines (ADR-003) |

**Error handling:** each page has a timeout; failing backends fall back (quality → normal → lite); unrecoverable pages are reported and marked in the output, never silently dropped.

---

## 5. Images and screenshots

```
extractors/image/
├── loader.py       safe decoding: magic bytes, size and pixel limits before decoding
├── classifier.py   screenshot · document photo · no text (skip early)
├── preprocess.py   dark mode inversion, upscaling small fonts, deskew and perspective
├── ocr_engine.py   multi-script OCR with confidence threshold; hash-checked models, low-confidence lines kept as illegible
├── layout.py       reading-order reconstruction (lines, columns, blocks): recursive XY-cut, lines joined with newlines, illegible lines as separate flagged blocks
├── extract.py      decode → classify → preprocess → OCR → layout, one IR page per image
└── detectors.py    chat (speaker side), code (indentation rebuilt), UI chrome; tables later (ADR-040)
```

Handled cases: dark mode; UI noise (status bars, clocks, tabs, menus); chats (speaker from alignment); code (indentation rebuilt from x coordinates); icon/emoji garbage; scrolling screenshots with overlapping lines; duplicates (perceptual hash); HEIC phone photos.

**OCR (ADR-004):** RapidOCR with PP-OCRv6 (one model covers Chinese, English, Japanese and 46 Latin-script languages) plus a dedicated Korean model. Text detection runs once; recognition uses the model matching the script.

---

## 6. Languages (ADR-024, ADR-025)

Every selected language gets a **language pack** with recomposition and normalisation rules, all with equal priority:

| Language | Key traps |
|---|---|
| Italian | Elisions (`dell'albero`), accented vowels misread as `e'`, `« »` |
| Spanish | Inverted `¿ ¡` often lost by OCR, `ñ` |
| French | Elisions, special spaces before `; : ! ?` and inside `« »`, ligatures `œ æ` |
| German | Long compounds; pre-1996 hyphenation changed letters (`Zuk-ker` → `Zucker`) |
| English | True compound hyphens (`well-known`) vs line-break hyphenation |
| Japanese | Join lines **without** spaces; remove furigana duplicated by OCR; width normalisation |
| Chinese | Join without spaces; full-width punctuation; never convert simplified ↔ traditional |
| Korean | Join with spaces; recompose decomposed Hangul syllables |

Hyphen resolution order: (1) the document's own lexicon (the joined word appears elsewhere), (2) per-language frequency lists, (3) **when in doubt, leave it**. Blocks in non-installed languages get only universal safe rules. New languages arrive through the `sugo.languages` extension family.

**Italian priority** (pack `sugo-pack-italy`): PEC certified emails (nested `postacert.eml`, `daticert.xml`), FatturaPA e-invoices, Italian anonymization (codice fiscale with checksum, partita IVA, IBAN, plates), Italian legal recipes.

---

## 7. Metrics and hybrid image mode

Two baselines (ADR-003): raw vs clean text (`tiktoken`, `o200k_base` default, vocabulary bundled and hash-verified so counting never touches the network, ADR-038), and **image cost vs extracted Markdown** per provider. Provider formulas are **data files** with source, date and verification status:

| Provider | Formula (as documented, October 2026) | Status |
|---|---|---|
| Claude | ⌈w/28⌉ × ⌈h/28⌉ after scaling to the largest size within both limits (port of the official reference implementation); high-resolution tier (Claude 4.7 and later): long edge ≤ 2576 px, ≤ 4784 tokens; standard tier (other models): ≤ 1568 px, ≤ 1568 tokens | Verified (October 2026) |
| Gemini | 258 tokens if both sides ≤ 384 px; otherwise 258 per 768×768 tile | Verified (October 2026) |
| OpenAI | Patch-based models (gpt-6-astra, gpt-5.6, gpt-5.5, gpt-5.4, gpt-5.2, gpt-4.1-mini): 32×32 patches, maximum dimension and patch budget per model and detail level, then a multiplier; images above 30 000 patches are rejected. Tile-based models (gpt-5.1, gpt-4.1, gpt-4o, gpt-4o-mini): base tokens plus tokens per 512×512 tile, base only at detail `low` | Verified (October 2026); deprecated models not listed |

Savings against images are not guaranteed (a small sparse screenshot sent to Gemini may cost as much as its text). The **hybrid mode** (ADR-017) picks per image: text only, provider-optimised image (crop noise, resize to tile/patch boundaries), or both. Percentages, not absolute counts, are the headline metric, since tokenizers differ across LLMs.

---

## 8. Generative model safeguards (ADR-026)

| Level | Models | Generative? |
|---|---|---|
| lite | OCR detection + recognition | No |
| normal | + layout and table structure | No |
| quality | + VLM (PaddleOCR-VL, ~0.9B) | **Yes** |

Safeguards: OCR/VLM **cross-check** with agreement score, low-agreement blocks flagged; unreadable areas marked `[illegible]`, never filled; VLM output is data, never instructions; every block records its `origin_engine`. In the `legal` profile the VLM runs only with cross-check enabled.

---

## 9. Process model and resources (ADR-018)

```
                      ┌──────────────────────────────────┐
 CLI · UI · MCP ────► │   Engine (main process)          │  queue, budget, scheduler
 clipboard · watcher  └───┬──────────────┬───────────────┘
              ┌───────────┴───┐  ┌───────┴────────┐  ┌──────────────┐
              │ light workers │  │ model workers  │  │ GPU worker   │
              │ PDF, cleaning,│  │ OCR, layout    │  │ VLM (single) │
              │ rendering     │  │ (loaded once)  │  │              │
              └───────────────┘  └────────────────┘  └──────────────┘
```

| Topic | Decision |
|---|---|
| Isolation | Separate worker processes (`spawn` start method on every OS): crashes and timeouts are contained; memory is returned to the OS on exit |
| Shared engine | One engine per user; all ports connect through a local channel (Unix socket in `$XDG_RUNTIME_DIR`, named pipe on Windows). Auto-starts, auto-stops when idle. Standalone mode for one-shot scripts |
| Memory budget | Tasks declare estimated memory (model card + page estimate) and are admitted only within the budget; bounded queues give backpressure; real usage is monitored |
| Graceful degradation | Under pressure: less parallelism → lower render DPI → smaller model. Never thrash swap |
| Adaptive DPI | A4 at 300 DPI ≈ 26 MB, at 200 DPI ≈ 12 MB: DPI depends on detected text size |
| Model residency | One heavy model at a time on 8 GB; LRU eviction; pages grouped by backend so each model loads once per job |
| Threads | Total threads ≤ physical cores (ONNX Runtime and PyTorch thread pools configured explicitly) |
| GPU | Single GPU worker and queue; batches sized from measured VRAM; CPU prepares the next batch while the GPU works; FP32 fallback when the FP16 self-test fails (GTX 16xx) |
| Priorities | Interactive (clipboard, single files, MCP) preempts background (books, watcher, sync) at page boundaries |
| Warm clipboard worker | Kept warm, unloaded after idle timeout to return RAM |
| Battery | Optional reduced parallelism and no GPU on battery |
| Background jobs | Low CPU and I/O priority (`nice`/`ionice` on Linux) |

---

## 10. Storage (ADR-019)

| Kind | Path (Linux, XDG) | Meaning |
|---|---|---|
| Configuration | `~/.config/sugo/` | `config.toml`, `providers/`, `recipes/`, `profiles/` |
| Regenerable | `~/.cache/sugo/` | `models/`, `cache.db`, `blobs/` — deletable at any time |
| Precious | `~/.local/share/sugo/` | `registry.db`, `anonymization/`, `audit/` — back it up |
| Logs | `~/.local/state/sugo/` | Rotated structured logs |
| Runtime | `$XDG_RUNTIME_DIR/sugo/` | Engine socket, cleared at logout |

Equivalent paths on Windows and macOS via `platformdirs`; every path overridable (`SUGO_CACHE_DIR`, `SUGO_DATA_DIR`) for Docker volumes. Cache format, keys and limits: ADR-045.

- **Two-level per-page cache**: extraction (page hash + engine + model revision) and cleaning/output (extraction key + cleaning-config hash + Sugo version). Changing compression reuses OCR; a new manual edition reprocesses only changed pages.
- **Checkpoint = cache**: an interrupted job resumes because completed pages are cache hits.
- **SQLite** with transactions for the page store and cache (crash-safe, avoids Windows antivirus overhead on thousands of small files); large blobs as content-addressed files.
- Atomic writes (temp + rename); short hashed internal file names (Windows 260-char limit).
- Cache size limit with LRU eviction; orphan cleanup at engine start; disk-space preflight; `sugo cache stats|clean|clear|verify`.
- **Sensitive data**: owner-only permissions (0700/0600); `cache = "ephemeral"`; `retention_days`; anonymization maps never logged, deletable per job, optionally passphrase-encrypted; hash-chained append-only audit log; full-disk encryption recommended (SSD deletion cannot be guaranteed).
- Schema migrations with automatic pre-migration backup; `sugo data export` / `restore` for moving machines.

---

## 11. Containers, folders and archives (ADR-020)

A **container** lists entries and opens them one by one: folders, zip/tar archives, emails with attachments, PDFs with embedded files, PEC envelopes. Containers can nest within limits. Provenance notation: `clients.zip!/2025/contract.pdf`.

| Topic | Decision |
|---|---|
| Folder scan | Recursive, `--include`/`--exclude`, `.sugoignore`; hidden and system folders skipped; symlinks not followed by default |
| Type detection | By content (magic bytes), never by extension |
| Duplicates | Processed once, by hash |
| Failures | One broken file never stops a batch; reported at the end |
| Output | Mirrored folder structure, JSON index, single JSONL for vector databases |
| **Plan first** | Large inputs show a plan (counts, time, space, tokens) before processing; `sugo plan` as a dry run |
| Archive limits | Real decompressed bytes, per-file size, suspicious ratio, nesting depth (default 2, hard max 3), entry count |
| Archive safety | Entries read in place where possible; otherwise extracted into an isolated temp dir with hashed names; symlinks and special files rejected; legacy filename encodings detected; passwords asked interactively, never brute-forced |
| Formats | zip, tar (+gz/bz2/xz) via stdlib; 7z via optional pack; RAR unsupported (non-free tool) |
| Cache | Per entry, by its own hash |
| Agents | MCP accepts only allowed roots; fixed exclusions (`.ssh`, `.gnupg`, keyrings, credential files); above a threshold the plan is returned instead of processing |

---

## 12. Interfaces: one core, five ports (ADR-015, ADR-022)

```
                    ┌───────────── Core (operations) ─────────────┐
                    │ convert · plan · estimate · chunks · explain │
                    └────────────────────┬────────────────────────┘
     ┌──────────────┬──────────────┬─────┴────────┬─────────────────────┐
  Python API     CLI / shell     Web UI        MCP server      Background service
                                                               (clipboard, watcher, tray)
```

### Operations

Operations are defined once with typed pydantic models; MCP tool schemas and the web API's OpenAPI are generated from them.

| Operation | Python | CLI | MCP | Web UI |
|---|---|---|---|---|
| `convert`, `plan`, `estimate`, `chunks`, `preview`, `explain` | ✓ | ✓ | ✓ | ✓ |
| `doctor` | ✓ | ✓ | | ✓ |
| `models.*`, `cache.*`, `setup`, `profile.*` | ✓ | ✓ | read-only | ✓ |

### Error model

```json
{ "code": "MODEL_MISSING",
  "message": "The OCR model for Korean is not installed.",
  "hint": "sugo models pull ocr-korean",
  "details": { "model": "ppocr-korean-rec", "size_mb": 12 } }
```

Stable English codes; translated messages; a suggested action. Python: `SugoError` subclasses. CLI: stderr + exit code. MCP: structured error. Web: HTTP status + same JSON.

### Python API

```python
import sugo

result = sugo.convert("manual.pdf", level="normal", recipe="book")
print(result.markdown, result.metrics.saved_percent)

with sugo.Engine() as engine:
    for event in engine.convert_stream("archive/", profile="rag"):
        ...
    chunks = engine.chunks("archive/contract.pdf", heading="Art. 5")
```

Async variant available. Public = what `sugo` exports.

### CLI and shell

```
sugo manual.pdf                      convert with defaults
sugo manual.pdf -l quality -o out/   level and output folder
sugo contract.pdf -r contract        recipe
sugo plan ./folder                   dry run
sugo stats screenshot.png            savings per provider
sugo clip                            convert the image in the clipboard
sugo watch ~/Pictures/Screenshots    watched folder
sugo doctor [--report]               diagnostics
sugo setup                           guided setup
sugo models pull normal              models
sugo mcp                             MCP server
sugo ui                              web interface
```

Results to **stdout**, progress and messages to **stderr**; colours and progress bars off when not a TTY; `NO_COLOR` respected; `--json` everywhere.

| Exit code | Meaning |
|---|---|
| 0 | Success |
| 1 | Generic error |
| 2 | Usage error |
| 3 | Partial success (some pages/files failed) |
| 4 | Refused for security reasons |
| 5 | Missing model or pack |
| 130 | Interrupted |

**Interactive shell** (`sugo` with no arguments): drag a file or `@path`; `Ctrl+V` converts the clipboard image; `/level`, `/profile`, `/provider`, `/compress`, `/preview`, `/explain`, `/stats`, `/export`; user-defined aliases (e.g. `/legal`); Tab completion, history, `Esc` to cancel; live per-page progress with a running savings counter. Libraries: Typer, Rich, prompt_toolkit.

### MCP server

stdio transport, connected to the shared engine.

| Tool | Main parameters |
|---|---|
| `convert_document` | `path`, `level`, `recipe`, `output` (markdown/chunks), `max_tokens`, `cursor` |
| `plan_conversion` | `path` |
| `estimate_savings` | `path`, `provider` |
| `get_chunks` | `path`, `pages`, `heading`, `max_tokens`, `cursor` |
| `explain_removal` | `document_id`, `block_id` |

**MCP responses respect a token budget** with cursor pagination: a 400-page book is never dumped into an agent's context. Content is wrapped and labelled as document data. Allowed roots, fixed exclusions, plan above threshold, no installs/downloads, rate limits per client, optional forced anonymization (`legal`). Integration kit: MCP config snippets, a Claude Code skill, an `AGENTS.md` fragment.

### Web UI

Local HTTP server (FastAPI) on `127.0.0.1`, random port, session token in the opening URL, `Host` and `Origin` checks (DNS rebinding and cross-site protection). REST endpoints mirror the operations; progress via Server-Sent Events. Drag-and-drop, side-by-side original/Markdown preview with removals highlighted, token counters per provider.

### Background service

Clipboard mode, watched folder and tray icon are engine clients. Linux: XDG Desktop Portal global shortcuts on Wayland (manual shortcut fallback), Wayland/X11 clipboard auto-detection (`wl-clipboard`/`xclip`), StatusNotifierItem tray, systemd user service.

### Internal protocol

JSON-RPC 2.0 over the local channel (same style as MCP), versioned with a handshake; a stale engine after an upgrade is restarted.

---

## 13. Output formats (ADR-023)

```json
{
  "schema_version": "1.0",
  "id": "c_8f3a91e2c04b7d1a5e6f90b2d3c4a5e6",
  "document_id": "d_51c0aa7b9e2d4f6a8b0c1d2e3f405162",
  "text": "## Art. 5 – Withdrawal\nThe contract may be…",
  "tokens": 187,
  "heading_path": ["Supply agreement", "Art. 5 – Withdrawal"],
  "pages": [4, 5],
  "source": "clients.zip!/2025/agreement.pdf",
  "source_sha256": "e3b0c442…",
  "language": "it",
  "source_date": "2025-03-14",
  "sugo_version": "0.1.0",
  "config_hash": "a91f…"
}
```

Full field list, ids and the published schema: ADR-047 (no timestamp, so output is reproducible; ids are 128-bit). Chunk `id` is **content-addressed**: unchanged text keeps its id, so vector databases re-embed only changed chunks. Optional YAML front matter in Markdown (source, hash, version, config). Evolution: added fields = minor; renamed/removed = major with deprecation; cleaning improvements noted in the changelog. JSON Schemas published in `schemas/` and validated in tests. The extension API is versioned separately.

---

## 14. Configuration (ADR-011)

```
defaults < system (/etc/sugo/config.toml) < user (~/.config/sugo/config.toml)
         < project (./sugo.toml or [tool.sugo] in pyproject.toml)
         < environment (SUGO_LEVEL=quality) < command options / shell commands / MCP parameters
```

TOML, pydantic validation, `platformdirs`. The v0.1 subset (user and project files, five keys, `SUGO_*` variables) is in ADR-051. System config can **lock** keys (company policies). Security limits have defaults and **hard bounds** (e.g. archive nesting 0–3, compression ratio 10:1–1000:1, page timeout 5–600 s; sensitive-folder exclusions cannot be disabled).

```toml
[general]
level = "normal"
languages = ["it", "en", "ja"]

[target]
provider = "claude"
image_mode = "auto"          # text | image | both | auto

[cleaning]
compression = "balanced"     # conservative | balanced | aggressive
strip_tracking_urls = true

[chunking]
max_tokens = 512
keep_tables_whole = true

[privacy]
offline = false
anonymize = false
audit_log = false

[storage]
cache = "persistent"         # persistent | ephemeral
retention_days = 0           # 0 = no automatic expiry

[hardware]
device = "auto"              # auto | cpu | cuda | mps
max_ram_mb = 2500

[ui]
language = "auto"

[aliases]
legal = "/profile legal /recipe contract"
```

---

## 15. Guided setup and work profiles (ADR-021)

Two-step installation: a small base (core + `lite` + CLI), then `sugo setup` installs packs, downloads only the needed models and writes a tailored configuration. Developers can skip it (`pip install sugo[normal,dev]`); companies use an answers file (`sugo setup --answers company.toml`).

### Work profiles

| Profile | Enables | Suggested level |
|---|---|---|
| personal | Clipboard, screenshots, GUI, tray | lite |
| dev | Shell, MCP, agent integration kit, JSON, code detection | normal |
| rag | Folders/archives, JSONL, advanced chunking, incremental updates, Docker | normal |
| office | Office incl. legacy, email with attachments, watcher, GUI | lite/normal |
| legal | Anonymization, offline, ephemeral cache, audit log, reproducibility; no web sources | normal |
| research | Books, EPUB, formulas, charts, complex tables, multilingual | quality (GPU) or normal |
| full | Everything | by hardware |

Profiles combine (union of packs); conflicts resolve to the **most protective** setting, with an explanation. Profiles are **data files**; the community can create and share new ones.

### Setup screens (phone-style)

One toggle per screen, pre-set by the profile, irrelevant screens skipped (GPU only if detected). Every screen follows the same four-part card:

| Section | Question answered |
|---|---|
| What it does | Plain-language purpose |
| If YES | What you gain and what it costs (disk, memory, speed) |
| If NO | What you cannot do, and alternatives |
| Good to know | Privacy or security implications |

Sequence: profile(s) → languages → GPU (if present) → clipboard → GUI → agent integration → anonymization → offline. A summary screen lists **"You will be able to / You will not be able to"**, disk and download size, recommended level with reason. "Use recommended settings" skips ahead. Changes later: `sugo setup`, `sugo add <pack>`, `sugo remove <pack>`, `sugo profile add|remove`, `sugo features`; just-in-time install prompts ("This HEIC photo needs the HEIC pack, ~15 MB. Install?"); never from MCP.

Cards are **data files** shared by CLI, UI and documentation, translatable; sizes come from CI measurements, not hand-written estimates. Without an NVIDIA GPU, setup installs **CPU-only PyTorch** (saves gigabytes). Official combinations tested in CI: the seven profiles, minimal install and frequent pairs (e.g. dev + legal). `sugo setup --advanced` exposes every pack individually, labelled "untested combination". Install into a dedicated environment (`uv tool`/`pipx`): Debian-based distributions block system-wide `pip install`. Runtime installs use pinned, hash-verified packages, never in offline mode, and can be forbidden by policy.

---

## 16. Extensions (ADR-012, ADR-028)

Families: `sugo.sources`, `sugo.containers`, `sugo.extractors`, `sugo.analyzers`, `sugo.cleaners`, `sugo.detectors`, `sugo.languages`, `sugo.serializers`, `sugo.chunkers`, `sugo.exporters`, `sugo.providers`, `sugo.media` (reserved). Discovered via Python entry points at startup, **loaded lazily**. Built-in components and official packs use the same mechanism.

**Data extensions** (profiles, recipes, provider formulas, language rule data) execute no code and have lighter requirements than **code extensions**.

### Manifest

```toml
[extension]
name        = "sugo-cleaner-cookie-banner"
version     = "1.2.0"
family      = "cleaners"
api_version = ">=1.0,<2.0"
license     = "MIT"
entry_point = "sugo_cookie.cleaner:CookieBannerCleaner"

[extension.card]
title       = "Cookie banner remover"
description = "Removes cookie consent banners from web pages."
if_yes      = "Cleaner web pages, fewer tokens."
if_no       = "Banners stay in the text."
notes       = "Works only on HTML sources."

[extension.requirements]
ram_mb = 20
gpu    = false

[extension.permissions]
network    = false
filesystem = "job"      # job directory only
subprocess = false
```

Permissions are shown before activation; network-permission extensions are disabled in offline mode and in `legal`. Cleaner ordering comes from declared `after`/`before` dependencies.

### Trust tiers

| Tier | Requirements | Grants |
|---|---|---|
| Installable | Valid, compatible manifest | Manual activation with warning and permission prompt |
| Compatible | Passes `sugo plugin check` (manifest, invariant tests on the corpus, performance budget, licence, own tests, docs, English card) | Listed in the community catalog |
| Verified | Maintainer code and security review, signed releases, pinned deps, active maintenance | Badge; eligible for official profiles |

At runtime, an extension whose proposal would violate a principle (e.g. adding text) is **disabled and reported**. Code extensions run in worker processes; on Linux, declared permissions are **enforced by the sandbox** (THREAT_MODEL §5). Companies can allow-list extensions.

---

## 17. Hardware detection

First run measures RAM, cores, GPU, VRAM and runs an FP16 self-test; a resolver picks engines for the chosen level and explains why. `sugo doctor` shows system, budget, GPU status, available levels, clipboard and shortcut support, sandbox level, installed models; `--report` bundles sanitised diagnostics for bug reports.

---

## 18. Model management (ADR-013)

Model registry entries: task, scripts, levels, format, RAM/VRAM, licence, **pinned revision**, SHA-256, sources (Hugging Face, ModelScope fallback). Downloads on demand with consent, resumable, atomic after verification; single cache with Docling, RapidOCR and Hugging Face caches redirected to it. Offline bundles: `sugo models bundle` / `sugo models install`. Safe formats only (ONNX, safetensors, GGUF), no `trust_remote_code`. MCP never triggers downloads. New model versions become default only after benchmark gates. `sugo models list|prune|licenses|update`.

Offline mode: library offline switches plus a Python-level network guard with logging, enforced in the network gateway `sugo._internal.net` (ADR-036); for certifiable guarantees, documentation explains OS-level methods (container without network, firewall).

Indicative disk footprint (to be measured): lite tens of MB; normal a few hundred MB; quality about 2 GB more.

---

## 19. Enterprise and legal features (ADR-014)

Offline anonymization (names, emails, phones, codice fiscale, partita IVA, IBAN) with a local restore map; coverage statistics and review mode (never claimed 100%); offline mode; hash-chained audit log; reproducible output stamped with version and config hash; locked policies; extension allow-lists; forced anonymization of MCP output.

---

## 20. Backup and disaster recovery (ADR-027)

| Scenario | Protection | Recovery |
|---|---|---|
| Power loss mid-job | Transactions, atomic writes | Re-run: resumes from cache |
| Corrupted cache | Regenerable by design | `sugo cache verify`, rebuild |
| Corrupted model | Checksum on load | Re-download or offline bundle |
| Failed upgrade | Pre-migration backup | `sugo data restore` |
| Disk full | Preflight check | Clean stop, clear message |
| Worker crash | Process isolation | Automatic restart |
| Lost/broken machine | Optional automatic backups | Install + `sugo data restore backup.sgb` |
| Ransomware | Off-machine backup copy | Restore from external copy |

Optional **automatic backups** of precious data only (a few MB), optionally passphrase-encrypted, to a user-chosen location, keeping N copies; 3-2-1 rule recommended. **A lost passphrase means unrecoverable backups** — stated clearly.

Project continuity: 2FA/passkey with offline recovery codes; mirror on Codeberg or GitLab; PyPI Trusted Publishing; Sigstore keyless signing; decisions recorded in-repo; lockfile for reproducible rebuilds.

---

## 21. Web sources and document registry — proposed (ADR-016)

Local SQLite registry with stable document identity and versions; HTTP conditional requests; change detection on the **cleaned** text hash; content-addressed chunk ids; diff output (added/changed/removed chunks); chunk dating. Sources: URLs, sitemaps, feeds, archived copies of dead pages. Legacy web handling: encoding detection, tolerant HTML parsing, layout-table vs data-table classification, frames, hidden text removal; optional headless browser pack. Respect `robots.txt`, rate limits, private-address blocking. Scope: single URLs, sitemaps and lists, not a full crawler. Scheduling via systemd timers / Task Scheduler / launchd (`sugo sync`).

---

## 22. Platforms and distribution (ADR-009, ADR-033)

| Support | Systems |
|---|---|
| Full | Linux x86_64 (Ubuntu LTS and derivatives incl. Linux Mint), Windows 10/11 x64, macOS Apple Silicon |
| Good | Other distributions, Linux ARM64, Intel Macs |
| Limited | Windows on ARM (x64 emulation; no native PyMuPDF wheels) |
| Unsupported | 32-bit systems, Windows 7/8 |

GPU: NVIDIA CUDA (Linux/Windows; PyTorch 2.15 + CUDA 13.2 still supports Turing, the oldest architecture in CUDA 13); Apple Silicon via MLX/Metal (model support to verify); AMD via ROCm on Linux; AMD/Intel on Windows via a non-PyTorch path to evaluate (ONNX Runtime, llama.cpp with Vulkan).

Distribution priority: PyPI (`uv tool`/`pipx`) and Docker images (GHCR, per level, amd64/arm64) → AUR, AppImage, Flatpak → Windows installer, winget → Homebrew. Model offline bundles attached to releases. Signed installers when the project has users.

---

## 23. Repository layout (ADR-032)

```
sugo/
├── src/sugo/
│   ├── api/                 public API (the only stable surface)
│   ├── core/                IR models, pipeline, engine, scheduler, budget, constants
│   ├── sources/  containers/
│   ├── extractors/          pymupdf, image/, docling, vlm
│   ├── analyzers/  cleaners/  detectors/  languages/
│   ├── serializers/  chunkers/  exporters/  optimizers/
│   ├── metrics/  models/  storage/  security/
│   ├── config/  setup/  i18n/
│   ├── ports/               cli/, shell/, mcp/, web/, service/
│   ├── data/                profiles, recipes, providers, cards
│   └── _internal/           private helpers; net/ is the only gateway to the internet (ADR-036)
├── packs/                   official packs, separate distributions (uv workspace)
│   ├── sugo-pack-anonymize/
│   ├── sugo-pack-italy/
│   ├── sugo-pack-web/
│   └── …
├── tests/                   unit, property, contract, golden, integration, security, dr, install
├── benchmarks/              scripts and historical results (corpus downloaded separately)
├── schemas/                 published JSON Schemas
├── docs/                    architecture, ADRs, user guides (en + it)
├── docker/
├── .github/                 workflows, templates, CODEOWNERS
└── pyproject.toml, uv.lock, governance files
```

Official packs are separate distributions so they **dogfood the extension API**. Outside the main repo: the test corpus (with per-file licences) and the community extension catalog (data only).

---

## 24. CI and release (ADR-033)

| When | What |
|---|---|
| Every push (Linux) | ruff, mypy, import-linter, Bandit, Semgrep, licence check, pip-audit, unit/property/contract/security tests, golden subset, coverage gate |
| Every PR | + Windows and macOS tests, reduced benchmark with regression gates |
| Nightly | Full profile matrix, full-corpus benchmarks, install-size measurement, DR tests, docs build |
| Weekly | Mutation testing; dependency update PRs (Renovate, 14-day minimum release age) |

Release: tag → build → reproducibility check → SBOM (CycloneDX, **including models**) → Sigstore attestations → manual approval → PyPI Trusted Publishing → signed Docker images → GitHub release (changelog, SBOM, checksums, GPU benchmark report from the reference machine, offline bundles) → mirror.

Workflow hardening: actions pinned by SHA, least-privilege tokens, no secrets for fork PRs, protected publishing environment.

Versioning: SemVer; 0.x may change contracts with notice; 1.0 when contracts are stable; trunk-based development; changelog from Conventional Commits; only the latest minor is supported. Documentation site: MkDocs Material (en + it), versioned, API reference from docstrings, on GitHub Pages.

---

## 25. Open items to verify during implementation

| Item | Status |
|---|---|
| PP-OCRv6 availability in RapidOCR packages (else convert to ONNX) | Verified: `rapidocr` 3.10.0 bundles PP-OCRv6 *small* (ADR-039) |
| Deskew and perspective correction of document photos | Deferred: separate pull request after the layout module (2c) |
| PyMuPDF 2.x adoption: 1.28.2 used while step 5a is written; move to 2.0 (or 2.0.x with MuPDF ≥ 1.28.6) after 2026-11-02, check its new dependencies and that its layout module never downloads models (ADR-043) | **Blocks merging step 5a** |
| OCR speed on the reference machine: dense phone screenshot ~7.4 s warm with the bundled small models vs < 2 s target; tiny models ~2.1 s but no Japanese (`benchmarks/ocr_speed.py`, ADR-039) | Decision pending |
| PaddleOCR-VL on macOS | To verify |
| Exact options to redirect Docling, RapidOCR and Hugging Face caches | To verify |
| llama.cpp + Vulkan backend for AMD/Intel GPUs on Windows | To evaluate |
| Landlock feature availability per kernel version | To verify |
| Licences of web content extraction and word-frequency libraries | To verify |
| Command name `sugo` free in Debian/Ubuntu repositories, GitHub, trademarks | To verify (free on PyPI as of 2026-10-27) |
| Offline language detector choice | Benchmark |
