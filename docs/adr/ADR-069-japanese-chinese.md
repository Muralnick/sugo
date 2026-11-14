# ADR-069: Japanese and Chinese

**Status:** Accepted (maintainer decisions of 2026-11-14: Japanese and Chinese first, Korean waits for v0.3; the OCR model is chosen from the configured languages; ADR approved the same day)
**Date:** 2026-11-14
**Deciders:** project author
**Implements:** ROADMAP v0.2.x "Japanese, Chinese and Korean" (Japanese and Chinese only), ADR-025 for `ja` and `zh`, ARCHITECTURE §"Language packs" rows Japanese and Chinese
**Builds on:** ADR-004 (OCR engine), ADR-039 (lite image stack), ADR-050 (text edits), ADR-051 (configured languages)
**Amends:** ADR-050 (two new checked edits), ROADMAP (Korean moves to v0.3)
**Adds dependencies:** none

## Context

ARCHITECTURE lists eight languages; v0.1 shipped the five Latin-script ones. The ROADMAP puts Japanese, Chinese and Korean in v0.2.x "as an optional extra for their OCR models".

Facts checked on 2026-11-14, on the reference machine, with Sugo 0.2.1:

- **OCR already reads Japanese and Chinese.** The PP-OCRv6 small recognition model bundled in the `rapidocr` wheel covers Chinese, Japanese and English (ADR-004, ADR-039). Two synthetic screenshots (three lines each, Yu Gothic and Microsoft YaHei, 30 px) came out exactly, including mixed simplified and traditional characters. No new model is needed for these two languages.
- **Korean needs a second recognition model** (`korean_PP-OCRv5_rec_mobile`, about 13 MB, Apache-2.0; there is no PP-OCRv6 Korean model). Sugo has no safe way to fetch a model before ADR-013 is implemented in v0.3.
- **Native PDFs keep the PDF's line breaks inside words.** Japanese and Chinese are written without spaces, so a line can end in the middle of a word: a generated PDF came out as `全\n角`, `英数\n字`. Each break costs a token and splits a word for search and embeddings. Two synthetic PDFs (PyMuPDF's built-in `japan` and `china-s` fonts, three paragraphs each):

| Text (o200k_base) | Now | Line breaks removed | Also full-width letters and digits made ASCII |
|---|---|---|---|
| Japanese | 134 | 126 (−6.0%) | 117 (−12.7%) |
| Chinese | 118 | 111 (−5.9%) | 111 (−5.9%) |

- **Full-width Latin letters and digits cost more tokens:** `ＡＢＣ１２３` is 5 tokens, `ABC123` is 2. Full-width punctuation must stay: turning `，` into `,` made the Chinese text *more* expensive (114 tokens) and ARCHITECTURE says Chinese keeps its punctuation.
- ADR-050 would refuse both edits today. Removing a line break between two characters joins two "words" (it only allows a join after an apostrophe or a hyphen), and `Ａ` → `A` is not the same character after NFC.
- On Windows, `system_language()` turns "Chinese (Simplified)_China" into `ch`, so a Chinese system would not get `zh` by default.

## Decision

### 1. Two language packs, no new dependency

`ja` and `zh` join `sugo.languages.PACKS`, so `languages = ["ja"]` (config, `SUGO_LANGUAGES`, the API) is accepted. `system_language()` maps Windows' "Japanese" and "Chinese" names to `ja` and `zh`, and `zh_TW`, `zh_HK` stay `zh`: one pack covers simplified and traditional Chinese, and Sugo **never converts** between them (a test checks it). Languages are still chosen in the configuration, never guessed (ADR-051).

OCR does not change: same models, same engine name, same speed.

### 2. A new checked edit: `cjk_join`

`EditKind.CJK_JOIN` removes a line break, with any spaces or tabs around it, when the characters on both sides are CJK: Han ideographs, Hiragana, Katakana (including the prolonged sound mark), CJK punctuation (`。、「」『』（）` and the like) and full-width forms. The core checks it mechanically, like `hyphen_join`: the span is only whitespace containing exactly one line feed, the replacement is empty, and the character before and after the span belongs to those blocks. The definition of "CJK character" lives in `sugo.core.text`, shared by the cleaner and the core.

