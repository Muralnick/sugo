# ADR-064: Repeated letterheads in scanned documents

**Status:** Accepted (maintainer decisions 1-3, 2026-11-07)
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

## Decision

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

## Maintainer decisions (2026-11-07)

1. Order: the layout fix (part 1) comes first, in its own pull request; the letterhead matching (part 2) follows.
2. `[illegible]` blocks inside a matched letterhead area stay on every page, as ADR-044 does for all flagged blocks.
3. Release: 0.2.0, with ADR-063.

## Implementation notes

### Part 1, layout (2026-11-07)

- Rows are compared one after the other inside an XY-cut leaf: a row whose median line height is at least 1.5 times the previous row's (or two thirds of it) starts a new paragraph (`LAYOUT_SIZE_SPLIT_RATIO`).
- **Rows with fewer than 25 readable characters are not measured** (`LAYOUT_SIZE_MIN_CHARS`). With every row measured, a short body line without descenders ("…stabiliti;") has a lower box, and it split a body paragraph in mid-sentence on the real scan.
- Screenshots are exempt: a chat message and its small timestamp stay one bubble.
- On the real scan, the only changes are the two intended ones: the letterhead now ends before the first body paragraph on pages 2 and 3; every other block is unchanged. The synthetic corpus (native PDFs, XLSX, screenshots) does not reach this code; the extractor tests and `benchmarks/handwriting.py` give the same results as before.
- The ADR's "or the gap between them is more than a share of the line height" was not needed on the real scan and is not implemented.

### Part 2, letterhead matching (2026-11-07)

Measured with `benchmarks/letterheads.py` (synthetic noisy scans, results in `benchmarks/results/`) and the maintainer's real scanned record (not in the repository). Changes from section 2, each forced by a measurement:

- **Containment against the whole band, not block against block.** A candidate block is a copy when at least half of its character trigrams are found anywhere in the top band of another page. The layout groups the captions differently on each page, so whole blocks rarely correspond; the band does.
- **Keyed trigram bitsets (4,096 bits) instead of MinHash signatures.** Containment needs the band's whole set, and a fixed-size bitset bounds memory per page; the trigrams are hashed with a key derived from the document's SHA-256. Only the decisions (page and block ids) leave the analyzer. Each page is compared with at most 5 pages before and after it, so the work grows linearly with the document.
- **Only text clearly smaller than the page's body text is a candidate** (at most 0.8 times the page's typical size). Without this rule, body-size articles that repeat in part from page to page were removed as whole blocks, losing the part that was new on each page. The OCR layout now records each block's median line height, in pixels, as `Style.font_size`; it is compared only within a page.
- **Top band only.** Matching the bottom band too removed formulaic footnotes in small print (different by a word or two on each page) and, once, a body-size closing line. The bottom keeps ADR-044's exact matching.
- **Tried and dropped:** keeping a block when one of its words is found on no other page. It cut the real record's saving from 14% to 4.4% (OCR-damaged words look new) and did not protect the case below.

Results:

| Document | Result |
|---|---|
| Real scanned record, 3 pages | 1,504 → 1,293 tokens (**14.0%** saved); 6 letterhead copies removed on pages 2 and 3; no body text removed |
| Synthetic letterhead, 3 and 6 pages, with and without footnotes | Letterhead tokens after page 1 removed (above the two-thirds gate); no body text or footnote removed |
| Synthetic controls without letterhead (repeating articles, footnotes) | Nothing removed |
| Synthetic control: a small running title that changes on every page ("…, section 3: notices") | **Known limit:** removed on 2 of 6 pages; the section name is in the receipt, not in the Markdown |

The known limit is for the maintainer to accept or not.
