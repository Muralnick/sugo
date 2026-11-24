# ADR-073: The PDF engine stays PyMuPDF, with conditions for moving to PDFium

**Status:** Accepted (maintainer decision 2026-11-24)
**Date:** 2026-11-24
**Deciders:** project author
**Closes:** the "PDF engine decision" item of the roadmap (v0.1.x, carried to v0.3.x)
**Builds on:** ADR-001 (per-page routing), ADR-010 (licences), ADR-031 (hardening), ADR-035 (dependency rules), ADR-043 (PDF extractor in an isolated worker), ADR-071 (`normal` level with Docling), ADR-074 (community polls)

## Context

The `lite` level reads PDFs with MuPDF through PyMuPDF, in an isolated worker (ADR-043). MuPDF is AGPL-3.0, and in 2026 fuzzing found many memory-safety bugs in it (ADR-043, Context). After v0.1 the roadmap asked for an evaluation of PDFium, the PDF engine of Chromium, through its Python binding `pypdfium2`, on real files.

### The test (2026-11-13)

73 real PDFs (2,680 pages: downloads, office documents, EUR-Lex), `pypdfium2` 5.14.0 installed in a temporary folder, no dependency added to Sugo.

| Aspect | PyMuPDF (today) | PDFium (`pypdfium2`) |
|---|---|---|
| Pages found | Same count in every file | Same count in every file |
| Text | Clean: `get_text("dict")` gives words and lines already built | Identical in about half of the files. In some large files, words placed one by one come out glued together (no space between them), titles with spaced letters break apart, and an end-of-line hyphen stays as the control character `\x02`. Sugo would need its own builder of words and lines from character positions |
| Scanned pages | 8 files without text: both engines see the same empty pages; OCR is the same afterwards | Same |
| Hidden text (ADR-043) | The signals Sugo uses work (render mode, opacity, clipping, size, position) | Reports "clip" on all 190,714 text objects, so that signal is unusable as it is; the other signals are rare (1 object in render mode 3, 20 with low opacity in 4 files). Detection would need new work and new tests |
| Speed | Baseline | Equal on small files; **2 to 5 times slower** on large ones (230–270 pages), mostly for the second page render without text |
| Memory | Process peak up to about 286 MB | Process peak up to about 124 MB (rough measure, includes imports) |
| Files refused | 6 files wrongly refused: a Sugo bug (gaps in the object numbering), fixed in v0.1.5 (#101); one empty file refused correctly | Opened all of them; the empty file refused correctly |
| Tables | Sugo does not use PyMuPDF's `find_tables()` | Not compared |

### Other facts

- **Licence.** PyMuPDF is AGPL-3.0 (Artifex sells a commercial licence). PDFium is BSD-3-Clause; `pypdfium2` declares BSD-3-Clause and Apache-2.0, plus the licences of what it bundles. While Sugo is AGPL, PyMuPDF's licence costs nothing. A closed or permissive Sugo would need Artifex's commercial licence or another engine. The maintainer's direction on 2026-11-24 is to stay AGPL.
- **Security record.** MuPDF had many memory-safety fixes in 2026 (ADR-043). PDFium runs in every Chrome browser and is fuzzed continuously by Google, so it is probably the more robust parser, but this ADR has not counted and compared the advisories of the two engines.
- **Where the binaries come from.** `pypdfium2` ships PDFium binaries built, with some patches of its own, by a separate one-maintainer project (`pdfium-binaries`), not by Google. That project publishes GitHub build provenance attestations, so the binaries can be checked against its source; Sugo has not checked them yet.
- **PDFium is already in Sugo's lock.** Docling, at the `normal` level (ADR-071), depends on `pypdfium2` (5.14.0 in `uv.lock`), installed only with the optional `normal` extra. Moving `lite` to PDFium would add no package to the lock, but would add `pypdfium2` to installs that use `lite` only. The provenance question already applies to `normal` today.
- **Isolation.** Whatever the engine, it runs in an isolated worker with memory and time limits (ADR-043). This limits the damage of a parser bug; it does not remove it.

## Decision

**PyMuPDF stays the PDF engine of the `lite` level.** It gives cleaner text, is 2 to 5 times faster on large files, is already integrated, and Sugo's hidden-text protections are built and tested on it. Moving would mean writing a word and line builder and redoing hidden-text detection, with worse results today.

### Conditions for moving to PDFium

The question is reopened, with a new ADR, when **any one** of these happens:

1. **PDFium proves better on measurement.** A new test on the real-PDF corpus, with a word and line builder written for PDFium, shows all of:
   - text at least as good as PyMuPDF's: no glued words, no broken titles, no `\x02` hyphens, on the same files;
   - hidden-text detection at least as good, on the existing tests of ADR-043;
   - speed within 1.5 times PyMuPDF's on large files, and memory within the 2.5 GB budget;
   - a better security record: fewer advisories reachable by opening a file, or faster fixes, over the last 24 months, counted from public advisories;
   - verified provenance of the PDFium binaries that `pypdfium2` ships.
2. **Users decide it.** A community poll under ADR-074 approves the move: it opens when 10 users support the proposal, and passes with two thirds of 20 to 99 votes, or a simple majority of 100 votes or more. A company or funder that needs PDFium to use or support Sugo is a reason for the maintainer to open the poll early.
3. **PyMuPDF gets worse.** Any one of:
   - a vulnerability that Sugo reaches by opening a file stays without a fixed PyMuPDF release for more than 30 days after it is public;
   - no PyMuPDF release at all for 12 months (a project that has stopped, while MuPDF bugs keep being found);
   - Artifex changes PyMuPDF's licence or distribution in a way that conflicts with Sugo's licence or principles.
4. **Sugo's licence changes** to a permissive or dual licence that PyMuPDF's AGPL does not allow.

Whatever the reason, a poll included, two things are never traded away: the move happens only once hidden-text detection is at least as good as today's on the tests of ADR-043 (a protection against prompt injection, THREAT_MODEL.md B), and no text that PyMuPDF reads is lost.

The security record and binary provenance are checked again at each minor release of Sugo, together with the PyMuPDF advisories (ADR-043).

### How a move would happen

Not at once: PDFium first as a second engine for `lite`, chosen by a setting and measured on the corpus; it becomes the default only once condition 1 holds on that measurement. The setting, its name and its place in the configuration are a public contract and belong to that future ADR.

## Advantages and disadvantages

### Staying on PyMuPDF

| Advantages | Disadvantages |
|---|---|
| Cleaner text from real files, measured | AGPL: a closed or permissive Sugo would need a paid Artifex licence |
| 2–5 times faster on large files | Many memory-safety bugs fixed in MuPDF in 2026; fixes reach PyMuPDF with a delay |
| Already integrated and tested; hidden-text detection built on it | Higher memory peak (about 286 MB against 124 MB) |
| No work needed now | A large wheel (about 64 MB) with extra dependencies (ADR-043) |

### Moving to PDFium

| Advantages | Disadvantages |
|---|---|
| Permissive licence: keeps every licensing option open | Words and lines must be rebuilt from character positions: new code, new tests |
| Probably a more robust parser (Chromium's engine, continuous fuzzing), still to be confirmed | 2–5 times slower on large files today |
| Lower memory | Hidden-text detection must be redone: PDFium reports clipping on every text object |
| Already in `uv.lock` through Docling (installed today only with `normal`) | Binaries built and patched by a third party; provenance attestations exist but are not yet verified |
| Opened every file of the corpus | Text worse on several files of the corpus today |

## Alternatives considered

| Alternative | Why not |
|---|---|
| Move to PDFium now | Worse text and speed on real files today, and a rewrite of text building and hidden-text detection, for a security gain not yet measured |
| Use both engines on every file and compare | Twice the time and memory, and two parsers exposed to every untrusted file instead of one |
| Decide later without conditions | The question would come back with no rule for answering it; this ADR names the conditions |

## Consequences

- The roadmap's PDF engine item is closed; the README no longer lists it as open.
- PyMuPDF and MuPDF advisories are still checked at each release (ADR-043), and now also PDFium's, which `normal` already uses.
- Checking the provenance of the `pypdfium2` binaries becomes an open task for the `normal` level, whatever happens to `lite`.
- A user request for PDFium is answered by pointing to this ADR's conditions.
