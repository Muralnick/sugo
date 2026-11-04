# ADR-033: Distribution, CI and release supply chain

**Status:** Accepted  
**Date:** 2026-10-27  
**Deciders:** project author

## Context

Users need trustworthy, verifiable releases; companies ask for inventories.

## Decision

Channels by priority: PyPI and Docker (GHCR) → AUR, AppImage, Flatpak → Windows installer, winget → Homebrew. CI tiers (push, PR, nightly, weekly). Release: reproducibility check, CycloneDX SBOM **including models**, Sigstore attestations, manual approval, PyPI Trusted Publishing, signed images, mirror. SemVer with 0.x phase; only latest minor supported. Hardened workflows (SHA-pinned actions, least privilege, no secrets for forks).

## Alternatives considered

| Alternative | Why not |
|---|---|
| Manual releases | Error-prone, unverifiable |

## Consequences

- GPU benchmark report attached manually from the reference machine.

## Amendment (2026-11-03)

`v0.1.0a1` is published to PyPI by hand, ahead of the automated pipeline
above, solely to claim the project's name before someone else does; the
`Private :: Do Not Upload` classifier that blocked this is removed for
that reason, not because the pipeline exists. The full pipeline (SBOM,
Sigstore attestations, PyPI Trusted Publishing) is still required before
the real `v0.1.0` release (roadmap step 9); this is the one exception
"Manual releases" above is rejected for.

## Amendment (2026-11-04): the first implementation, scoped to PyPI only

Roadmap step 9 implements the "Release" decision above, scoped to PyPI
only: Docker/GHCR and the other channels follow once this path is
proven, rather than building all of them at once.

- **SBOM:** `cyclonedx-bom` (a pinned dev dependency, `uv.lock`) generates
  a CycloneDX SBOM from the built distribution's dependency graph.
  `scripts/release/generate_sbom.py` then adds the two bundled OCR model
  files and the vendored tokenizer vocabulary as explicit components,
  reading their pinned SHA-256 from `sugo.core.constants` so the hash has
  one source of truth. `lite` is the only engine level in v0.1, and it
  downloads no models at install or run time (ADR-036); the day a level
  does, its downloader's manifest joins this script's inputs too.
- **Build provenance:** `actions/attest-build-provenance`, GitHub's own
  Sigstore-backed attestation action, signs the built sdist, wheel and
  SBOM — no separate Sigstore tooling needed.
- **Manual approval:** a GitHub Environment named `release`, with the
  maintainer as the required reviewer, gates the publish job.
- **Publish:** `pypa/gh-action-pypi-publish` over OIDC (PyPI Trusted
  Publishing). This requires the maintainer to configure the Trusted
  Publisher on pypi.org once, by hand; the workflow cannot do this part.
- **Reproducibility check:** the workflow builds the sdist and wheel
  twice, in two separate jobs, and fails the release if the two builds
  differ byte-for-byte.
- **Trigger:** pushing a `vX.Y.Z` tag (stable releases only — a
  pre-release tag such as `v0.1.0a1` is excluded, since that one is
  already published by hand per the amendment above).
- **Deferred:** Docker/GHCR images, AUR, Flatpak, Homebrew, and the
  mirror, until those channels are actually built.
- All third-party GitHub Actions are pinned by commit SHA, not by tag
  (ADR-033's "hardened workflows" decision), with the human-readable
  version in a trailing comment.
