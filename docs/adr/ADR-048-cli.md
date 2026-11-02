# ADR-048: Command line (`sugo`, `stats`, `clip`, `doctor`)

**Status:** Accepted  
**Date:** 2026-10-29  
**Deciders:** project author  
**Implements:** ADR-015 (ports), ADR-022 (CLI conventions, exit codes), ARCHITECTURE §12  
**Adds dependencies:** `typer`, `rich`  
**Adds error codes:** `LEVEL_MISSING`, `FILE_UNREADABLE`, `OUTPUT_UNWRITABLE`, `INTEGRITY_CHECK_FAILED`, `CLIPBOARD_NO_IMAGE`, `CLIPBOARD_UNAVAILABLE`

## Context

Roadmap step 7a gives v0.1 its command line: one-shot conversion, savings per provider, the clipboard and diagnostics. The interactive shell is out of scope for v0.1. Commands, options, the `--json` output and exit codes are public contracts (principle 12). Step 7b, the MCP server, has its own ADR.

## Decision

### Libraries (maintainer decision)

**Typer 0.27.3** (MIT) and **Rich 15.0.0** (MIT), as ARCHITECTURE §12 names them, in the base dependencies so that `sugo` always runs. They add Typer's own dependencies, `shellingham` (ISC), `annotated-doc` (MIT) and `colorama` (BSD-3-Clause, Windows only), and Rich's, `markdown-it-py` and `mdurl` (MIT) and `pygments` (BSD-2-Clause). Typer 0.27 carries its own copy of Click (BSD-3-Clause). All licences are on the allow-list. Every version is more than 14 days old, enforced by `exclude-newer` (ADR-035). `prompt_toolkit` is left for the interactive shell, after v0.1.

Typer is configured to stay quiet. **Rich tracebacks are off**, because they print local variables, which can hold document text. **Shell completion is off**, because installing it edits the user's shell profile. Rich markup and highlighting are off for everything Sugo prints, so a file named `[red]x.png` is shown as typed.

### Commands (maintainer decision)

```
sugo FILE... [-o DIR] [--chunks] [--max-tokens N] [--front-matter] [--no-cache] [--json]
sugo convert FILE...          (the same; sugo FILE is short for it)
sugo stats FILE [--provider NAME]... [--json]
sugo clip [-o DIR] [--json]
sugo doctor [--json]
sugo --version
```

- **Converting.** Without `-o`, the Markdown of one file goes to stdout; with `--chunks`, its chunks go to stdout as JSON Lines. With `-o`, each input becomes `DIR/NAME.md`, plus `NAME.jsonl` with `--chunks`, written atomically and owner-only (ADR-047). Several inputs need `-o`, and a file that fails never stops the others. Folders are not inputs in v0.1. Two inputs whose names differ only in case, or an output that would replace an input, are refused before anything runs. `--front-matter` adds the provenance fields `source`, `source_sha256`, `sugo_version` and `config_hash`. `--max-tokens` needs `--chunks` and is at least 32 (default 512).
- **Source names.** `source`, and therefore `document_id`, is the path as typed, normalised by `pathlib` (`./a.pdf` and `a.pdf` both become `a.pdf`; backslashes become `/`). It is never made absolute, which would put the user's home folder into every chunk and change ids from machine to machine. This closes the residual noted in ADR-047.
- **Page cache on by default** (maintainer decision): the persistent cache of ADR-045, owner-only. `--no-cache` uses a temporary cache per job, deleted at the end. A cache that cannot be opened falls back to the temporary one, with a warning.
- **`sugo stats`** converts the file, counting the tokens of the uncleaned text as well (new `count_raw_tokens` option of the pipeline, which never changes the output or its config hash). It then reports both baselines of ADR-003 from a new core operation, `sugo.core.estimate.estimate_savings`, which the MCP tool `estimate_savings` will reuse. Images are compared against every bundled provider, or against those named with `--provider`, at their default tier. Unverified formulas are marked, and providers that would refuse the image are listed.
- **`sugo clip`** reads the clipboard through Pillow's `ImageGrab`. That is native on Windows and macOS. On Linux it runs `wl-paste` or `xclip` with an argument list, never through a shell. The image is checked against the pixel limit, re-encoded as PNG and converted like a file, so the same limits apply. With `-o`, the output is named `clip-<first 12 hex digits of its SHA-256>.md`, which is stable and never collides.
- **`sugo doctor`** reads only. It reports the version, Python, CPUs, the lite level's packages, the OCR models and the tokenizer vocabulary (both SHA-256 verified), the cache folder and its size, and clipboard support. It warns while PyMuPDF is older than 2.0 (ADR-043), and exits 1 if any check fails.

