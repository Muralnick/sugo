# ADR-002: Adaptive table serialization

**Status:** Accepted  
**Date:** 2026-10-27  
**Deciders:** project author

## Context

Markdown tables with alignment padding waste tokens; narrow-long or sparse tables have cheaper faithful representations.

## Decision

The serializer renders candidate formats (compact pipe table without padding, key-value, row sentences), measures them with the tokenizer and picks the cheapest one that preserves structure.

## Alternatives considered

| Alternative | Why not |
|---|---|
| Always standard Markdown tables | Simple but expensive |
| Always CSV | Cheap but loses multi-row headers and readability |

## Consequences

- Measurable savings on table-heavy documents.
- Consumers must handle several documented table representations.
