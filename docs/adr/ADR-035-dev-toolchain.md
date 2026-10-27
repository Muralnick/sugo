# ADR-035: Development toolchain and build backend

**Status:** Accepted  
**Date:** 2026-10-27  
**Deciders:** project author

## Context

Step 0 of the roadmap needs a build backend and the development tools that enforce ADR-029 and ADR-030. Every dependency, including development-only ones, needs a recorded decision, an allowed licence and a release at least 14 days old.

## Decision

| Tool | Role | Licence | First pinned version |
|---|---|---|---|
| `uv_build` | Build backend (src layout, no plugins) | MIT / Apache-2.0 | 0.13.0 |
| `ruff` | Linting and formatting | MIT | 0.17.0 |
| `mypy` | Static type checking | MIT | 2.4.0 |
| `import-linter` | Architectural boundaries | BSD-2-Clause | 2.15 |
| `pytest` | Test runner | MIT | 9.1.1 |

- Development tools live in the `dev` dependency group (PEP 735), never in the runtime dependencies of `sugo`.
- `[tool.uv] exclude-newer = "14 days"` makes the resolver ignore any artifact uploaded in the last 14 days, so the minimum-age rule is enforced by the tool, not by memory.
- `uv.lock` pins exact versions with hashes; CI installs with `uv sync --locked`.
- CI uses a pinned uv version, and GitHub Actions are pinned by commit SHA (ADR-033).

Deferred to later steps, each with its own entry here when added: Hypothesis, pytest-cov and the coverage gate, Bandit, Semgrep, pip-audit, the licence check.

## Alternatives considered

| Alternative | Why not |
|---|---|
| hatchling | Extra tool with plugins we do not need; `uv_build` matches the uv workspace |
| setuptools | Heavier, legacy configuration surface |
| Black + flake8 + isort | Three tools instead of one (ruff) |
| pyright | Node.js dependency; mypy is the reference checker named in ADR-029 |

## Consequences

- `uv_build` supports pure-Python packages only; a native extension would need a new ADR.
- Upgrading a tool is a lockfile change reviewed like code.
