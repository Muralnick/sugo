# ADR-004: OCR engine: RapidOCR with PaddleOCR models

**Status:** Accepted  
**Date:** 2026-10-27  
**Deciders:** project author

## Context

Screenshots are central. OCR must be local, fast on CPU, pip-installable, and cover eight languages in three script families. PyMuPDF reports 85.2% overall accuracy on ExtractBench with RapidOCR vs 78.3% with Tesseract. PP-OCRv6 (PaddleOCR 3.7.0, June 2026) covers Chinese, English, Japanese and 46 Latin-script languages with one model in three sizes (1.5M, 7.7M, 34.5M parameters).

## Decision

RapidOCR (ONNX Runtime) as default engine with PP-OCRv6 plus a dedicated Korean model. Detection runs once; recognition uses the script-appropriate model. Model size depends on level.

## Alternatives considered

| Alternative | Why not |
|---|---|
| Tesseract | Less accurate on screenshots; needs a system binary |
| EasyOCR | PyTorch-based, slow on CPU |
| Native PaddleOCR | Heavier Paddle framework |

## Consequences

- Easy installation for non-technical users.
- PP-OCRv6 availability in RapidOCR to verify; otherwise the project converts models to ONNX.
- Apache-2.0 models.
