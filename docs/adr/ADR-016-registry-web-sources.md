# ADR-016: Document registry, versions and web sources

**Status:** Proposed  
**Date:** 2026-10-27  
**Deciders:** project author

## Context

Documents change over time; web pages, especially legacy ones, are noisy and use old encodings, malformed HTML and layout tables.

## Decision

Local SQLite registry with stable identity and versions; conditional HTTP requests; change detection on cleaned-text hash; content-addressed chunk ids; diff output; chunk dating. `sugo.sources` is the only network component, disabled offline. `robots.txt`, rate limits, private-address blocking. Scope limited to URLs, sitemaps and lists.

## Alternatives considered

| Alternative | Why not |
|---|---|
| Full reprocessing on every update | Wastes compute and embeddings |
| Built-in full crawler | A product of its own; better as an extension integrating existing tools |

## Consequences

- Incremental updates benefit local files too.
- Scheduling via systemd timers, Task Scheduler, launchd.
