# ADR-075: Signed container images on GitHub Container Registry

**Status:** Accepted (maintainer decisions A to D, 2026-11-26)
**Date:** 2026-11-26
**Deciders:** project author
**Closes:** the "container image" item of the roadmap (v0.2.x, carried to v0.3.x)
**Builds on:** ADR-033 (distribution and supply chain), ADR-035 (dependency rules), ADR-036 (network boundaries), ADR-065 (container image for the MCP server)

## Context

ADR-065 added a `Dockerfile` that builds the MCP server from the checked-out source, and a CI job that builds it and asks it for its tools. Nothing is published: whoever wants the image builds it. ADR-033 plans signed images on GHCR, per level, for amd64 and arm64, and ADR-065 left that for a later ADR. The README has promised a published image since v0.2.

Facts checked on 2026-11-26:

- Every runtime package in `uv.lock` with native code (numpy, ONNX Runtime, OpenCV headless, Pillow, psutil, pyclipper, pydantic-core, PyMuPDF, PyYAML, regex, Shapely, tiktoken) has a manylinux aarch64 wheel for CPython 3.12 in the lock. An arm64 image needs no compiler and no change to the lock.
- Both base images in the `Dockerfile` are pinned by the digest of a multi-platform index that includes `linux/amd64` and `linux/arm64`, so the same `FROM` lines serve both architectures.
- GitHub offers native arm64 Linux runners (`ubuntu-24.04-arm`) to public repositories, so arm64 can be built and tested without emulation.
- The base image digests are refreshed by hand today (ADR-065, Consequences), so Debian security fixes reach the image only when someone remembers.

## Decision

### Maintainer decisions (2026-11-26)

- **A. Architectures:** `linux/amd64` and `linux/arm64`, one multi-platform image.
- **B. Levels:** `lite` only. `normal` (Docling, ADR-071) shipped in v0.3.0 for PDF pages but is not complete yet (Office files through Docling are still on the v0.3.x roadmap), and it would make the image several times larger; it gets its own image, tagged with a `-normal` suffix, in a later ADR.
- **C. Base image updates:** automatic pull requests, respecting the 14-day rule.
- **D. Inventory:** two SBOMs attached to the image (point 5, option 1).

### 1. Where and under which names

- `ghcr.io/muralnick/sugo` (GHCR requires lowercase), public.
- Each `sugo-cli` release `vX.Y.Z` publishes the tags `X.Y.Z`, `X.Y` and `latest`. Tags are a convenience; the documentation tells users to pin the digest (`ghcr.io/muralnick/sugo@sha256:…`), which is the only name that cannot move.
- A loader release (`langchain-sugo-v…`, `llama-index-readers-sugo-v…`) publishes no image.

### 2. The same Dockerfile, built natively per architecture

- The release image is built from the repository's `Dockerfile` (ADR-065, decision A) at the release tag's commit: the same source and the same `uv.lock` as the wheel published to PyPI.
- One job per architecture, each on a native runner (`ubuntu-24.04` and `ubuntu-24.04-arm`). No QEMU emulation.
- `SOURCE_DATE_EPOCH` is the commit's time, and BuildKit's `rewrite-timestamp` is on, so file and image timestamps do not depend on when the build ran.
- Each job runs the MCP probe of ADR-065 (`scripts/container/mcp_probe.py`, `--network none`) on the image it just built, on its own architecture, and fails the release if the probe fails. An image that was not probed is never pushed.
- Builds use the `docker` CLI and `buildx` already installed on GitHub's runners. No third-party Docker actions are added: the login reads the job's `GITHUB_TOKEN` from standard input.

### 3. Publishing behind the same approval as PyPI

- The push job runs only for `vX.Y.Z` tags, after both probes pass, in the `release` environment, so the maintainer's approval covers PyPI and the image together.
- Only the push job has `packages: write`; every other job keeps the read-only default. The token is the job's own `GITHUB_TOKEN`: no personal token, no stored secret.
- The job pushes each architecture's image by digest, then creates the multi-platform index and its three tags. It checks that each pushed image has the same config digest (image ID) as the image that passed the probe.
- `workflow_dispatch` dry runs build and probe the images but never push them, as for PyPI.

### 4. Signature and provenance

- `actions/attest-build-provenance`, the action the release already uses (ADR-033), signs a Sigstore provenance attestation for the image index digest, stored in GHCR next to the image (`push-to-registry`) and in the repository's attestations.
- Anyone can verify an image with `gh attestation verify oci://ghcr.io/muralnick/sugo:X.Y.Z --repo Muralnick/sugo`. The README gives this command next to the `docker run` command.

### 5. Inventory (SBOM): decision D

ADR-033 requires a CycloneDX SBOM that includes the models. The release already makes one for the wheel (Python packages, the two bundled OCR models, the tokenizer vocabulary). An image also contains Debian packages from the base image, and vulnerability reports for images are mostly about those.

- **(1, chosen)** Two inventories attached to the image: the release's existing CycloneDX SBOM (same `uv.lock`, models included), attested to the image digest with `actions/attest-sbom` (GitHub's own action); and the Debian and Python packages actually in the image, from BuildKit's built-in SBOM generator, its scanner image pinned by digest. Complete, no third-party action, two documents to explain.
- **(2)** Only the release's existing SBOM attested to the image. Simpler; the Debian layer is described only by the base image digest, so a user who wants the Debian package list must scan the image themselves.

