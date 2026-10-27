# ADR-019: Storage layout and two-level per-page cache

**Status:** Accepted  
**Date:** 2026-10-27  
**Deciders:** project author

## Context

Data must be separated by value; OCR is expensive while cleaning is cheap; legal users need control over stored text.

## Decision

XDG categories: config, regenerable cache, precious data, state, runtime. Two-level per-page cache (extraction; cleaning/output). Checkpoint = cache. SQLite plus content-addressed blobs; atomic writes; size limit with LRU; preflight disk check. Owner-only permissions, ephemeral mode, retention, optionally encrypted anonymization maps, hash-chained audit log; full-disk encryption recommended. Schema migrations with automatic backup; `sugo data export|restore`.

## Alternatives considered

| Alternative | Why not |
|---|---|
| Single document-level cache | Any setting change would redo OCR |
| App-level encryption of the whole cache | Key management complexity for less protection than disk encryption |

## Consequences

- New manual editions reprocess only changed pages.
