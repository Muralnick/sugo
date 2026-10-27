# ADR-029: Code standards enforced by tooling

**Status:** Accepted  
**Date:** 2026-10-27  
**Deciders:** project author  
**Amended by:** ADR-036 (network access boundaries)

## Context

AI-written code must be reviewable and safe; written rules without enforcement erode.

## Decision

ruff, strict mypy on core/api/security, import-linter boundaries (core ↛ ports; network only in sources; packs use only `sugo.api`), Bandit and Semgrep, banned constructs (`eval`, `exec`, `pickle`, `shell=True`, stdlib XML), constants module, licence allow-list, ≥ 90% core coverage, Conventional Commits, signed commits, AI disclosure.

## Alternatives considered

| Alternative | Why not |
|---|---|
| Style guide without tooling | Inconsistent and unenforced |

## Consequences

- Some rules (comment quality, module headers) remain review-based.
