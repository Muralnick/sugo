# ADR-025: Language packs for text recomposition

**Status:** Accepted  
**Date:** 2026-10-27  
**Deciders:** project author

## Context

Each language has its own recomposition traps (compound hyphens, elisions, CJK line joining, furigana, decomposed Hangul).

## Decision

A language pack per selected language, equal priority for all eight. Hyphen resolution: document lexicon first, then per-language frequency lists, otherwise leave unchanged. Unknown languages get only universal safe rules. Per-block script and language detection with a lightweight offline detector. New `sugo.languages` extension family with mandatory test cases.

## Alternatives considered

| Alternative | Why not |
|---|---|
| Italian-only rules | Wrong text in the other seven languages |

## Consequences

- Frequency-list libraries and detector to be chosen with licence checks.
