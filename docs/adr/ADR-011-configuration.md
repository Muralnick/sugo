# ADR-011: Layered TOML configuration with policies

**Status:** Accepted  
**Date:** 2026-10-27  
**Deciders:** project author

## Context

Different users configure in different places; companies must enforce settings.

## Decision

Layers: defaults < system < user < project (`sugo.toml` or `[tool.sugo]`) < environment < options. TOML, pydantic validation, XDG paths via `platformdirs`. Lockable keys at system level. Security limits with hard bounds. Recipes and user aliases on top.

## Alternatives considered

| Alternative | Why not |
|---|---|
| YAML | Extra dependency, type ambiguities |
| Single config file | Insufficient for projects and policies |

## Consequences

- Every output records the hash of the effective configuration.
