# CLAUDE.md — instructions for AI coding agents

This file is read by Claude Code (and is mirrored in `AGENTS.md` for Codex and other agents). It tells you how to work on Sugo.

## Project in one paragraph

Sugo is a local, offline-first Python application that converts documents, screenshots and images into compact Markdown for RAG systems and LLMs, minimising tokens without losing content. The full architecture has already been designed: **do not redesign it, implement it.** If something in the design looks wrong or impossible, stop and explain the problem instead of silently deviating.

## Read before writing code

1. `PRINCIPLES.md` — invariants you must never violate.
2. `docs/ARCHITECTURE.md` — the system design.
3. `docs/ROADMAP.md` — what to build now (the first release scope).
4. The ADRs in `docs/adr/` relevant to the module you are working on.
5. `CODE_STYLE.md` — mandatory coding rules.

## How the maintainer works

- The maintainer directs the project and makes product and architecture decisions; you implement. The maintainer is not a professional programmer: **explain what each module does and why, in plain language, when you finish it.** The maintainer prefers explanations in Italian; code, comments, commits and docs stay in English.
- Work **one module at a time**, in the order of `docs/ROADMAP.md`. Do not scaffold future modules ahead of time.
- Each module is done only when it has tests, passes `ruff`, `mypy` and `import-linter`, and its token metrics are measured where relevant.
- Ask before: adding a dependency, changing a public contract (API, output schema, CLI flags, exit codes, error codes), or touching `PRINCIPLES.md`, `src/sugo/security/` or invariant tests. Each of these needs an ADR.

## Hard rules

- Python 3.12, managed with `uv`. Pinned dependencies with hashes in `uv.lock`.
- Never use `eval`, `exec`, `pickle`, `subprocess` with `shell=True`, or network access outside the boundaries of ADR-036: outbound internet only through `src/sugo/_internal/net/` (called only by `sources`, `models`, `setup`); local networking only in `ports` and `core/engine`.
- Never use `print`; use the structured logger or the ports.
- Never log document content or file names at default log level.
- Plugins and cleaners **propose** changes to the intermediate representation; only the core applies them. Removal = mark `removed` with `removed_by` and `reason`, never delete.
- Never fill unreadable content with guesses; mark it as illegible.
- Model files: only ONNX, safetensors or GGUF; pinned revisions; SHA-256 verified; no `trust_remote_code`.
- Parse XML only with `defusedxml`.
- New dependency versions must be at least 14 days old.
- Respect the memory budget: the reference machine has 8 GB RAM and 4 cores; Sugo's default budget is 2.5 GB.

## Terminology

| Term | Meaning |
|---|---|
| **Level** | Engine power: `lite`, `normal`, `quality` |
| **Profile** | Work profile: `personal`, `dev`, `rag`, `office`, `legal`, `research`, `full` |
| **Recipe** | How to treat a document type: `book`, `contract`, `chat-screenshot`, … |
| **Pack** | Optional functional distribution, e.g. `sugo-pack-anonymize` |
| **Port** | An interface over the core: Python API, CLI/shell, web UI, MCP server, background service |
| **IR** | Intermediate representation: Document → Page → Block |

## Commands (once scaffolded)

```bash
uv sync                      # install dev environment
uv run pytest                # tests
uv run ruff check . && uv run ruff format --check .
uv run mypy src/sugo/core
uv run lint-imports          # architectural boundaries
```

## Commit conventions

Conventional Commits (`feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `chore:`). Mention AI assistance with a `Co-authored-by` trailer, consistent with `AI_WORKFLOW.md`.

## Git workflow

`main` is protected: every change reaches it through a pull request whose CI check (`checks`) passes.

1. Never commit directly to `main`. Start each piece of work on a new branch from an up-to-date `main`, named `<type>/<short-description>` with a Conventional Commits type (e.g. `feat/ir-models`, `fix/ocr-timeout`, `docs/pr-workflow`).
2. Run the commands above locally before pushing.
3. Push the branch with `git push -u origin <branch>` and open the pull request with `gh pr create`. The description summarises the change, lists the checks run, follows the checklist in `CONTRIBUTING.md` and declares AI assistance.
4. The maintainer reviews and merges. Do not merge a pull request unless the maintainer asks you to.
