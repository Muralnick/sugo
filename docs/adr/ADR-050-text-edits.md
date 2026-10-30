# ADR-050: Text edits, text normalisation and tracking URLs

**Status:** Accepted  
**Date:** 2026-10-30  
**Deciders:** project author  
**Extends:** ADR-041 (cleaner decisions)  
**Implements:** ADR-025 (language packs, v0.1 subset), ARCHITECTURE §4 and §14 (`strip_tracking_urls`), ROADMAP v0.1 cleaners "text normalisation, URL stripping"

## Context

The v0.1 cleaners still missing are text normalisation and URL stripping. They do not remove blocks: they change part of a block's text, for example joining "infor-" and "mation" or deleting `?utm_source=newsletter`. ADR-041 allows removals only and says that a decision cannot carry new text. A cleaner that could replace text freely would break principle 4: it could invent content, or change "not liable" into "liable". This ADR adds the smallest form of edit the core can check by itself.

## Decision

### Edit decisions (maintainer decision)

`sugo.core.decisions.EditDecision` proposes to replace `text[start:end]` of one block, with a kind and a reason. The core accepts only three kinds and checks each one mechanically, on the text itself:

| Kind | What the core checks | Example |
|---|---|---|
| `delete` | The replacement is empty | `?utm_source=n` → nothing |
| `normalize` | (1) The span and its replacement have the same visible characters: equal after removing whitespace and invisible characters (zero-width space, word joiner, BOM, soft hyphen), expanding the seven typographic ligatures and composing to NFC. (2) Spacing only shrinks: the replacement has no more whitespace characters and no more line breaks than the span, and no whitespace other than space and line feed. (3) Around the edit, words are unchanged, except that two words may join after an apostrophe or a hyphen | `ﬁ` → `fi`, no-break space → space, `a   b` → `a b`, `e` + combining acute → `é`, `dell' albero` → `dell'albero` |
| `hyphen_join` | The span is exactly a hyphen (`-`, U+2010, U+2011 or soft hyphen, possibly after extra soft hyphens) followed by a line break and optional spaces or tabs, with a letter (or a combining mark) on both sides; the replacement is empty | `infor-⏎mation` → `information` |

So a normalisation can never add, remove or change a letter, digit or sign, never opens a paragraph, indents a line into a code block, splits a word or merges two words ("now here" → "nowhere" is refused). Only `delete` and `hyphen_join` remove visible characters, always with a recorded reason. The rule on words compares the 64 characters on each side of the edit (skipped when no space is removed, or spaces only become fewer spaces), so checking stays linear on long blocks.

A cleaner may propose at most 2 000 edits per block and 10 000 per page (`MAX_EDITS_PER_BLOCK`, `MAX_EDITS_PER_PAGE`). Past that the core refuses the whole set, and the text cleaners themselves leave such a block as it is (ADR-025: when in doubt, leave it). A hostile document full of spaces, ligatures or tracking parameters therefore cannot make cleaning take minutes per page or fill memory with edit records (security review). The line-break hyphen pattern starts only at the beginning of a run of soft hyphens and never backtracks, so a long run costs linear time. Full NFKC is deliberately **not** an equivalence: it would accept `m²` → `m2` and `½` → `1⁄2`.

Edits follow the rules of ADR-041. A cleaner's decisions for a page are checked as a whole, and if one is invalid none is applied. A span must be non-empty (an empty span would be an insertion) and inside the text, and edits must not overlap. A block that is removed cannot be edited; the same cleaner cannot both remove and edit a block, nor edit a block it already edited (its edits are undone as one batch). Error messages name the problem and the kind, never the text (principle 11).

