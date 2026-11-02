# ADR-051: Basic TOML configuration for v0.1

**Status:** Accepted  
**Date:** 2026-10-30  
**Deciders:** project author  
**Implements:** ADR-011 (layered configuration, v0.1 subset), ARCHITECTURE §14, ROADMAP v0.1 "Basic TOML configuration"  
**Adds error code:** `CONFIG_INVALID`

## Context

v0.1 needs a configuration so that users do not repeat options on every command. Above all, the languages of the text rules (ADR-050) need a place to be set. ADR-011 designs layers, policies and locks for companies; v0.1 needs only the user's and the project's preferences.

## Decision

### Layers (maintainer decision)

```
defaults < user (platformdirs: ~/.config/sugo/config.toml on Linux)
         < project (./sugo.toml, or [tool.sugo] in ./pyproject.toml)
         < environment (SUGO_*) < command options
```

- **Project file:** read only from the current folder, never from a folder above it. `sugo.toml` wins over `[tool.sugo]`. A `pyproject.toml` that is not valid TOML belongs to another tool, so it gives a warning, not an error.
- **System layer:** the system layer with lockable keys (principle 8) comes after v0.1, with policies.
- **MCP server:** reads the **user file only**. A project file in the folder the agent was started in, or `SUGO_*` variables, could otherwise change what the server does. For the same reason its default languages ignore the locale: English, unless the user file names languages. Where the user file is found still follows `HOME` / `XDG_CONFIG_HOME`, like `SUGO_CACHE_DIR` for the cache. Those are set by the MCP client that launches the server, from the user's own client configuration, not by the agent. Whoever controls that launch already controls the process (security review).
- **Every command loads the configuration** before any other work. `sugo doctor` shows the files it read, the effective languages of the CLI and of `sugo mcp`, and any warning or error. With `--json`, warnings are not printed: stderr carries only the JSON error, and `sugo doctor` shows them.

### Keys (maintainer decision: the five v0.1 uses)

| Key | Values | Default | Option / variable |
|---|---|---|---|
| `general.languages` | list of `it`, `es`, `fr`, `de`, `en` | the system's language (from `LC_ALL`, `LC_MESSAGES`, `LANG` or the OS locale) if it has a pack, and English | `SUGO_LANGUAGES=it,en` |
| `cleaning.strip_tracking_urls` | `true` / `false` | `true` | `SUGO_STRIP_TRACKING_URLS` (`true/false/1/0/yes/no/on/off`) |
| `chunking.max_tokens` | integer from 32 to 8 192 | 512 | `--max-tokens` (same bounds), `SUGO_CHUNK_MAX_TOKENS` |
| `storage.cache` | `persistent` / `ephemeral` | `persistent` | `--no-cache`, `SUGO_CACHE` |
| `ui.language` | `auto` / `en` / `it` | `auto` | `SUGO_UI_LANGUAGE` (used by the Italian interface, ADR-052) |

Languages are stored sorted and without repeats, since order does not change the output. They and `strip_tracking_urls` are part of the config hash (ADR-050).

### Errors (maintainer decision: stop clearly)

- A key Sugo does not know, a wrong type or value, invalid TOML, an unreadable file or a file over 1 MB stops the command with **`CONFIG_INVALID`, exit code 2**. The message names the file or variable and the key, and what is expected, never the value given. A typo is therefore never ignored in silence. Unprintable characters in keys and paths are replaced with `?`: a quoted TOML key such as `"\u001b]52;c;…"` in a downloaded folder must not reach the terminal as an escape sequence (code review, the same attack ADR-048 closed for PDFs). A folder that cannot be searched is a `CONFIG_INVALID` too, never a crash.
- Keys that the design reserves for later versions only give a warning: `general.level`, `cleaning.compression`, `chunking.keep_tables_whole`, `storage.retention_days`, and the sections `[target]`, `[privacy]`, `[hardware]` and `[aliases]`. A file copied from ARCHITECTURE §14 therefore keeps working.
- Values are validated by strict pydantic models (ADR-037), so `"512"` is not a number and `"yes"` in a file is not a boolean. Environment variables are text by nature: they are parsed first, then validated one at a time so the error names the variable.

### Code

`sugo.config.settings` (`load`, `Settings`, `ConfigError`) reads only files and the environment. A new import-linter contract keeps it off extractors, cleaners, ports, storage and the network. The pipeline keeps explicit arguments; the ports pass the configured values. A test fixture isolates every test from the developer's own configuration.

## Alternatives considered

| Alternative | Why not |
|---|---|
| Ignore wrong keys with a warning | A typo such as `strip_tracking_url = false` would silently do nothing |
| Search parent folders for `sugo.toml` | Running Sugo inside a downloaded folder could pick up settings from anywhere above it |
| Project file and environment for MCP too | The agent's working folder and environment are not under the user's direct control |
| System layer and locks now | Policies are out of the v0.1 scope; they come together |
| A `--config FILE` option | Not needed yet; can be added as a minor change |

## Consequences

- New public contracts: the five keys, the five variables, the `CONFIG_INVALID` error code, and the `config` line of `sugo doctor`.
- The cache, chunk size and text settings of the CLI and the MCP server now follow the configuration. `--no-cache` and `--max-tokens` still win.
