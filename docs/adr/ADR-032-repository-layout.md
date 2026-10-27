# ADR-032: Monorepo with packs as separate distributions

**Status:** Accepted  
**Date:** 2026-10-27  
**Deciders:** project author

## Context

Official functional packs must stay optional, and the extension API must be exercised daily.

## Decision

Single repository using a uv workspace: core `sugo` plus official packs under `packs/` as separate distributions released together; extras pull them in. Test corpus and community catalog in separate repositories.

## Alternatives considered

| Alternative | Why not |
|---|---|
| Everything in one distribution | Optional features not truly optional; extension API untested |
| Many repositories | Release coordination overhead for one maintainer |

## Consequences

- `sugo[legal]` installs `sugo-pack-anonymize` and related packs transparently.
