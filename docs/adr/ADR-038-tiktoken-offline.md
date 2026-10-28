# ADR-038: tiktoken with a bundled, hash-verified vocabulary

**Status:** Accepted  
**Date:** 2026-10-28  
**Deciders:** project author  
**Implements:** ADR-003 (token metrics)  
**Amends:** licence allow-list in `CODE_STYLE.md` (one exception, below)

## Context

ADR-003 counts text tokens with `tiktoken` and the `o200k_base` encoding. On first use, `tiktoken.get_encoding()` downloads the vocabulary from `openaipublic.blob.core.windows.net` and caches it in a temporary directory. That would be outbound internet access outside the gateway, breaking principle 1 and ADR-036, and the metrics would fail offline.

## Decision

- Add `tiktoken` (MIT) as a runtime dependency, pinned to `>=0.14.0,<0.15` so upgrades are deliberate.
- Ship `o200k_base.tiktoken` (3.6 MB, MIT, from tiktoken) in `sugo/data/tokenizers/` with its licence and provenance. It was downloaded once at development time and checked against the SHA-256 pinned in tiktoken's own source.
- `sugo.metrics.tokenizer` reads the file from package data, **verifies the SHA-256 before parsing**, and builds the `Encoding` itself. `get_encoding()` and tiktoken's loader are never called, so nothing is downloaded and nothing is written to disk.
- Document text is counted with `encode_ordinary`: markers such as `<|endoftext|>` inside a document are plain text, never control tokens.

### Transitive dependencies

| Package | Licence | Note |
|---|---|---|
| `regex` | Apache-2.0 AND CNRI-Python | The CNRI-Python part covers code inherited from CPython's `re` module (CPython 2.6 and 3.1); it is the same licence history as Python itself. **Exception approved by the maintainer on 2026-10-28**, limited to `regex`. |
| `requests`, `urllib3`, `idna`, `certifi`, `charset-normalizer` | Apache-2.0, MIT, BSD-3-Clause, MPL-2.0, MIT | Installed because tiktoken can download vocabularies, but imported by tiktoken only for `http(s)://` paths, which Sugo never passes. import-linter still forbids Sugo from importing them (ADR-036). |

### Enforcement

| Guarantee | Test |
|---|---|
| No network and no tiktoken loader during load and counting | `test_loading_and_counting_never_touch_the_network` (invariant, sockets and loader blocked) |
| An altered vocabulary is refused | `test_tampered_bundled_file_is_refused`, `test_parse_rejects_altered_vocabulary` |
| Our encoding equals tiktoken's definition | `test_encoding_matches_tiktoken_definition` (pattern, special tokens, multilingual samples) |

## Alternatives considered

| Alternative | Why not |
|---|---|
| Let tiktoken download and cache the file | Network access outside the gateway; fails offline |
| Download through the gateway as a model (ADR-013) | Metrics would not work until the model module exists, and a first run would need the internet |
| `TIKTOKEN_CACHE_DIR` pointing at package data | Relies on tiktoken's cache-key scheme; a missing or renamed file silently falls back to a download |
| Another tokenizer (e.g. Hugging Face `tokenizers`) | Larger dependency; o200k_base is the reference chosen in ADR-003 |

## Consequences

- The wheel grows by about 3.6 MB.
- Upgrading tiktoken requires re-checking the pinned hash and the copied pattern; the cross-check test fails if they drift.
- Network-capable libraries are present in the environment; the boundary is enforced by import-linter and by the invariant test, not by their absence.
