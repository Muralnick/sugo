# ADR-013: Model management and offline mode

**Status:** Accepted  
**Date:** 2026-10-27  
**Deciders:** project author

## Context

Models range from tens of MB to several GB, come from external sources, and some pickle-based PyTorch formats execute code on load. Companies use air-gapped machines.

## Decision

Registry with pinned revisions and SHA-256; consented, resumable, atomic downloads; Hugging Face with ModelScope fallback; single cache; offline bundles. Safe formats only (ONNX, safetensors, GGUF); no free `trust_remote_code`. MCP never triggers downloads. Application-level offline mode, with documented OS-level methods for certifiable guarantees.

## Alternatives considered

| Alternative | Why not |
|---|---|
| Silent automatic downloads | Unacceptable for bandwidth and transparency |
| Promising total offline at application level | Not provable for native library code |

## Consequences

- New model versions become default only after benchmark gates.
