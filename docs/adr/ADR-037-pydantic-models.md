# ADR-037: pydantic for the IR and typed data models

**Status:** Accepted  
**Date:** 2026-10-28  
**Deciders:** project author

## Context

Roadmap step 1 needs the intermediate representation (ADR-005) as typed models whose invariants are checked on every construction: normalised bounding boxes, soft deletion with `removed_by` and `reason` (principle 3), illegible blocks without guessed text (principle 4). The same models are serialised into the SQLite page store (ADR-006) and must reload identically (principle 6). The design already names pydantic for configuration (ADR-011) and operation contracts (ADR-022), and JSON Schemas must be published for the output (ADR-023).

## Decision

Use **pydantic v2** (MIT; its runtime dependencies `pydantic-core`, `annotated-types`, `typing-inspection` and `typing-extensions` are MIT or PSF-2.0) as the first runtime dependency of `sugo`, pinned in `uv.lock` with hashes.

- IR models are **frozen**, reject unknown fields and use **strict** validation: an extractor bug that passes the wrong type fails loudly instead of being coerced.
- A change to a block is a new validated copy (`Block.mark_removed`), so invariants cannot be bypassed.
- The `pydantic.mypy` plugin, shipped with pydantic, type-checks model constructors.

## Alternatives considered

| Alternative | Why not |
|---|---|
| Standard-library dataclasses | No validation or JSON Schema generation; hand-written checks would duplicate what pydantic will provide anyway for configuration and operations |
| attrs + cattrs | Two dependencies instead of one, and pydantic is still needed for ADR-011 and ADR-022 |
| msgspec | Faster, but a smaller ecosystem and no FastAPI or MCP schema integration (ADR-015) |

## Consequences

- Validation costs CPU on every construction; to be measured against the `lite` performance targets (docs/TESTING.md) once extractors exist.
- A pydantic major upgrade is a reviewed lockfile change; the `<3` upper bound prevents an accidental one.