### 6. Automatic base image updates

- A new `.github/dependabot.yml` with the `docker` ecosystem for the root `Dockerfile`, checked weekly, with `cooldown` of 14 days (ADR-035): Dependabot proposes a new tag and digest only once that release is 14 days old. A fix for a published vulnerability may skip the wait under the ADR-035 amendment (2026-11-24), by hand.
- `python` is limited to patch updates (`3.12.x`): moving to another Python version is a decision, not an update. The `uv` image is excluded: its version must match the one in CI and `pyproject.toml`, so it moves together with them, by hand.
- A Dependabot pull request goes through the normal checks, including the container job on both architectures (point 7), and the maintainer merges it. The published image changes only at the next release; a serious vulnerability in the base image is a reason for a patch release.
- Dependabot runs on GitHub with read access to the repository and opens pull requests; it gets no secret and cannot merge.

### 7. CI on both architectures

The `container` CI job of ADR-065 runs on `ubuntu-24.04` and `ubuntu-24.04-arm`, so an arm64 break shows up in the pull request that causes it, not at release time. It stays a non-required check, as decided in ADR-065, until it has run green on both for a few weeks.

### 8. One-time manual steps for the maintainer

- After the first push, in the package settings on GitHub: make the package public and link it to the repository (GHCR creates new packages private).
- Enable Dependabot version updates in the repository settings, if not already on.

### 9. Not done here

- Byte-for-byte comparison of two image builds, as the wheel has: the image's layers include files written by `uv sync` and Debian, and proving them identical needs more work. Timestamps are fixed (point 2); a reproducibility check is a later step.
- A vulnerability scanner in CI (such as Trivy or Grype).
- The image as an `oci` package in `server.json` for the MCP Registry: a change to a public file, for a later decision.
- Images for `normal` and `quality`, and Docker Hub or other registries.

## Alternatives considered

| Alternative | Why not |
|---|---|
| Build arm64 with QEMU on an amd64 runner | Several times slower, and the probe would run emulated; native runners are free for public repositories |
| `docker/login-action`, `docker/build-push-action` and the other Docker actions | Four more third-party actions with access to the push token, for steps the preinstalled CLI already does |
| A personal access token to push | A long-lived secret; the job's `GITHUB_TOKEN` expires with the job |
| Install the exact PyPI wheel in the image instead of building from source | Ties the image job to the PyPI upload and adds a second install path to the `Dockerfile`; both come from the same commit and lock, and the provenance names the commit |
| Renovate instead of Dependabot | A third-party app with write access to the repository; Dependabot is GitHub's own and needs nothing installed |
| Refresh base images by hand at each release (today) | Easy to forget; Debian fixes would wait for a release and for memory |
| Only a `latest` tag | Users could not stay on a version; a moving tag is the opposite of a verifiable release |

## Consequences

- People can run Sugo's MCP server on Linux, macOS (Intel and Apple Silicon, through Docker Desktop or Podman) and Windows with one command, without installing Python, and can verify where the image comes from.
- Every `sugo-cli` release also builds two images and probes them; the release takes a few minutes longer and pushes about 400 MB per architecture to GHCR.
- Base image updates arrive as reviewable pull requests; the release checklist no longer has a manual digest refresh.
- GitHub's arm64 runners are relatively new; if they become unavailable, arm64 falls back to QEMU emulation on amd64, at the cost of speed.
- Residual: Dependabot is documented to update an image pinned as `tag@sha256:…` when a newer tag appears; whether it also proposes a new digest when Debian rebuilds the same tag is to be confirmed in the first weeks. If it does not, a small scheduled check is added in a follow-up.

## Amendment (2026-11-26): implementation notes

- Each architecture's build writes an OCI archive (`--output type=oci`) holding the image and BuildKit's SBOM attestation. The probe runs that archive's image, copied into Docker with `skopeo`: `docker load` cannot read an archive with an attestation next to the image.
- `scripts/release/merge_oci_images.py` (standard library only) puts the two archives' images and attestations in one OCI index. It checks every blob's SHA-256 while copying, one Linux image per archive, no architecture twice, and that each attestation belongs to its archive's image. It runs in dry runs too, and again in the push job, which stops if the digest differs from the one checked earlier.
- The push job logs in with `docker login` (token on standard input) and pushes with `skopeo copy --all --preserve-digests`, so the registry serves the index digest that is attested. `skopeo` is preinstalled on both GitHub runners (1.13.3 on 2026-11-26), like `docker` and `buildx`: no tool is downloaded for this.
- The BuildKit image (`moby/buildkit`, v0.34.2) and the SBOM scanner (`docker/buildkit-syft-scanner`, 1.12.1) are pinned by digest in `release.yml`, at least 14 days old. Dependabot reads only the `Dockerfile`, so these two move by hand.
- The Dockerfile's `org.opencontainers.image.source` label names this repository, so GHCR links the package to it on the first push; making the package public stays a manual step (point 8).
