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
| `hypothesis` | Property-based tests (added in roadmap step 1) | MPL-2.0 | 6.169.1 |

- Development tools live in the `dev` dependency group (PEP 735), never in the runtime dependencies of `sugo`.
- `[tool.uv] exclude-newer = "14 days"` makes the resolver ignore any artifact uploaded in the last 14 days, so the minimum-age rule is enforced by the tool, not by memory.
- `uv.lock` pins exact versions with hashes; CI installs with `uv sync --locked`.
- CI uses a pinned uv version, and GitHub Actions are pinned by commit SHA (ADR-033).

Deferred to later steps, each with its own entry here when added: pytest-cov and the coverage gate, Bandit, Semgrep, pip-audit, the licence check.

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

## Amendment (2026-11-24): security fixes may skip the 14-day wait

The 14-day minimum age protects against malicious releases (a hijacked
maintainer account, a poisoned build), which are usually found and pulled
within days. Its cost is that a release fixing a known vulnerability also
waits 14 days, with the vulnerability open in Sugo. Before this amendment
the only exception was `sugo-cli` itself in the release pipeline
(ADR-033). Maintainer decision: a security fix may skip the wait, under
these conditions.

**When.** A published advisory (GitHub Security Advisory, OSV entry or
CVE) for a dependency, runtime or development, that affects Sugo: Sugo
reaches the vulnerable code, or that cannot be ruled out. For a low
severity the default is still to wait; the maintainer decides.

**Checks before adopting the version**, written in the pull request:

1. The advisory names the version as fixed, or the upstream project says
   so in its release notes.
2. The release comes from the project's usual source, checked against
   the index recorded for the package in `uv.lock`, not PyPI alone: the
   same project and publisher on that index (PyPI for most packages, the
   PyTorch index for `torch` and `torchvision` on Linux, ADR-071), a
   matching tag in the upstream repository, and its usual attestations or
   signatures if it publishes them.
3. The changes from the version in `uv.lock` are reviewed: they contain
   the fix and nothing unexpected (new install-time code, new network
   access, obfuscated or binary-only changes without source).
4. The licence is unchanged and still on the allow-list.

**Scope.** Only the named package, and only the checked release. The
exception is a timestamp just after that release's upload time, in
`pyproject.toml`:

```toml
[tool.uv]
exclude-newer = "14 days"
exclude-newer-package = { pymupdf = "2026-11-24T12:00:00Z" }
```

uv records it in `uv.lock` (`[options.exclude-newer-package]`), so the
exception is visible in review. The timestamp filters by upload time, not
by version number: it also admits any other release of that package
uploaded in the last 14 days (for example a newer major version uploaded
before a backported fix). The pull request therefore shows that `uv.lock`
resolves exactly the checked version; when it does not, the version is
pinned too (`constraint-dependencies = ["pymupdf==1.2.3"]` under
`[tool.uv]`), and the pin is removed with the timestamp. Newer releases of that package, and its
other dependencies, still wait 14 days; if the fix needs a new version of
another package, that package goes through the same checks. If a later
advisory hits the same package while the entry is still there, its fix is
a new exception: the same checks again on the new release, then the
timestamp moves forward to it, never to "any release". The entry is
removed once the last release it admits is 14 days old, at the latest
with the next dependency update.

**Record.** A `Security` entry in `CHANGELOG.md` with the advisory
identifier, and, if a Sugo release ships the fix, the emergency release
process of ADR-031. The pull request is approved by the maintainer like
any other.