### Streams, JSON and exit codes

Results go to stdout; messages, progress and errors go to stderr. The progress spinner appears only on a terminal. Rich honours `NO_COLOR`. Piped stdout is UTF-8 on every OS.

With `--json`, the conversion commands print one object, `{"documents": [...]}`. Each document is either `{"source", "status": "ok", "kind", "source_sha256", "pages", "failed_pages", "tokens", "removed", ...}` or `{"source", "status": "error", "error": {code, message, hint, details}}`. A successful document also carries `markdown` (and `chunks` with `--chunks`) when printed, or `outputs` (the files written) with `-o`. A failure that ends the whole command is printed to stderr as `{"error": {...}}`.

| Exit | When |
|---|---|
| 0 | Everything converted |
| 1 | Error: unsupported or damaged input, encrypted PDF, unreadable file, clipboard without an image |
| 2 | Usage error (Click's own code) |
| 3 | Partial: some files failed, or some PDF pages could not be read (the new `Conversion.failed_pages`, numbered from 1) |
| 4 | Refused for security: a file or image over the limits, or a bundled model or vocabulary failing its SHA-256 check |
| 5 | `sugo[lite]` is not installed (`LEVEL_MISSING`, checked before anything is imported) |
| 130 | Interrupted with Ctrl+C |

When every file fails, the exit code is that of the failures, or 1 if they differ. Unexpected exceptions are not caught: they end with a plain Python traceback (no locals) and exit 1, so bugs are reported rather than hidden.

### Terminal safety (security review)

A crafted PDF can carry real control characters, e.g. a font whose encoding maps a letter to `/uni001B`. Printed to a terminal they become escape sequences that clear the screen, fake a prompt, set the window title or write the clipboard (OSC 52, honoured by Windows Terminal). The Markdown serializer therefore drops C0 controls except tab and line feed, DEL and C1 from every block, table cell and chunk heading path **before escaping** (`drop_controls`), so a dropped character can never hide structure from the escaper. Controls that `str.splitlines` treats as line breaks (CR, VT, FF, FS, GS, RS, NEL) become line feeds, keeping lines as before. They never print, so no visible content is lost. Every output inherits this — stdout, files, `--json`, JSONL and the MCP port — and a property test checks that no control character survives rendering. Rich markup is off on both consoles.

Residual (low): on Linux and macOS, Pillow's `ImageGrab` decodes the clipboard with all its image plugins before Sugo's PNG/JPEG/WEBP allow-list. The clipboard is filled by the user's own applications; reading the raw PNG bytes instead is left for a later change.

### Privacy

Error messages come from Sugo's own exceptions, which never quote document text. For an `OSError` only the reason is shown, not the full message with its path. The CLI prefixes a failure with the file name the user typed, because the user needs it. That goes to the user's own terminal only and is never logged (principle 11). Logging goes to stderr at WARNING level.

## Alternatives considered

| Alternative | Why not |
|---|---|
| `argparse` (no dependency) | More code to maintain, plainer help; the maintainer chose Typer + Rich as designed |
| `prompt_toolkit` now | Only the interactive shell needs it, and the shell comes after v0.1 |
| Absolute paths as `source` | Leak the home folder into chunks; ids would differ across machines |
| Cache off by default | Every run would redo OCR; the cache is already private to the user |
| Folder inputs in v0.1 | Need the plan-first flow and mirrored output (ARCHITECTURE §11); out of the v0.1 scope |

## Consequences

- New public contracts: commands, options, the `--json` shape, the exit-code mapping and six error codes (maintainer decision).
- Base install grows by Typer, Rich and their dependencies, about 3 MB.
- Messages are English only. Italian (ADR-024) still has to come before the v0.1 release.
- A file named like a command (`stats`) needs `sugo convert stats` or `sugo ./stats`.