The text normalisation cleaner proposes it only when `ja` or `zh` is a configured language, only in prose blocks (as today), and never when a Latin letter or digit touches the break (`Python\nを` stays: when in doubt, leave it). A blank line (a paragraph break) is never touched. Headings rendered on one line are joined without a space between two CJK characters, the same rule in the serializer.

### 3. Width normalisation as an accepted `normalize`

The ADR-050 equivalence is extended by two exact mappings, and nothing else:

- full-width ASCII **letters and digits** (U+FF10–FF19, U+FF21–FF3A, U+FF41–FF5A) to ASCII;
- half-width Katakana (U+FF65–FF9F) to full-width Katakana, composing a following half-width sound mark (`ｶﾞ` → `ガ`).

Full-width punctuation, the full-width space U+3000 (used for indentation) and everything else stay. These are proposed only for `ja` and `zh`. Full NFKC stays refused, as in ADR-050.

### 4. Chunking

Chunks already break after `。！？`. They may also break after `、` and `，` before falling back to cutting inside a run, so a long sentence is cut at a pause rather than in the middle of a word.

### 5. Tests and corpus

- Unit and property tests for both edits, including the invariant tests of ADR-050 (the original text is always recoverable; no visible character changes except the two width mappings).
- Fixtures are generated in the tests from PyMuPDF's built-in CJK fonts, and screenshots are rendered from those PDFs, so CI needs no font files.
- A small real corpus outside the repository (TESTING.md): Japanese laws from e-Gov and Chinese laws from the National People's Congress site, both outside copyright as official legislative texts (Japan Copyright Act art. 13, PRC Copyright Law art. 5), with a manifest and checksums. Token savings and content loss are measured there before release.
- The character-count thresholds (`LAYOUT_SIZE_MIN_CHARS` 25, `SUBSTANTIVE_MIN_CHARS` 40) were tuned on Latin text, where a character says less. They are measured on the CJK corpus and changed only if they measurably misbehave.

### 6. Not in this ADR

- **Korean**, moved to v0.3 with the safe model download (maintainer decision). Recorded now for that ADR: when `ko` is a configured language, lines are recognised with the Korean model (it also reads Latin letters and digits); otherwise with the bundled one. Detection still runs once. Hangul written as separate jamo is already composed by the universal NFC rule.
- **Furigana** (small reading aids above kanji, which OCR reads as an extra line). Removing them needs real scans to tune; it waits for a sample from the corpus and its own small amendment.
- Vertical Japanese text (out of scope for `lite`, FEATURES).

### 7. Release

Additive: two new accepted language codes and two new edit kinds, internal to the IR (edits are not in `sugo.api`). Output changes only for users who configure `ja` or `zh`. It ships as 0.2.2. The receipt and JSONL schemas do not change.

## Alternatives considered

| Alternative | Why not |
|---|---|
| Ship the Korean model now in a separate PyPI package (`sugo-cli[korean]`) | Maintainer decision: wait for the safe model download of v0.3 rather than add a second way to deliver models |
| Remove every line break inside CJK prose, without a core check | A third-party cleaner could then join anything; principle 4 needs the core to check it |
| Remove line breaks for every language when both sides are CJK | A Latin document quoting a Chinese line list (addresses, poetry) would lose its breaks; tying it to the configured language keeps the default as today |
| Full NFKC for CJK | Changes punctuation and costs Chinese more tokens (measured), turns `㈱` into `(株)` |
| A language detector | Still not needed: the configuration says which languages apply (ADR-050, ADR-051) |

## Consequences

- The IR gains `EditKind.CJK_JOIN`; cached pages from earlier versions are not reused, because Sugo's version is part of every cache key.
- Users with Japanese or Chinese documents must set `languages` (or have a Japanese or Chinese system locale) to get the new rules.
- Korean is announced for v0.3, not v0.2.x; README and FEATURES say so.
