# ADR-030: Testing and benchmark strategy

**Status:** Accepted  
**Date:** 2026-10-27  
**Deciders:** project author

## Context

Credibility depends on proven savings without content loss; AI-written code needs strong tests.

## Decision

Savings always paired with content preservation. Unit, property, invariant, contract, golden, integration, security, DR, install and language-pack tests; weekly mutation testing. Corpus: synthetic documents with exact ground truth, EUR-Lex, public-domain books, public benchmarks; stored outside the repo with licences. "Content lost" is the primary metric. Regression gates on content loss, savings, recognition errors, time and memory. GPU benchmarks on the reference machine before releases. Initial performance targets. Logs without content or file names; no telemetry.

## Alternatives considered

| Alternative | Why not |
|---|---|
| Savings-only metrics | Hides content loss |

## Consequences

- CI timing noise handled with medians and relative thresholds.
