# ADR-067: Public Python API, first version

**Status:** Accepted (maintainer decision of 2026-11-13: the API comes before the loaders; ADR approved the same day)
**Date:** 2026-11-13
**Deciders:** project author
**Implements:** ARCHITECTURE §"Python API" (first part); the prerequisite of the ROADMAP v0.2 LangChain and LlamaIndex loaders (ADR-068)
**Builds on:** ADR-015 (ports), ADR-022 (error model), ADR-023 (output schema), ADR-045 (page cache), ADR-051 (configuration)
**Adds:** a public contract (the names `sugo` exports)
**Adds dependencies:** none

## Context

ADR-015 lists the Python API as the first port, and ARCHITECTURE shows `sugo.convert(...)` and `sugo.Engine`. Neither exists: `sugo/__init__.py` and `sugo/api/__init__.py` hold only a docstring. The CLI, the web UI and the MCP server call `sugo.core.pipeline.convert_file` directly, and that function, its `Conversion` result and the extractor exceptions are internal: they change whenever the pipeline does.

The LangChain and LlamaIndex loaders (ADR-068) live in other distributions. They must depend on something that follows semantic versioning (principle 12), or every Sugo release can break them. Users who call Sugo from their own Python code need the same thing.

The ARCHITECTURE sketch also has `level`, `recipe`, `profile`, `Engine.convert_stream` and an async variant. Only the `lite` level exists, and there are no recipes, profiles or shared engine yet (v0.3, v0.4). This ADR covers only what Sugo can do today, and leaves room for the rest.

## Decision

### 1. What is public

Public means a name in `sugo.__all__`. Everything else, `sugo.api` included, is private even when it can be imported. The first version exports:

| Name | What it is |
|---|---|
| `convert(source, *, name=None, chunks=False, max_tokens=None, receipt=False, cache="ephemeral", level="lite")` | Convert one file and return a `Result` |
| `Result` | Frozen dataclass: the conversion's output and its facts (section 3) |
| `Chunk` | The chunk model already published as JSON Schema 1.0 (ADR-023), re-exported unchanged |
| `SugoError` | The one exception `convert` raises on purpose (section 4) |
| `__version__` | The installed version, as `sugo --version` prints it |

`level` accepts only `"lite"` for now. It is there so that adding `"normal"` and `"quality"` later does not change the signature. `Engine`, `convert_stream`, folders and the async variant come with the shared engine (v0.3) and containers (v0.4), each by amendment of this ADR.

### 2. Input

- `source` is a path (`str` or `os.PathLike`) or the file's `bytes`. A path is read exactly as the CLI reads it, with the same size limit. It is one file: no folders, wildcards or URLs. A string that looks like a URL is treated as a path and is not found, because Sugo never fetches anything outside its network gateway (principle 1, ADR-036).
- `name` gives the document its name and identity (ADR-047) when `source` is bytes. For a path it defaults to the path as given, as in the CLI.
- `chunks=True` also returns chunks, sized by `max_tokens`, or by the configured chunk size when `max_tokens` is None. `max_tokens` without `chunks=True` is a `ValueError`, as `--max-tokens` without `--chunks` is a usage error in the CLI.
- `receipt=True` also builds the receipt (ADR-056), at the same cost as in the CLI.

### 3. Result

`Result` holds the same facts as the CLI's JSON output: `markdown`, `chunks` (empty unless asked for), `source`, `source_sha256`, `kind`, `pages`, `failed_pages`, `removed`, `edited`, `secret_blocks`, `tokens`, `sugo_version`, `config_hash` and `receipt` (None unless asked for). `partial` is true when some pages could not be read, which is exit code 3 in the CLI. The fields are plain Python types and read-only mappings, so a caller cannot change a result by accident.

A document flagged as holding credentials (`secret_blocks > 0`) is returned, as the CLI returns it: the caller is the user, not an agent. Only the MCP server refuses such documents (ADR-053). What the loaders do with them is ADR-068's decision.

### 4. Errors

`convert` raises `SugoError` for every failure the user can act on. It carries the same `code`, `message` and `hint` as the CLI and MCP errors (ADR-022), and it chains the internal exception as `__cause__`. Callers match on `code`, a stable English string, never on the message, which is translated. Subclasses per family may come later; `code` stays the contract. `ValueError` and `TypeError` remain for wrong arguments, `OSError` for a path that cannot be read, as Python libraries usually do.

### 5. Settings and cache

- `convert` loads the settings as the CLI does (ADR-051): user file, project file in the current folder, then environment variables. So the same machine gives the same output from the CLI and the API, and the system layer with locked keys, when it comes, applies to both (principle 8). The arguments override the settings as the CLI flags do. `config_hash` records the result in every output (principle 6).
- `cache="ephemeral"` (the default) uses a private temporary page cache for the call, deleted at the end. A library call therefore leaves no document text on disk unless asked. `cache="user"` uses the user's persistent page cache, like the CLI, and is faster for repeated loads. `cache=None` keeps no cache at all.

### 6. Behaviour as a library

- **No output.** It never prints and adds no logging handler: the `sugo` logger gets a `NullHandler`, and logs stay without content (principle 11).
- **Fast import.** `import sugo` stays cheap: the pipeline, the OCR engine and the workers are imported on the first call, so the CLI's start-up does not slow down.
- **Concurrency.** The first version supports one call at a time per process. Calls from several threads are not guaranteed until the shared engine (ADR-018) defines how its workers are shared; the documentation says so.
- **Types.** The API is fully typed (the package already ships `py.typed`) and checked with mypy in strict mode.

### 7. Boundaries and tests

- A new import-linter contract: `sugo.api` may import the core, configuration and storage, never another port. The other ports keep calling the pipeline directly for now. Moving them onto the API is optional and can come later.
- Tests check that `sugo.__all__` holds exactly the names above, with the signature above. Changing either is a contract change, released under the 0.x caveat of ARCHITECTURE until 1.0.
- `docs/python-api.md` documents the API with one example per use, and the READMEs link it.

## Alternatives considered

- **Let the loaders import `sugo.core.pipeline`.** Fastest today, but any internal refactor would break published packages. Rejected (maintainer decision).
- **Start with `Engine` and streaming.** It needs the shared engine of v0.3. Starting with `convert` covers the loaders and simple scripts now, and `Engine` can be added without changing it.
- **Ignore the configuration files in the API, for reproducibility.** The output would then differ between CLI and API on the same machine, and a future administrator policy could be bypassed through Python. `config_hash` already makes each output traceable to its settings.
- **One exception class per error.** It mirrors the error codes twice. One class with a stable `code` keeps the contract small; subclasses can be added later without breaking callers that catch `SugoError`.

## Consequences

- Sugo gets its first Python contract. Every later change to these names follows semantic versioning (principle 12).
- The loaders of ADR-068 import only `sugo`, so their own import-linter rule can enforce it.
- The documented example `sugo.convert("manual.pdf", level="normal", recipe="book")` in ARCHITECTURE stays the target. When the API is implemented, ARCHITECTURE marks the parts that do not exist yet as planned.
