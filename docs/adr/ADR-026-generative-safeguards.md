# ADR-026: Safeguards for generative models

**Status:** Accepted  
**Date:** 2026-10-27  
**Deciders:** project author

## Context

Only `quality` uses a generative model (VLM), which can hallucinate on blurry areas and could be influenced by text in images.

## Decision

OCR/VLM cross-check with agreement score and flags; unreadable areas marked `[illegible]`; VLM output treated as data; `origin_engine` recorded per block; in `legal`, VLM only with cross-check enabled.

## Alternatives considered

| Alternative | Why not |
|---|---|
| Trust VLM output | Invented text in contracts is unacceptable |

## Consequences

- Higher cost on `quality` pages due to double processing.
