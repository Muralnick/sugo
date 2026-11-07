# ADR-062: Interactive shell, first version

**Status:** Accepted (maintainer decisions 1-4, 2026-11-07)
**Date:** 2026-11-07
**Deciders:** project author
**Implements:** ARCHITECTURE §12 "Interactive shell", ROADMAP v0.2 (brought forward, maintainer decision 2026-11-07)
**Amends:** ADR-048 (`sugo` with no arguments)
**Adds dependencies:** `prompt_toolkit` 3.0.x (BSD-3-Clause) and `wcwidth` 0.8.x (MIT)

## Context

The maintainer's first hands-on test (2026-11-07) found the command line too "orthodox": every command needs the full path typed or pasted, quoted when it has spaces, and the options remembered. ARCHITECTURE §12 already designs the answer, an interactive shell started by `sugo` with no arguments: drag a file or type `@path`, `Ctrl+V` for the clipboard image, slash commands, Tab completion, history, `Esc` to cancel, live progress. It names prompt_toolkit for the input line. ADR-048 left the shell and prompt_toolkit for after v0.1; on 2026-11-07 the maintainer chose to start it right after 0.1.2.

### The dependency, checked on 2026-11-07

| | prompt_toolkit | wcwidth |
|---|---|---|
| Role | The input line: editing, history, Tab completion, key bindings, on Windows, macOS and Linux | Width of characters on screen; prompt_toolkit's only dependency |
| Licence | BSD-3-Clause (on the allow-list) | MIT (on the allow-list) |
| Version | 3.0.53, uploaded 2026-07-26 (over 14 days) | see below |
| Code | Pure Python, one wheel of 392 KB | see below |
| Its own dependencies | wcwidth only | none |
| Known vulnerabilities (OSV) | none | none |

wcwidth changed on 2026-09-23: from **0.9.0** every release also ships **compiled native wheels** for each platform, which uv and pip prefer to the pure-Python one. Up to **0.8.5** (uploaded 2026-09-23, pure Python) it was plain Python. Native code from a small single-maintainer project is a larger supply-chain and memory-safety surface than the problem needs (computing column widths).

## Decision

### 1. Dependencies (maintainer decision, 2026-11-07)

- `prompt_toolkit>=3.0.53,<3.1`, base dependency, so the shell is always there.
- `wcwidth>=0.8.5,<0.9`: pinned below the first release with native wheels. Raising it needs a new ADR, after checking what the compiled part does.
- Both are imported only inside `sugo.ports.cli.shell`; an import-linter contract keeps them out of the core, like the other port libraries.

### 2. When the shell opens

- `sugo` with no arguments **in an interactive terminal** (stdin and stdout are terminals) opens the shell. This changes ADR-048, where it printed the help.
- Not in a terminal (a script, a pipe, CI), `sugo` with no arguments keeps printing the help and exit code 2, so no script changes behaviour.
- `sugo shell` opens it explicitly. `sugo --help` is unchanged. Every existing command and option is unchanged.

### 3. What the first version does

Only what Sugo can already do; the rest of ARCHITECTURE §12's list comes with the features behind it.

| Input | Effect |
|---|---|
| A path, dragged onto the window or typed, with or without quotes, or `@path` | Converts it; Markdown shown, tokens before and after, where the output went |
| Several paths on one line, or a folder's `*.pdf` | Converts each, one after the other, as `sugo convert` |
| `Ctrl+V` on an empty line, or `/clip` | Converts the image in the clipboard, as `sugo clip`. Windows Terminal keeps `Ctrl+V` for its own paste and never sends it to programs, so there `/clip` is the way |
| `/save [folder]` | Writes the last result as `NAME.md` (and `.jsonl` / `.receipt.json` when made) |
| `/stats` | Tokens per LLM provider for the last file, as `sugo stats` |
| `/explain` | What was removed or edited and why, from the last file's receipt |
| `/chunks [size]`, `/receipt`, `/cache` | Turn chunks, the receipt or the page cache on or off for the next files |
| `/verify FILE RECEIPT` | As `sugo verify` |
| `/doctor` | As `sugo doctor` |
| `/help`, `/exit` (or `Ctrl+D`) | |
| `Tab` | Completes slash commands and paths |
| `Esc` | Clears the line being typed |
| `Ctrl+C` during a conversion | Cancels it and returns to the prompt |

Progress: one line per file while it converts, then its tokens before and after. Page-by-page progress needs the pipeline to report pages and comes with that change (implementation note, 2026-11-07). Done on 2026-11-08: the internal pipeline takes an `on_page` callback, and the shell shows "Converting NAME, page N"; pages taken from the cache are not reported, and the total is not shown because the PDF extractor does not expose it (implementation note).

Where prompt_toolkit cannot run, such as Git Bash's mintty terminal on Windows, which is not a Windows console, the shell falls back to a plain input line: every command works, without Tab completion, history or `Ctrl+V` (implementation note, 2026-11-07).

Shell-only messages (a wrong argument, nothing converted yet) are plain messages, not new error codes: the CLI's error codes are a public contract.

Left for when the features exist: `/level` (only `lite` exists), `/profile` (v0.3), `/provider`, `/compress`, `/preview`, user-defined aliases.

### 4. Privacy and safety

- **History stays in memory** for the session only, and is lost on exit: typed lines hold file names, and principle 11 keeps file names out of anything Sugo stores by default. A history file can come later, opt-in, through its own ADR.
- Everything printed goes through the same control-character removal as the CLI (ADR-048), so a document cannot write escape sequences into the terminal. Rich markup stays off.
- Paths go through the same checks and size limits as `sugo convert`; nothing runs a shell; the shell never executes typed text as a command other than its own slash commands.
- Messages in the interface language (ADR-052), as the rest of the CLI.

## Alternatives considered

| Alternative | Why not |
|---|---|
| A shell on Python's `input()` only | No Tab completion, no history and no key bindings on Windows, where `readline` does not exist; Ctrl+V for images cannot be caught |
| `wcwidth` 0.9.x with native wheels | More native code than needed; can be revisited with its own review |
| A saved history file by default | Stores file names on disk without asking (principle 11) |
| Open the shell for `sugo` with no arguments everywhere | A script calling `sugo` with no arguments would hang waiting for input |

## Consequences

- New public contract: `sugo shell`, `sugo` with no arguments in a terminal, the slash commands. Exit codes and `--json` outputs are unchanged.
- Two small pure-Python dependencies, about 0.7 MB.
- `sugo` becomes usable without remembering options or quoting paths, the main problem of the first hands-on test.
- The shell reuses the CLI's conversion code; it adds no new way to read files.
