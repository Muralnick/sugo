# ADR-022: Operation contracts, error model and CLI conventions

**Status:** Accepted  
**Date:** 2026-10-27  
**Deciders:** project author

## Context

Five ports must behave consistently; scripts and agents need stable signals.

## Decision

Operations defined once with pydantic models; MCP schemas and OpenAPI generated. Unified error model (stable code, translated message, hint, details). CLI: results on stdout, progress on stderr, TTY detection, `NO_COLOR`, `--json`; exit codes 0/1/2/3 partial/4 security/5 missing/130. MCP: token-budgeted responses with cursors, content labelled as data. Web UI: 127.0.0.1, random port, session token, Host/Origin checks, SSE progress. Internal JSON-RPC 2.0 with version handshake.

## Alternatives considered

| Alternative | Why not |
|---|---|
| Per-port ad-hoc interfaces | Inconsistency and duplicated documentation |

## Consequences

- Exit code 3 lets RAG pipelines distinguish partial success.
