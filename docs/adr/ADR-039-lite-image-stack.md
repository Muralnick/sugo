# ADR-039: Image stack for the lite level

**Status:** Accepted  
**Date:** 2026-10-28  
**Deciders:** project author  
**Implements:** ADR-004 (OCR engine), ADR-007 (engine levels)  
**Amends:** licence allow-list in `CODE_STYLE.md` (exceptions below)

## Context

Roadmap step 2 builds the `lite` image pipeline: safe decoding, classification, preprocessing, OCR and layout. ADR-004 chose RapidOCR with PP-OCRv6 and left open whether PP-OCRv6 is available in RapidOCR packages. Before deciding, a spike was run on the reference machine (4 cores, 8 GB, no GPU) with the network blocked.

## Findings

- `rapidocr` 3.10.0 ships PP-OCRv6 *small* detection and recognition models (ONNX, about 31 MB, Apache-2.0, Baidu/PaddleOCR weights) inside its wheel. With explicit model paths, it runs with no network access.
- Peak memory about 420 MB, within the `lite` budget (< 1 GB).
- RapidOCR's default detector setting (`limit_type: min`, 736 px) upscales small images and multiplies detection time; `max` with about 960 px avoids it.
- A dense phone screenshot (30 lines) takes about 7.7 s warm, against the < 2 s target in `docs/TESTING.md`. Recognition dominates. This gap is recorded, not hidden; the target is not changed without a new ADR.

## Decision

- The image stack is the optional extra **`sugo[lite]`** (ADR-007). The dev environment installs it so every test runs.
- Dependencies are added module by module, with this ADR as their record:

| Package | Added in | Role | Licence |
|---|---|---|---|
| `pillow` | Step 2a | Decoding, resizing | MIT-CMU |
| `numpy` | Step 2a | Pixel arrays | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 |
| `rapidocr` | Step 2b | OCR pipeline and bundled models | Apache-2.0 |
| `onnxruntime` | Step 2b | Model inference | MIT |

  Transitive dependencies of `rapidocr` (OpenCV headless, shapely, pyclipper, omegaconf, PyYAML, tqdm, colorlog, requests and others) are reviewed when step 2b adds it.
- **Licence exceptions approved by the maintainer on 2026-10-28:** MIT-CMU (Pillow), and Zlib, 0BSD and CC0-1.0 for the parts of numpy that use them. All are permissive.
- **Models:** the PP-OCRv6 *small* models bundled in the pinned `rapidocr` wheel are used directly. Sugo checks their SHA-256 on load and never lets RapidOCR download anything. Other sizes and the Korean model wait for the model module (ADR-013).
- **Decoding safety:** formats are detected from magic bytes; only PNG, JPEG and WEBP are accepted; file size and pixel count are capped before decoding (`sugo/core/constants.py`); Pillow's decompression-bomb warning is made fatal as a second guard.

## Alternatives considered

| Alternative | Why not |
|---|---|
| Tesseract | Lower screenshot accuracy and a system binary (ADR-004) |
| Downloading models on first use | Needs the model module and the network; bundled models work offline today |
| Pillow-SIMD or OpenCV for decoding | Pillow is already required and is the better-audited decoder surface |

## Consequences

- `sugo[lite]` weighs about 170 MB installed, most of it OpenCV and ONNX Runtime.
- Native decoders and ONNX Runtime remain the main attack surface (THREAT_MODEL.md); worker isolation and sandboxing come with ADR-018 and ADR-031.
- Deskew and perspective correction of document photos are not part of step 2a; they need geometry routines that arrive with OpenCV in step 2b.
