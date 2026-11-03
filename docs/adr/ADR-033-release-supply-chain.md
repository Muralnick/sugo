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
