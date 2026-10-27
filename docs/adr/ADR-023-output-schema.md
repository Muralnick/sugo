# ADR-023: Versioned output schema and content-addressed chunk ids

**Status:** Accepted  
**Date:** 2026-10-27  
**Deciders:** project author

## Context

RAG maintainers will build pipelines on Sugo's output; breaking them destroys trust.

## Decision

JSONL chunk schema v1 with `schema_version`, content-addressed `id`, `document_id`, tokens, heading path, pages, container-aware source, language, dates, version and config hash. Optional Markdown front matter. SemVer rules: additions minor, renames/removals major with deprecation. JSON Schemas published and tested. Extension API versioned separately.

## Alternatives considered

| Alternative | Why not |
|---|---|
| Unversioned output | Silent breakage downstream |

## Consequences

- Vector databases re-embed only changed chunks.
