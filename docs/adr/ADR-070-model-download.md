# ADR-070: Safe model download, first version, and Korean

**Status:** Accepted (ADR approved 2026-11-14; maintainer decisions of 2026-11-14: a copy on GitHub with ModelScope as fallback; Python's standard library for HTTP; `pull`, `list`, `remove`, `bundle` and `install` in the first version; a missing model is an error with a hint)
**Date:** 2026-11-14
**Deciders:** project author
**Implements:** ADR-013 (first version), ARCHITECTURE §18 "Model management", ROADMAP v0.3 "the safe model download" and Korean (ADR-069 §6)
**Builds on:** ADR-004 (OCR engine), ADR-036 (network boundaries), ADR-039 (lite image stack), ADR-045 (private storage), ADR-048 (CLI), ADR-066 (uninstall), ADR-067 (Python API), ADR-069 (Japanese and Chinese)
**Amends:** ADR-066 (`sugo uninstall` also removes downloaded models)
**Adds dependencies:** none

## Context

Every model Sugo uses today is bundled in the `rapidocr` wheel. The next ones are not: the Korean recognition model now, Docling's layout and table models in v0.3, a vision model in v0.5. ADR-013 sets the rules (pinned revisions, SHA-256, consent, resumable and atomic downloads, safe formats only, MCP never downloads, offline bundles) and ADR-036 says outbound traffic goes only through the gateway `sugo._internal.net`, which exists but is empty.

Facts checked on 2026-11-14:

- The Korean model RapidOCR uses, `korean_PP-OCRv5_rec_mobile.onnx`, is 13 488 748 bytes, SHA-256 `cd6e2ea50f6943ca7271eb8c56a877a5a90720b7047fe9c41a2e541a25773c9b`, Apache-2.0. Its character list is inside the ONNX file, so it is one file.
- It is published as ONNX only on ModelScope (`RapidAI/RapidOCR`, tag `v3.10.0`), which redirects to a CDN in China with a link that expires. The official Hugging Face repository (`PaddlePaddle/korean_PP-OCRv5_mobile_rec`) has only the Paddle format, which Sugo does not accept (safe formats only).
- No HTTP client library is a Sugo dependency. Python's `urllib.request` covers HTTPS, redirects, proxies from the environment and `Range` requests.
- The `[privacy] offline` setting is in ARCHITECTURE §14 but not implemented.

## Decision

### 1. Registry in the code

`sugo.models.registry` lists every downloadable model as a frozen record: id (`ocr-korean`), task, languages, level, format, file name, size in bytes, SHA-256, licence and its notice, upstream revision, and an ordered list of sources. Only these models can be downloaded or installed, and only in ONNX, safetensors or GGUF. A new model or version is a code change, reviewed and released, never data fetched at run time.

`ocr-korean` has two sources, tried in order (maintainer decision): a copy attached to a GitHub release of this repository, tag `models-1`, then ModelScope at the pinned tag. Apache-2.0 allows the copy; the release also carries the licence and a notice naming PaddlePaddle and RapidAI. The SHA-256 is fixed in the code, so either source can only deliver the same file.

### 2. The gateway, with the standard library (maintainer decision)

`sugo._internal.net` gets one function, `download(url, destination, expected_size, expected_sha256, ...)`, and nothing else uses the network:

- **HTTPS only**, with the system's certificate store (`ssl.create_default_context`). No `http://`, also not after a redirect.
- **Allowed hosts**: each source names its host, and redirects may lead only to hosts on a fixed list (`github.com`, `objects.githubusercontent.com`, `release-assets.githubusercontent.com`, `www.modelscope.cn` and `*.modelscope.cn`). At most five redirects.
- **Public addresses only** (SSRF): before connecting directly, the host's addresses are resolved and refused if any is private, loopback, link-local, multicast or reserved. Through a proxy set by the standard environment variables (as companies need), the proxy decides.
- **Bounded**: more bytes than `expected_size` stop the download; timeouts on connect and read.
- **Offline mode**: with `[privacy] offline = true` (or `SUGO_OFFLINE=1`) the gateway refuses before any connection.
- **Logged** at info level: host, size, outcome. Never a file name or anything from the user's documents (principle 11).

### 3. Storing models

Models live in `<cache dir>/models/<id>/<sha256>.<ext>`, in the private cache folder of ADR-045.

- **Resumable**: the download writes `<sha256>.part` and, if it is there from an interrupted run, asks for the rest with a `Range` request; a server that ignores it restarts from zero.
- **Atomic**: the file gets its final name (`os.replace`) only after its size and SHA-256 match. A wrong file is deleted and the next source is tried.
- **Checked on every load**, as the bundled models are today (ADR-039): a file changed on disk is refused and the error says to download it again.
- Two Sugo processes pulling at once take a lock on the model's folder; the second waits for the first, then finds the model installed.

### 4. Commands (maintainer decision: also bundles in the first version)

| Command | What it does |
|---|---|
| `sugo models list` | Every model in the registry: installed or not, size, licence, languages. `--json` |
| `sugo models pull ocr-korean` | Shows size, source and licence, asks "Download? [y/N]", downloads, verifies. `--yes` for scripts; outside a terminal without `--yes`, nothing is downloaded and the exit code is 2, as for `sugo uninstall` (ADR-066) |
| `sugo models remove ocr-korean` | Deletes the model's files, with the safe-delete rules of ADR-066 §4 |
| `sugo models bundle ocr-korean -o korean.zip` | Writes an offline bundle: the installed model files and a manifest. No network |
| `sugo models install korean.zip` | Installs from a bundle, on a machine without internet. No network |

A **bundle** is a ZIP file holding `sugo-models.json` (format version, Sugo version, model ids) and the model files. `install` trusts nothing in it: it accepts only file names the registry knows, extracts each to a `.part` file with a size cap from the registry (no paths from the archive, so no zip slip, no bombs), checks the SHA-256 against the registry, then renames. A bundle with an unknown or altered file is refused whole.

`sugo doctor` lists installed models. The shell, the web UI and the MCP server never download (principle 10); they report the missing model (section 6). The Python API has no download function in this version.

### 5. Korean

- A language pack `ko` (ADR-025, ADR-069 §6): Korean puts spaces between words, so the universal rules apply and the CJK rules of ADR-069 do not. Hangul written as separate jamo is already composed by NFC.
- **OCR model by configured language** (maintainer decision of 2026-11-14, ADR-069 §6): when `ko` is a configured language, every text line is recognised with the Korean model, which also reads Latin letters and digits; otherwise with the bundled model. Detection still runs once, with the bundled detection model. A document that mixes Korean with Japanese or Chinese is read with the Korean model: a known limit.
- A Korean system locale selects `ko` by default, as for the other packs.

### 6. A missing model is an error (maintainer decision)

When `ko` is configured and an image or scanned page needs OCR, but `ocr-korean` is not installed, the conversion stops with:

```json
{ "code": "MODEL_MISSING",
  "message": "The OCR model for Korean is not installed.",
  "hint": "sugo models pull ocr-korean",
  "details": { "model": "ocr-korean", "size_mb": 13 } }
```

Exit code 5 (`MISSING`, already in ARCHITECTURE §12), the same code in the API (`SugoError`), MCP and the web UI. Native PDFs with a text layer and Office files need no OCR and convert as before. A corrupted model gets `MODEL_INVALID` (exit code 5), with the same hint.

### 7. Uninstall and cache (amends ADR-066)

`sugo uninstall` lists downloaded models with their size and deletes them, with the same safe-delete rules. `sugo cache clear` keeps them: it deletes document text, and models are not document text.

### 8. Supply chain

The release SBOM lists the registry's models as optional components with their hashes and licences, as it does for the bundled ones. The `models-1` GitHub release is made once by the maintainer with the file downloaded from ModelScope and checked against the pinned SHA-256; the checksum is in the release notes.

### 9. Order of work

1. The gateway, the registry, storage, `list`, `pull`, `remove`, offline mode.
2. `bundle` and `install`.
3. The `ko` pack, OCR routing, `MODEL_MISSING`, uninstall.

Each is its own pull request with tests; the network is never touched by the tests (a local HTTPS test server stands in, and the gateway's checks are tested directly). Release: 0.3.0, because it adds commands, a configuration setting and error codes.

## Alternatives considered

| Alternative | Why not |
|---|---|
| ModelScope only | One site, behind a CDN with expiring links: if it fails, no Korean (maintainer decision) |
| Convert the official Paddle model to ONNX ourselves | A conversion toolchain to trust and reproduce; RapidAI's ONNX file is already what RapidOCR tests |
| `httpx` | A dependency and its own dependencies to vet and update, for what the standard library does (maintainer decision) |
| Fall back to the bundled model with a warning | Korean read as garbage without the user noticing (maintainer decision) |
| A separate PyPI package with the model (`sugo-cli[korean]`) | A second way to deliver models; rejected in ADR-069 |
| Bundles later, with Docling | Companies with air-gapped machines would get Korean only with internet (maintainer decision) |

## Consequences

- `sugo.models` is a new package and the first caller of the gateway; ADR-036's import rules already allow it.
- New public contract: the `models` command group, `[privacy] offline` and `SUGO_OFFLINE`, error codes `MODEL_MISSING`, `MODEL_INVALID`, `DOWNLOAD_FAILED` and `OFFLINE`, the language code `ko`, the bundle format (versioned).
- Docling's models (v0.3) and the vision model (v0.5) reuse the registry, gateway and bundles; Hugging Face sources need only their hosts added to the list.
