# ADR-008: VLM choice for the quality level

**Status:** Accepted  
**Date:** 2026-10-27  
**Deciders:** project author

## Context

`quality` must handle books and hard documents in eight languages within 6 GB VRAM. Granite-Docling (258M) declares English with experimental Japanese, Arabic and Chinese, no Korean. PaddleOCR-VL-1.6 (0.9B) supports 111 languages including Korean. MinerU 4.0 is a full product (server, document library) under Apache-2.0 with additional conditions and telemetry to disable. HPD-Parsing requires a customised vLLM runtime.

## Decision

PaddleOCR-VL-1.6 as primary; Granite-Docling as a lighter option for Latin-script documents; MinerU as a benchmark reference; HPD-Parsing excluded. Pluggable VLM backend. Safeguards in ADR-026.

## Alternatives considered

| Alternative | Why not |
|---|---|
| Granite-Docling only | Insufficient Korean/CJK coverage |
| MinerU as dependency | Product-level licence and telemetry unsuited to a lightweight dependency |

## Consequences

- Final choice confirmed by benchmarks in all eight languages.
- Fast-moving field: re-evaluate periodically.
