# ADR-066: `sugo uninstall` and `sugo cache clear`

**Status:** Accepted (maintainer decisions 1-3, 2026-11-12)
**Date:** 2026-11-12
**Deciders:** project author
**Implements:** ROADMAP v0.1.x "an uninstall command"; the `clear` part of ARCHITECTURE §10's `sugo cache stats|clean|clear|verify`
**Builds on:** ADR-019 and ADR-045 (storage, page cache), ADR-048 (CLI), ADR-051 (configuration)
**Adds:** two commands, three error codes
**Adds dependencies:** none

## Context

Removing the program (`uv tool uninstall sugo-cli`, `pip uninstall sugo-cli`) leaves Sugo's files on disk. The README lists them for deletion by hand, and there are only two:

| What | Where (platformdirs) | Files Sugo writes there |
|---|---|---|
| Settings | user config folder, e.g. `~/.config/sugo` | `config.toml`, only if the user wrote it |
| Page cache | user cache folder, e.g. `~/.cache/sugo`, or `SUGO_CACHE_DIR` | `cache.db`, `cache.db-wal`, `cache.db-shm` |

Nothing else persists: the shell keeps its history in memory (ADR-062), the ephemeral cache and the web UI's launcher page live in temporary folders deleted on close. The cache holds the text of converted documents, so leaving it behind is a privacy problem for exactly the users who care most. On Windows both folders share `%LOCALAPPDATA%\sugo`, the cache in its `Cache` subfolder.

A Python program cannot reliably remove its own package. It does not know for sure which tool installed it (uv tool, uvx, pipx, pip, a virtual environment, a container), and on Windows `sugo.exe` is locked while it runs.

## Decision

### 1. `sugo uninstall` deletes Sugo's data and tells how to remove the program (maintainer decision 1)

1. It lists what it will delete, with paths and sizes: the settings file and the cache folder, saying the cache holds text of converted documents.
2. It asks for confirmation (decision 2, below), then deletes.
3. It prints the command that removes the program, guessed from where Sugo is installed: `uv tool uninstall sugo-cli` for a uv tool, `uv cache clean sugo-cli` for uvx (how MCP Registry clients run Sugo), `pipx uninstall sugo-cli` for pipx, `pip uninstall sugo-cli` otherwise. It never runs another program.
4. It reminds the user to remove Sugo from AI agents too (`claude mcp remove sugo`): their configuration belongs to them, and Sugo does not edit it.

`--keep-config` keeps the settings file. Project files (`sugo.toml`, `[tool.sugo]`), output files and receipts are the user's and are never touched; the command says so. A cache folder used once through a different `SUGO_CACHE_DIR` is unknown to it.

### 2. Confirmation (maintainer decision 2)

- In a terminal, the list ends with "Delete them? [y/N]"; only an explicit yes deletes. The Italian interface accepts `s`/`sì` as well as `y`/`yes`.
- `--yes` skips the question, for scripts.
- Outside a terminal without `--yes` the command deletes nothing and exits with code 2 (usage), so no script deletes data by accident.
- When there is nothing to delete, it says so and prints only the step 3 and 4 advice.

### 3. `sugo cache clear` (maintainer decision 3)

Deletes the page cache, as step 1 does for the cache, with no question: the cache is regenerable and deleting it only costs speed. It is the way to remove document text without uninstalling. `stats`, `clean` and `verify` stay for later; `cache` is a command group so they can join it.

### 4. Deleting safely

The cache folder can be anything `SUGO_CACHE_DIR` names, such as the home folder. So:

- **Never a recursive delete.** Only the named files above are removed; then the folder is removed only if empty (`rmdir`). A folder holding other files is kept, and the output says so.
- **No links followed.** As ADR-045 for opening: a cache folder or file that is a symbolic link, not a plain directory or file, has other hard links, or belongs to another user is refused, and nothing in it is deleted. A settings file that is a link has the link removed, never its target.
- **Not while in use.** Before deleting, the cache is opened with SQLite and locked exclusively, with a short wait. If another Sugo is converting (a shell, `sugo ui`, an agent's MCP server), the command stops, deletes nothing, and asks the user to close the others and try again. A damaged database is deleted anyway; nothing can be using it as a cache.
- Order: cache first, then settings, then the settings folder if empty, which on Windows is the cache folder's parent.
- File names and paths are shown only on the user's terminal, escaped as in ADR-048, never logged (principle 11).

### 5. Public contract

New commands: `sugo uninstall [--yes] [--keep-config]`, `sugo cache clear`. New error codes, with exit codes:

| Code | Exit | When |
|---|---|---|
| `CACHE_IN_USE` | 1 | Another Sugo process holds the cache |
| `STORAGE_REFUSED` | 4 | A file or folder to delete is a link, not plain, or not the user's |
| `DELETE_FAILED` | 1 | The system refused to delete a file (permissions, read-only disk) |

A file named `cache` or `uninstall` can still be converted with `sugo convert cache`, as for every other command name. Neither command has `--json` in this version.

## Alternatives considered

- **Also run uv or pip to remove the package.** Rejected (decision 1): fragile on Windows (locked executable), wrong in virtual environments and containers, and it would make Sugo run another program with the user's rights.
- **Delete the whole folders recursively.** Rejected: with `SUGO_CACHE_DIR` pointing at a shared folder it would delete the user's own files.
- **Ask only with `--yes`, never interactively.** Rejected (decision 2): one more step for the person at the keyboard, with no extra safety over an explicit question that defaults to no.
- **Clear the cache through SQLite (`DELETE` and vacuum) instead of deleting the files.** Rejected for these commands: deleting the files also removes free pages that may still hold old text. Deleted files may still survive on SSDs; full-disk encryption remains the real protection (ARCHITECTURE §10).

## Consequences

- One command removes every trace Sugo leaves, and the README's manual table becomes the fallback.
- Three new error codes and two commands join the CLI contract.
- The installer guess may be wrong for unusual layouts; the advice then is the generic `pip uninstall sugo-cli`, which the README also gives.
