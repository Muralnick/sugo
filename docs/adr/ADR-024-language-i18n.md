# ADR-024: English project, Italian priority, interface i18n

**Status:** Accepted  
**Date:** 2026-10-27  
**Deciders:** project author

## Context

International contributors expect English; the author is Italian and wants Italy to have first-class support.

## Decision

English for code, configuration, comments, commits and main documentation. Interface (CLI, UI, setup cards) in English plus **complete Italian from the first release**, via gettext; other languages from the community (e.g. Weblate). Machine-readable outputs and error codes never translated. User documentation in English and Italian. `sugo-pack-italy`: PEC, FatturaPA, Italian anonymization, Italian legal recipes.

## Alternatives considered

| Alternative | Why not |
|---|---|
| Italian-only project | Limits contributors and reach |

## Consequences

- Italian text costs more tokens than English with most tokenizers, so savings matter more for Italian users.
