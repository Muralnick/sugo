# ADR-063: Handwriting in scanned pages (signatures)

**Status:** Accepted (maintainer decisions 1-3, 2026-11-07)
**Date:** 2026-11-07
**Deciders:** project author
**Applies:** PRINCIPLES 3 (no silent loss), 4 (no invented content) and 12 (stable contracts)
**Amends:** the Markdown output (ADR-042) and the receipt (ADR-056): one new block flag and one new marker
**Adds dependencies:** none

## Context

On 2026-11-07 the maintainer converted a real scanned PDF: a three-page meeting record signed by hand by three people, each signature under or across the typed name. At the `lite` level every word of a scanned page comes from the bundled OCR (ADR-039), and the signatures came out like this (names replaced):

| On the page | What Sugo wrote | Problem |
|---|---|---|
| Typed name A, crossed by A's signature | `Nàme Surnàme`-like text, with `ø`/`ó` where the ink crosses | The typed name is damaged |
| A's signature | `[illegible]` and a stray `e` | Almost right; the `e` is invented |
| B's signature, in blue ink | Two made-up words | **Invented text presented as real text** |
| Typed name C, and C's signature beside it | One line: made-up words, then the name with one letter missing | The scribble is read as words and merged with the name |

The third row breaks principle 4: unreadable areas must be marked, never filled. An LLM reading the Markdown would take the made-up words for a name.

### Why the current safeguard misses it

Sugo marks an OCR line illegible when its confidence is below `OCR_MIN_CONFIDENCE` (0.5). Measured on this page, with the bundled models at 200 dpi:

| Line | Confidence | Box height (share of page) |
|---|---|---|
| Typed name A, damaged | 0.95 | 0.018 |
| A's signature | 0.47 (illegible) | 0.019 |
| Stray `e` | 0.75 | 0.020 |
| Typed name B | 0.99 | 0.018 |
| B's signature (blue) | 0.70 | 0.038 |
| Typed name C, damaged | 0.94 | 0.022 |
| C's signature | 0.90 | 0.053 |

The signatures are read with 0.70 and 0.90 confidence, above some blocks of ordinary typed text elsewhere in the same document (0.66 to 0.70, from the receipt). No confidence threshold separates them. Two signals do: the signature lines are **two to three times taller** than the typed lines around them, and one is in **coloured ink** while the typed text is black or grey.

Sugo has no handling of handwriting today: no block type, flag or marker. ARCHITECTURE plans the `quality` level (VLM with OCR cross-check, v0.4) for the hardest pages, but a signed scan is a common, ordinary document (contracts, minutes, forms) that the `lite` level meets every day.

## Decision

### 1. Detect handwriting lines at the `lite` level, with no new dependency

After OCR and before layout, the image extractor marks an OCR line as **handwriting** when both hold:

- **Height:** its box is at least 1.6 times the median height of the page's lines (measured against the typed lines around them: about 2 and 2.8 for the two signatures read as words, at most 1.2 for typed lines; to be confirmed over whole pages in section 5); and
- **Not confident print:** its confidence is below 0.95, **or** the dark pixels in its box are mostly coloured (blue, violet, green ink) rather than neutral.

The thresholds are constants in `sugo.core.constants`, fixed by the measurement in section 5, not settings. Large typed headings are tall too, but are expected to be read with high confidence in neutral ink, so they stay text; section 5 must confirm it. The check reuses the pixels already in memory (numpy over the line box): no model, no download, no measurable cost.

A handwriting line is not read as text: it becomes its own block, so it is never merged into a typed line beside it (the fourth row above).

### 2. Mark it, never fill it: a new flag and a new marker

- The block gets a new flag `BlockFlag.HANDWRITING = "handwriting"`; its OCR text is kept in the IR and in the receipt, never in the Markdown.
- The Markdown serializer renders it as **`[handwriting]`**, escaped the same way as `[illegible]` (a literal `[handwriting]` in document text is escaped).
- The marker says what Sugo sees, not what it guesses: Sugo cannot tell a signature from a handwritten note, so it does not write `[signature]` (the same reason chat sides are `left`/`right`, ADR-040).
- Nothing is removed: the block stays, so principle 3 holds without a cleaner. `/explain`, the web UI and `sugo verify` list it among the flagged blocks with its reason.

### 3. Typed text damaged by ink: kept, flagged as uncertain

A typed line whose box overlaps a handwriting box keeps its OCR text (it is mostly right and is often the only copy of a name), and gets a new flag `BlockFlag.INK_OVERLAP = "ink_overlap"`. It is listed among the uncertain blocks in the receipt; the Markdown is unchanged. The `lite` level cannot repair the letters; the `quality` level's cross-check (v0.4) can.

### 4. Contract change

