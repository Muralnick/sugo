# ADR-003: Token metrics and per-provider image baseline

**Status:** Accepted  
**Date:** 2026-10-27  
**Deciders:** project author

## Context

Value must be proven with numbers. For images the user's real alternative is sending the image to a vision LLM, billed in image tokens; formulas differ per provider and change over time. The initially assumed Claude formula (area/750) was outdated: current documentation uses 28×28 patches, ⌈w/28⌉×⌈h/28⌉, with a standard tier (long edge 1568 px, max 1568 tokens) and a high-resolution tier (2576 px, max 4784 tokens). Gemini charges 258 tokens for images up to 384 px per side and 258 per 768×768 tile beyond.

## Decision

Two baselines: raw vs clean text (`tiktoken`, default `o200k_base`) and image cost vs extracted Markdown per provider. Formulas are **data files** with source, date and verification status. Percentages are the headline metric because tokenizers differ across LLMs.

## Alternatives considered

| Alternative | Why not |
|---|---|
| Text counts only | Ignores the main image use case |
| Formulas in code | Every provider change would require a release |

## Consequences

- Reports honestly show low or no savings (e.g. small screenshots to Gemini).
- OpenAI formula for recent models marked unverified.
- The same formulas drive the hybrid mode (ADR-017).
