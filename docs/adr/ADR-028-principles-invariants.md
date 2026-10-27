# ADR-028: Immutable principles, invariant tests and proposal-based extensions

**Status:** Accepted  
**Date:** 2026-10-27  
**Deciders:** project author

## Context

Users and reviewers will read the code line by line and need to know what is guaranteed. In open source nothing is technically immutable.

## Decision

`PRINCIPLES.md` lists twelve promises of the official project, each enforced by invariant tests; changing one requires an ADR, public discussion and a major version. Extensions **propose** decisions; the core validates and applies them, so buggy extensions cannot break principles 3–5. Security limits have hard bounds. Forks breaking the principles must not use the name.

## Alternatives considered

| Alternative | Why not |
|---|---|
| Rely on documentation only | Unverifiable promises |

## Consequences

- In-process Python cannot be fully sandboxed: malicious extensions are handled by trust tiers and process isolation.
