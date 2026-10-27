# ADR-012: Extension system via entry points

**Status:** Accepted  
**Date:** 2026-10-27  
**Deciders:** project author

## Context

The community must add sources, extractors, cleaners, exporters, providers and languages without touching the core; the CLI must start fast.

## Decision

Entry-point families (`sugo.sources`, `sugo.containers`, `sugo.extractors`, `sugo.analyzers`, `sugo.cleaners`, `sugo.detectors`, `sugo.languages`, `sugo.serializers`, `sugo.chunkers`, `sugo.exporters`, `sugo.providers`, `sugo.media`). Built-ins and official packs use the same mechanism. Manifest with API version, card, requirements and declared permissions. Ordering from declared dependencies. Lazy loading. Data extensions vs code extensions. Trust tiers: Installable, Compatible (`sugo plugin check`), Verified.

## Alternatives considered

| Alternative | Why not |
|---|---|
| Script folder | No versioning or dependency management |
| Numeric priorities | Fragile with third-party extensions |

## Consequences

- Extensions run with user privileges; mitigations in ADR-028 and the threat model.
