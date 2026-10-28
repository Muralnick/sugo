# ADR-041: Minimal cleaner decisions, applied by the core

**Status:** Accepted  
**Date:** 2026-10-28  
**Deciders:** project author  
**Implements:** ADR-028 (proposal-based extensions), ARCHITECTURE §4 (cleaner contract)

## Context

Roadmap step 3 needs the first cleaner: removing the screenshot UI chrome typed by the detectors (ADR-040). ADR-028 requires cleaners to *propose* decisions that the core validates and applies, so that a buggy cleaner cannot break principles 3–5. The full decision format (edits, merges, flags, ordering between cleaners) belongs to the extension API, which does not exist yet; designing it now would freeze a public contract before it has been used.

## Decision

- **Minimal decision:** `sugo.core.decisions.Decision` says one thing only: remove block *X* for reason *Y*. It is an immutable, strictly validated pydantic model (ADR-037); an empty reason or any extra field is refused, so a decision cannot carry new text.
- **The core applies:** `apply_decisions(page, decisions, cleaner=name)` returns a new page where each named block is marked removed (soft deletion, principle 3). The core writes the cleaner's name into `removed_by` from its caller, never from the decisions. Until the extension API exists the caller is trusted code; then the core will take the name from the extension registry, so a cleaner cannot act under another one's name.
- **All or nothing:** the core checks a cleaner's decisions for a page as a whole. A decision naming a block that is not on the page, a block already removed, or the same block twice makes the whole set invalid: nothing is applied and `InvalidDecisionError` names the cleaner, so the caller can disable and report it (ARCHITECTURE §16). Error messages leave block ids out (principle 11).
- **Internal for now:** decisions are not exported in `sugo.api` and get no public error code. They become public, possibly extended, with the extension API; that change will need its own ADR.
- **First cleaner:** `sugo.cleaners.ui_chrome.UiChromeCleaner` proposes the removal of every `ui_chrome` block still present. Its `propose(page)` omits the `stats` argument of the documented contract until the analyzers exist (step 5).
- An import-linter contract keeps cleaners off extractors and ports: they see only the IR.

## Alternatives considered

| Alternative | Why not |
|---|---|
| Cleaners call `Block.mark_removed` and return the page | The cleaner, not the core, would decide what changes; violates ADR-028 |
| Full decision format now (edits, flags, merges) | A public contract with no user yet; likely wrong once real cleaners exist |
| Skip invalid decisions and apply the rest | A buggy cleaner would leave pages half-cleaned and go unnoticed |
| Ignore a second removal of an already removed block | Hides overlapping cleaners; per-cleaner metrics would depend on order without anyone knowing |

## Consequences

- Two cleaners that legitimately target the same block must skip removed blocks; the ordering rules of the extension API will make this explicit.
- On a synthetic phone chat screenshot (4 messages, status bar with clock, network and battery), removing UI chrome cuts the text from 35 to 26 o200k_base tokens (−26%). The measurement is `test_chat_screenshot_loses_only_the_status_bar`, which fails if the saving drops below 20%. Corpus numbers come with step 8.
