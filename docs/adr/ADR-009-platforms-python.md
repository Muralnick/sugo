# ADR-009: Platforms and Python version

**Status:** Accepted  
**Date:** 2026-10-27  
**Deciders:** project author

## Context

The open-source and developer audience is strongly Linux-oriented; the author avoids virtual machines. Dependency ranges: PyMuPDF 2.0 Python 3.11–3.15; PyTorch 2.15 ≥ 3.11; PaddleOCR declares up to 3.12; MinerU < 3.15. PyTorch 2.15 with CUDA 13.2 still supports Turing GPUs (e.g. GTX 1660 Ti), the oldest architecture in CUDA 13.

## Decision

Priority Linux > Windows > macOS, one Linux-first codebase, no dedicated edition. Python 3.12. Development in GitHub Codespaces (Linux); cross-platform CI on GitHub Actions. A non-PyTorch path (ONNX Runtime; llama.cpp with Vulkan to evaluate) to survive future Turing deprecation and cover AMD/Intel GPUs.

## Alternatives considered

| Alternative | Why not |
|---|---|
| Dedicated Linux edition | Two codebases, divergent features |
| Windows-first | Against the main audience |

## Consequences

- Native Linux desktop integration (Wayland portals, StatusNotifierItem, systemd).
- `quality` tested on the author's GPU machine; Codespaces have no GPU.
