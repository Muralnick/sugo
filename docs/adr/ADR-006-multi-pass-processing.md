# ADR-006: Multi-pass processing with an SQLite page store

**Status:** Accepted (revised)  
**Date:** 2026-10-27  
**Deciders:** project author

## Context

Global cleaners need document-wide statistics, but an 8 GB machine cannot hold a book in memory alongside models. The original design used one JSON file per page; review showed weaker crash safety and heavy Windows antivirus overhead on thousands of small files.

## Decision

Four passes: extraction into an **SQLite** page store (compressed page records, transactional), analysis with lightweight statistics, page-by-page cleaning and rendering, chunking. The page store doubles as checkpoint and cache (ADR-019).

## Alternatives considered

| Alternative | Why not |
|---|---|
| All in memory | Does not scale with length |
| Sliding window | Incomplete statistics for recurring patterns |
| One file per page | Less crash-safe, slow on Windows |

## Consequences

- Memory independent of document length.
- Free resume after interruptions.
- Single writer guaranteed by the shared engine (ADR-018).