The core records every edit on the block as a `TextEdit` (`start`, `end`, `original`, `replacement`, `kind`, `edited_by`, `reason`; offsets index the text before that cleaner's edits). The cleaner's name comes from the caller, as for removals. `Block.original_text()` undoes all edits, so the extracted text can always be inspected (principle 3). A property test checks this for any accepted edits, and another checks that normalisation never changes what a reader sees. Both are invariant tests.

The definitions the cleaner and the core must share (what a letter is, invisible characters, the line-break hyphen pattern, apostrophes, the visible form of a text) live in one module, `sugo.core.text`, so they cannot drift apart.

Like removals, edits stay internal until the extension API exists (they are not in `sugo.api`). Table cells are not edited in v0.1.

### Text normalisation cleaner (maintainer decision: conservative, no dependencies)

`TextNormalizationCleaner` runs after the four removal cleaners. It touches only prose: headings, paragraphs, list items, chat messages, captions and footnotes. Code, tables and formulas are left alone, because their spacing can matter. It applies these rules:

- **Universal rules:** expand ligatures; turn no-break, fixed-width and narrow spaces into a space; collapse runs of spaces and drop trailing spaces (never leading indentation, which the serializer interprets); drop invisible characters (zero-width *joiners* stay, because emoji need them); compose accents stored as two characters.
- **Line-break hyphens**, decided by a new **lexicon analyzer** (pass 2, ADR-006). A hyphen is joined only if the document writes the joined word elsewhere. It is kept as a compound ("well-known") if the document writes the hyphenated form, with any of the three hyphens. Words are compared composed (NFC) and case-folded, and a compound also vouches for its parts ("information-theoretic" for "information"). Otherwise it is left (ADR-025: when in doubt, leave it). A soft hyphen always joins. The lexicon keeps 8-byte hashes of words, never text. It is capped at 200 000 words, so a hostile document cannot grow memory without bound. Its digest is part of the cache key of cleaned pages.
- **Language packs** (`sugo.languages`): Italian, Spanish, French, German and English. In v0.1 only Italian and French add a rule: the stray space after an elision (`dell' albero` → `dell'albero`, `l' arbre` → `l'arbre`), for a fixed list of elided words, unless the word follows an opening quote ("the 'all' keyword", "rock 'n' roll" keep their spaces). Rules that would change letters are left out because no edit may change a letter: `e'` → `è`, a lost `¿`, pre-1996 German hyphenation. The languages come from the configuration (default `en` until ADR-051). v0.1 has **no language detector and no frequency lists**, so ADR-025's per-block detection and frequency lists are postponed and add no dependencies.

### Tracking URL cleaner (maintainer decision: tracking parameters only)

`TrackingUrlCleaner` deletes query parameters on a fixed list (`utm_*`, `fbclid`, `gclid`, `msclkid`, `mc_eid` and others in `TRACKING_PARAMETERS`) from `http`/`https` URLs in prose. The address, the fragment and every other parameter stay, so the link still works. Consecutive trackers are deleted as one span with their separators. It is on by default (`strip_tracking_urls`, ARCHITECTURE §14) and can be turned off.

### Pipeline

`convert` and `convert_file` take `languages` and `strip_tracking_urls`. Both are part of the config hash and of the cleaned-page cache key. An unknown language is refused with `ValueError` before any work. `Conversion.edited` counts edits per cleaner, next to `Conversion.removed` for blocks. The CLI's `--json` does not show it yet: adding it is a contract change, left for `explain` and the preview after v0.1.

If the core refuses a cleaner's proposals for a page, the pipeline logs a warning naming only the cleaner and keeps the page without that cleaner's changes. A refused proposal is a bug in the cleaner; it must not make the document fail.

## Measurements

On o200k_base tokens:

| Text | Before → after |
|---|---|
| English text with ligatures, no-break spaces and double spaces | 43 → 30 (−30%) |
| Sentence with a newsletter link (`utm_*` and `fbclid`) | 47 → 22 (−53%) |
| Italian contract text with elisions, no-break spaces and a hyphenated word | 40 → 31 (−22%) |

The last two are regression tests that fail below −15% and −40%. Corpus numbers come with step 8.

## Alternatives considered

| Alternative | Why not |
|---|---|
| Normalisation hard-coded in the core | Extensions could never add rules without another design change |
| Free-text replacements, trusted because cleaners are ours | The core could not keep principle 4 once third-party cleaners exist |
| Full NFKC as the equivalence | Changes meaning: `m²` → `m2`, `½` → `1⁄2` |
| Join every line-break hyphen | Breaks true compounds ("well-known", "Jean-Paul") |
| Language detector and frequency lists now | Two dependencies to vet; the maintainer chose speed for v0.1 |
| Remove whole long URLs | Loses information the reader may need |

## Consequences

- The IR gains `Block.edits`, `TextEdit` and `EditKind`. Cached pages from earlier versions are not reused, because Sugo's version is part of every cache key.
- Chunk ids change for edited text, as for any change of content (ADR-047).
- Hyphens stay in documents that never repeat the joined word. This is a deliberate loss of a few tokens to avoid wrong joins.
- Before third-party cleaners exist, the extension API must decide how edits from several cleaners are ordered, and whether cleaners may edit table cells.
