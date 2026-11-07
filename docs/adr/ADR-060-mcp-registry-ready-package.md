# ADR-060: A package the official MCP Registry can run

**Status:** Accepted (maintainer decisions A, B and C, 2026-11-07)
**Date:** 2026-11-07
**Deciders:** project author
**Amends:** ADR-007 and ADR-039 (the `lite` level is no longer optional), ADR-033 (package metadata)
**Adds:** console script `sugo-cli`; `server.json` for the MCP Registry
**Adds dependencies:** none (the `lite` packages move from the extra to the base dependencies, same versions)

## Context

The official MCP Registry lists MCP servers so that agents such as Claude Code or Codex can add them without the user reading Sugo's README. For a Python package the registry publishes a `server.json` with `"registryType": "pypi"` and `"runtimeHint": "uvx"`; a client then runs `uvx <package> <arguments>`. Checked on 2026-11-07 against the registry's documentation (`docs/modelcontextprotocol-io/package-types.mdx`, `docs/reference/server-json/generic-server-json.md`, `quickstart.mdx`):

- `uvx sugo-cli` runs an executable named `sugo-cli`; Sugo's is named `sugo`, so it fails. The documented examples show no way to name another executable.
- The package `sugo-cli` alone cannot convert anything: PyMuPDF, ONNX Runtime, RapidOCR, Pillow and numpy come only with the `[lite]` extra, and `uvx sugo-cli` installs no extra. Every conversion would stop with `LEVEL_MISSING`.
- The registry checks ownership by looking for `mcp-name: <server name>` in the README, which is the package description on PyPI. It may sit inside an HTML comment.

The same second point also traps people installing by hand: `pip install sugo-cli` without `[lite]` installs a Sugo that refuses every file.

## Decision

**A (maintainer decision, 2026-11-07).** The package installs a second console script, `sugo-cli`, running the same entry point as `sugo`. `sugo` stays the documented command; `sugo-cli` exists for runners that use the package name, such as `uvx sugo-cli`.

**B (maintainer decision, 2026-11-07: option 1).** The `lite` packages become base dependencies, with the same version ranges: installing `sugo-cli` installs a Sugo that converts. The `[lite]` extra stays, empty, so every existing command (`pip install "sugo-cli[lite]"`, the release check, the dev group) keeps working. `LEVEL_MISSING` and the `lite` check of `sugo doctor` stay: they now only catch a broken install. Rejected alternatives: a separate `sugo-mcp` package (one more package to publish and keep in step at every release), and staying out of the registry.

**C (maintainer decision, 2026-11-07).** The README carries the registry's ownership line, hidden in an HTML comment:

```
<!-- mcp-name: io.github.Muralnick/sugo -->
```

The GitHub login is written with its exact capitalisation: a published report (Audrey 1.1.3 release notes) says the registry compares the namespace as an exact string. `mcp-publisher publish` validates it; if it refuses the capitalisation, the line and `server.json` change together.

**`server.json`** at the repository root describes the server for the registry: name `io.github.Muralnick/sugo`, package `sugo-cli` on PyPI with `runtimeHint` `uvx`, stdio transport, and the arguments `mcp` (fixed) and `--root` (required, repeatable, a folder chosen by the user). Its `version` and the package's must match; a test keeps them equal to `pyproject.toml`, so a release bumps all of them together.

**Publishing to the registry is not automated here.** It needs `mcp-publisher login github` by the maintainer and is done by hand after a PyPI release whose README carries the line above (the first is 0.1.2).

## Consequences

- `pip install sugo-cli` and `uvx sugo-cli mcp --root DIR` work without knowing about extras. The install is about 400 MB for everyone, as the README already says for the recommended install.
- No light install remains. None is useful today, since the base package converts nothing; if a smaller level is wanted later (for example Office and XML only), it comes back through a new ADR.
- The README's install commands drop `[lite]`; old commands with `[lite]` still work.
- One more console script name on the user's `PATH`.
- Residual: the registry's checks were read from its documentation, not yet exercised; the first publication may need a correction to `server.json`.
