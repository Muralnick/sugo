# ADR-064: Repeated letterheads in scanned documents

**Status:** Proposed
**Date:** 2026-11-07
**Deciders:** project author
**Amends:** ADR-044 (running headers and footers) for pages read with OCR; the image layout (roadmap step 2c)
**Applies:** PRINCIPLES 3 (no silent loss), 6 (reproducibility) and 11 (no document text in statistics)
**Adds dependencies:** none

## Context

On 2026-11-07 the maintainer converted a real scanned PDF, a three-page meeting record with the same letterhead (five institutional logos with their names) at the top of every page. Sugo saved 0% of its tokens: no header, footer or page number was removed. Measured on that document (names and logo texts not reproduced here):

- The letterhead costs about **23% of the output** (343 of 1,505 o200k_base tokens). Keeping its first copy and removing the other two would save about 15%.
- ADR-044 finds a running header by **exact** text after normalisation. Three things defeat it on scans:
  1. **OCR errors differ on every page.** The same logo name is read three different ways on three pages.
  2. **The layout groups the logo words differently on every page.** A logo caption is a block of its own on one page and merged with another logo's words on the next, so no block repeats as a whole, even with perfect OCR.
  3. **On two of the three pages, the letterhead and the first body paragraph end up in the same block.** The letterhead's small logo captions overlap the gap above the body, so the XY-cut finds no clean horizontal cut. Even a perfect matcher could not remove that block without removing body text.
- The letterhead also reaches below ADR-044's edge band (the top 10% of the page): its lowest lines end at about 15%.

Native PDFs are not affected: their running headers are exact copies, and ADR-044 handles them.

## Decision (proposed)

Two changes, each measured on its own, both for **pages read with OCR only** (`PageOrigin.OCR`). Native pages keep ADR-044 exactly as it is.

### 1. Layout: never merge text of very different sizes into one paragraph

In the image layout, a paragraph is split between two rows when the row height changes by more than a factor (proposed: 1.3), or the gap between them is more than a share of the line height that the XY-cut alone does not catch. Letterhead captions are set much smaller than body text, so they no longer merge into the body paragraph below them.

This is a general layout fix: it also helps scanned forms and pages with footnotes. It must not change the character error rate (CER) of the existing OCR tests and benchmarks.

### 2. Similar, not identical, repeated blocks in the top and bottom bands of OCR pages

For OCR pages, the edge analyzer also records, for each text block in the edge bands, a **similarity sketch** instead of an exact digest:

- **Band:** the top and bottom 20% of the page (10% for native pages, unchanged), since scanned letterheads are taller than running headers.
- **Sketch:** the block's normalised text (ADR-044 normalisation, digits masked) cut into character trigrams. Each trigram is hashed with a key derived from the document's SHA-256, and only a MinHash signature of 32 values is kept. Statistics still hold no document text (principle 11), they stay in memory for the job only, and the same document always gives the same sketch (principle 6).
- **Repeated:** a block matches a block on another page when their estimated similarity is at least a threshold (proposed: 0.5, to be measured). A block is a **letterhead block** when it matches blocks on at least 3 pages, covering at least 40% of the pages between the first and the last (ADR-044's rules, unchanged).
- **Removal:** a new cleaner proposal, under the existing `headers_footers` cleaner. **The first copy is always kept**, since a similar match is weaker evidence than an exact one. Later copies are removed, whole blocks only, with the reason `letterhead repeated on N pages (similar text read with OCR); first copy kept on page P`. A block that reaches outside the band is never removed.
- **Flagged blocks** (hidden, suspicious instruction, low agreement, handwriting) are never counted and never removed, as in ADR-044. `[illegible]` blocks inside a matched letterhead area are an open decision (below).

### 3. Measure before merging

- A synthetic benchmark in `benchmarks/`: three-to-ten-page scans with the same letterhead (logo shapes and small captions) and different body text, rendered with scanner-like noise so the OCR reads the letterhead differently on each page.
- Gate: on the synthetic scans, at least two thirds of the letterhead tokens after page 1 are removed and **no body text is lost**; on the existing corpus and the native PDFs, the output does not change; the OCR CER tests do not change.
- The maintainer's real document is checked by hand (target: about 15% saved) and never added to the repository.

## Options considered

| Option | Why not chosen |
|---|---|
| Looser exact matching (more normalisation) | OCR errors are different letters on each page; no normalisation makes them equal |
| Edit distance between whole blocks | Blocks are grouped differently on each page, so whole blocks rarely correspond |
| Compare the pixels of the top band across pages (image fingerprint) | Needs image data in the IR and a new kind of statistic; the band also holds the body's first lines on some pages, so it says *that* the band repeats, not *which* blocks to remove |
| Remove every block in a repeated band | Would remove body text that starts inside the band |
| Wait for the `quality` level (VLM, v0.4) | Scanned letterheads are common in ordinary documents (records, contracts, letters); the `lite` level should not pay 20% extra tokens until then |

## Consequences

- Scanned documents with a letterhead lose its later copies: on the real record, about 15% fewer tokens.
- Two new numbers (similarity threshold, OCR band size) and one new statistic, in memory only.
- Residual risk: a body block near the top of several pages that shares most of its trigrams with others (a repeated form title, a table header) may be removed after its first copy. The first copy always stays, every removal records its reason, and the benchmark bounds it.
- Native PDFs and screenshots are unchanged.

## Open decisions for the maintainer

1. The order: the layout fix (part 1) first in its own PR, then the letterhead matching (part 2). Proposed: yes, since part 1 is useful alone and part 2 depends on it.
2. `[illegible]` blocks inside a matched letterhead area (unreadable logo pieces): keep them on every page (as ADR-044 does for all flagged blocks), or remove the later copies with the letterhead. Proposed: keep them for now; they cost two tokens each.
3. Release: removing more page furniture changes what a cleaner removes, but no format, flag or error code. Proposed: the next release after ADR-063, 0.2.0.
