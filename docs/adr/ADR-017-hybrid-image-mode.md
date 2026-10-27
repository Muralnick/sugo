# ADR-017: Hybrid mode and provider-aware image optimization

**Status:** Accepted  
**Date:** 2026-10-27  
**Deciders:** project author

## Context

For small, sparse images some providers (e.g. Gemini) charge as much as or less than the extracted text.

## Decision

Per image: text only, optimised image (noise crop, resize to the target provider's tile or patch boundaries), or both, according to the configured provider. Module `optimizers/image_budget.py` reuses the metrics formulas.

## Alternatives considered

| Alternative | Why not |
|---|---|
| Always text | Sometimes costlier and loses visual information |

## Consequences

- Charts and diagrams stay images when cheaper.
- A distinctive feature for the README.
