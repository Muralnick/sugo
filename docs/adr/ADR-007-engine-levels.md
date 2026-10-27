# ADR-007: Three engine levels: lite, normal, quality

**Status:** Accepted  
**Date:** 2026-10-27  
**Deciders:** project author

## Context

Users range from 8 GB laptops without GPU to NVIDIA GPU machines. Features must be identical; engine power differs.

## Decision

**lite** (CPU, < 1 GB, PyMuPDF, small OCR, Office via lightweight dedicated libraries to avoid PyTorch), **normal** (CPU, ~2–3 GB, Docling layout and tables), **quality** (GPU recommended, VLM). Interfaces and cleaning identical across levels. The term *level* is distinct from *profile* and *recipe* (ADR-021).

## Alternatives considered

| Alternative | Why not |
|---|---|
| Single configuration | Too heavy or too weak |
| Different features per level | Fragmented experience |

## Consequences

- Modular installation (`sugo[lite]`, `sugo[normal]`, `sugo[quality]`).
- `lite` stays small because Docling pulls in PyTorch.
