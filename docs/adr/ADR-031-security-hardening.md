# ADR-031: Security hardening highlights

**Status:** Accepted  
**Date:** 2026-10-27  
**Deciders:** project author

## Context

Sugo processes untrusted inputs and feeds LLMs and agents (see THREAT_MODEL.md).

## Decision

`defusedxml`; core dumps disabled in workers; invisible-text and deceptive-character removal; injection phrases flagged not removed; output-poisoning checks on substantive header/footer removals; Landlock sandbox on Linux enforcing extension permissions; 14-day dependency cooldown; low OS priority for background work; declared residual risks; rehearsed emergency release process.

## Alternatives considered

| Alternative | Why not |
|---|---|
| Rely on parser robustness | Native parsers have a history of vulnerabilities |

## Consequences

- Isolation is weaker on Windows and macOS, and this is documented.
