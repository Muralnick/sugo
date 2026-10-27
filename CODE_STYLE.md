# Code style

Rules are enforced by tools wherever possible: a written rule that no tool checks is a wish, not a standard.

| Area | Rule | Enforced by |
|---|---|---|
| Language | English for code, identifiers, comments, commits, technical messages | Review |
| Formatting and linting | `ruff format`, `ruff check` (no style debates) | CI |
| Types | Type hints everywhere; strict `mypy` on `src/sugo/core`, `api`, `security` | CI |
| Module headers | Every module starts with a docstring stating its single responsibility | Review |
| Comments | Explain **why**, not what | Review |
| Constants | No magic numbers: thresholds and limits live in `sugo/core/constants.py`, each with the reason for its value | Review, ruff rule |
| Errors | No bare `except`, no swallowed exceptions; use the error model (`code`, `message`, `hint`, `details`) | ruff, review |
| Output | No `print`; structured logging or ports only | ruff (`T20`) |
| Forbidden | `eval`, `exec`, `pickle`, `marshal`, `subprocess(..., shell=True)`, `yaml.load` without safe loader, stdlib XML parsers | ruff, Bandit, Semgrep |
| Network | Outbound internet only through `sugo._internal.net`, called only by `sources`, `models` and `setup`; local networking only in `ports` and `core.engine` (ADR-036) | `import-linter`, ruff |
| Architecture | Core never imports ports; packs and plugins use only `sugo.api` | `import-linter` |
| Dependencies | Minimal, pinned with hashes, licence on the allow-list, at least 14 days old, justified in an ADR | CI licence check, Renovate config |
| Tests | Every change ships with tests; core coverage ≥ 90% | CI |
| Commits | Conventional Commits, signed | CI, branch protection |
| Public API | Only what `sugo` exports is public; everything else lives under `sugo._internal` or private modules | Review, contract tests |

## Licence allow-list

MIT, BSD-2-Clause, BSD-3-Clause, Apache-2.0, ISC, PSF-2.0, MPL-2.0, LGPL (dynamic use), AGPL-3.0, GPL-3.0-compatible. Anything else requires an ADR.