Two new `BlockFlag` values and one new Markdown marker change the output (principle 12). Under the 0.x rule in ARCHITECTURE they ship in a minor release with a CHANGELOG entry. Receipts that contain the new flags cannot be verified by an older Sugo, which rejects unknown flags; this is stated in the CHANGELOG. No CLI flag, exit code or error code changes.

### 5. Measure before merging

The implementation is accepted only with numbers:

- A small synthetic set in `benchmarks/`: typed pages rendered as scans, with signatures drawn as pen strokes in black and in blue, under, beside and across typed names; plus a scanned page with large headings and no handwriting.
- **No false positive** on the existing benchmark corpus and on the synthetic pages without handwriting: no typed line may become `[handwriting]`.
- On the synthetic signed pages, every signature becomes `[handwriting]` and no made-up words remain.
- The maintainer's real document is checked by hand; it is never added to the repository.

## Options considered

| Option | Why not chosen |
|---|---|
| Raise `OCR_MIN_CONFIDENCE` | The signatures are read with 0.70 and 0.90, above real typed lines: a higher threshold marks good text illegible and still misses C's signature |
| Write `[signature]` | Sugo cannot tell a signature from a note or an annotation; naming it would be a guess |
| Drop handwriting silently | Breaks principle 3, and a signature's presence is content in a contract or a record |
| Mark it `[illegible]` | Hides a useful fact (the page is signed) and mixes handwriting with damaged print |
| A handwriting-detection model | New model, download and memory budget for a problem two cheap signals already cover; reconsider with the `quality` level |
| Wait for the `quality` level (v0.4) | Signed scans are ordinary documents; the `lite` level should not invent names until then |

## Consequences

- Signed scans no longer produce made-up words; the Markdown shows `[handwriting]` where a person wrote by hand.
- Damaged typed names stay readable but are reported as uncertain.
- Two new flags and one marker in the output contract; old Sugo versions cannot verify receipts that contain them.
- Tall, low-confidence typed text (for example a large stamp read badly) may become `[handwriting]`: the benchmark in section 5 bounds it, and the OCR text stays in the receipt, so nothing is lost.

## Out of scope

The same document showed a second, separate problem: the letterhead at the top of each scanned page is read differently on every page (different OCR errors in the logo text), so the repeated-header cleaner (ADR-044) does not recognise it and saves nothing. Fuzzy matching of repeated OCR headers needs its own ADR.

## Maintainer decisions (2026-11-07)

1. The marker text is `[handwriting]`.
2. Typed lines damaged by ink (section 3) are flagged only in the receipt; the Markdown shows no marker for them.
3. Release: the output contract changes, so, as section 4 says, it ships in the next minor release (0.2.0), not in a 0.1.x patch release. 0.2.0 may be released before the rest of the ROADMAP v0.2 scope is ready.

## Implementation notes (2026-11-07)

Measured with `benchmarks/handwriting.py` (6 synthetic signed pages, 18 signatures, and a control page) and the maintainer's real signed scan (not in the repository).

- **Colour is not used.** On the real scan, a blue typed heading in the letterhead ("ACCREDITAMENTO …") would have become `[handwriting]` through the colour signal. Without colour, no false positive was found on the real scan or the control page, and no pixel work is needed.
- **The typical height is weighted by characters.** A plain median was set by the many short logo words of the real letterhead, which made body lines look 1.6 times taller than "typical". Weighted by characters, body lines set it.
- **Thresholds kept as proposed:** 1.6 times the typical height and confidence below 0.95. Typed lines read below 0.95 were at most 1.1 times taller; taller typed headings were read with at least 0.99.
- **Illegible lines stay `[illegible]`**, also when tall: on the real scan one such tall line was part of a logo, not ink.
- **The receipt lists the block, not its text.** `FlaggedBlock` has no text field, and adding one would change the receipt schema version; the OCR text stays in the IR (page cache) only. Section 2 said "in the IR and in the receipt"; the maintainer is asked to confirm.
- **Screenshots are not checked**: their tall, uncertain lines are emoji and interface glyphs.

### Gate result (section 5): not fully met

| Page | Signatures | `[handwriting]` | Made-up words left | Typed text lost |
|---|---|---|---|---|
| Under the names, black | 3 | 3 | none | none |
| Under the names, blue | 3 | 1 | `00000000` (confidence 0.98) | none |
| Beside, black / blue | 3 / 3 | 3 / 3 | none | none |
| Across, black / blue | 3 / 3 | 3 / 3 | none | none (the names under the ink were already unreadable before this change) |
| Control (no handwriting) | 0 | 0 | none | none |
| Real signed scan | 2 read as words | 2 | none | none; one damaged name flagged `ink_overlap` |

One synthetic signature in blue ink is read with 0.98 confidence and stays as made-up text; another becomes `[illegible]`, which invents nothing. Catching the first would need the colour signal back, with the false positive above. The maintainer decides whether to accept this limit.
