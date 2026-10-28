# ADR-040: Screenshot detectors and chat speaker side

**Status:** Accepted  
**Date:** 2026-10-28  
**Deciders:** project author  
**Amends:** ADR-005 (adds `speaker` to the IR block)

## Context

Roadmap step 3 types the content of screenshots: interface noise, chat bubbles and code. Two of these need information that only exists before lines are grouped into paragraphs: the position of each line (to rebuild code indentation) and of each status-bar item. The IR block had no field for who wrote a chat message.

## Decision

- **Where:** screenshot detectors live in the image extractor (`extractors/image/detectors.py`, as in ARCHITECTURE §5) and work on OCR line geometry during layout. They only *type* content; nothing is removed there. Removal of UI chrome is a cleaner's proposal, applied by the core (step 3b).
- **UI chrome:** only status-bar items (clock, battery percentage, network names) and lone icon misreads of at most two characters, and only inside the top and bottom bands of a screenshot (6% of the height each). Everything else stays content.
- **Chat:** a screenshot is a chat when at least three paragraphs are bubbles aligned to the left or right edge, with both sides present, making up at least 60% of its paragraphs. Aligned paragraphs become `chat_message` blocks.
- **Speaker:** new optional block field `speaker`, allowed only on `chat_message`, with the **neutral** values `left` and `right`. Which side is the phone's owner depends on the app, so Sugo records what it sees, not who it guesses.
- **Message timestamps are content** and stay with their message: they cost few tokens and can matter, for example as evidence. Only the status-bar clock is UI chrome. A future aggressive compression level may drop them.
- **Code:** a paragraph is code when at least two rows, and at least half of its rows, show code structure: keywords followed by code syntax, brackets, operators, assignments, calls. A keyword alone does not count, because legal lists end rows with `;` and English prose starts rows with `if`, `for`, `from` or `return`. Indentation dropped by OCR is rebuilt as spaces from each row's x position; only whitespace is added, derived from the image geometry.
- All thresholds are in `sugo/core/constants.py`, conservative, and to be calibrated on the corpus (step 8). When in doubt, the content stays text.

## Alternatives considered

| Alternative | Why not |
|---|---|
| Detectors on IR blocks after layout | Line positions are gone; code indentation cannot be rebuilt |
| `speaker` as `me` / `other` | Guesses the phone's owner from the app's convention; can be wrong |
| Removing message timestamps | Loses information that can matter, for a small token gain |
| One-row code detection | Headings like "for the following reasons:" or receipt lines like "Total = 1250 EUR" would become code |

## Consequences

- One-row code snippets stay plain text.
- Chats whose messages are all on one side (Slack-like) stay paragraphs.
- The output schema (ADR-023) will expose `speaker` when exporters arrive (step 6).
