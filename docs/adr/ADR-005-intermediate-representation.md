# ADR-005: IR with normalised coordinates and soft deletion

**Status:** Accepted  
**Date:** 2026-10-27  
**Deciders:** project author

## Context

Cleaners need position, style and repetition, which Markdown loses. Rules must work on phone screenshots, 4K monitors and A4 pages. Removals must be explainable.

## Decision

Cleaners operate on an IR of typed blocks with 0–1 normalised bboxes and `removed`, `removed_by`, `reason` fields. Markdown is produced only at the end.

## Alternatives considered

| Alternative | Why not |
|---|---|
| Clean Markdown directly | Loses position and style; unreliable header/footer detection |
| Hard deletion | No explanations, previews or per-cleaner metrics |

## Consequences

- Per-cleaner metrics for free.
- Enables preview and `/explain`.
- `time_range` reserved for audio and video.
