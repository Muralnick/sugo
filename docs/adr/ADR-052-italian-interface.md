# ADR-052: Italian interface for v0.1

**Status:** Accepted  
**Date:** 2026-10-31  
**Deciders:** project author  
**Implements:** ADR-024 (complete Italian interface via gettext), ADR-051 (`ui.language`), ROADMAP v0.1 "Italian interface"  
**Updates:** ADR-048 (CLI messages were English only)

## Context

ADR-024 promises a complete Italian interface from the first release, through gettext. ADR-051 added the `ui.language` key (`auto`, `en`, `it`) but nothing used it yet. The CLI's text comes from four places: Sugo's own messages and help; the messages of Sugo's exceptions, raised deep in the extractors and the configuration; the text Typer writes itself (help panels, "Usage:", usage errors); and the operating system (reasons such as "No such file or directory").

Typer 0.27 bundles its own copy of Click (`typer._click`). That copy no longer marks its text for gettext: its usage errors are English sentences written in the code. Only Typer's own module still marks about twenty messages.

## Decision

### What is translated (maintainer decisions)

- **Everything the terminal shows to a person:** help texts, progress, results, warnings, errors and hints, `sugo doctor`, configuration errors, and Typer's text, including the usage errors of its copy of Click.
- **Always English:** error codes, JSON keys, `--json` output (messages and hints included), the MCP server (its help too), and log messages. Programs and agents read them, and English keeps them the same on every machine and bug reports comparable.
- **Style:** informal *tu* with the imperative ("Converti i file", "Controlla la cartella di uscita"). "chunk", "token", "Markdown", "cache" and "JSON" stay in English.

### Choosing the language

`ui.language` decides, through every layer of ADR-051 (`SUGO_UI_LANGUAGE` included). `auto` follows the system's language (`LC_ALL`, `LC_MESSAGES`, `LANG`, then the OS locale, which Windows names "Italian_Italy"); a language without an interface falls back to English. The CLI chooses before parsing the command line, so help and usage errors speak the language too. If the configuration is not valid, the CLI uses the system's language and the command then reports the error. `sugo mcp` reads no configuration for this: it is English. `--json` switches the command to English before anything else.

### Mechanism (no new dependency)

- `sugo.i18n` offers `gettext` (imported as `_`), `ngettext`, and `N_`, which only marks text translated later, such as help texts built when a module is imported. Placeholders use `str.format` and are filled after translation. The active language is process-wide and English by default: only the `sugo` command switches it, so the Python API stays English.
- **Catalogs are `.po` files read directly**, in `sugo/i18n/locales/<language>/<domain>.po`: text that can be reviewed, in the format translation tools such as Weblate edit. The standard library reads only compiled `.mo` files, which are binaries in the repository, and compiles the `Plural-Forms` header into Python code with `exec`. Sugo's reader (`sugo.i18n.catalog`) handles the subset of the format the catalogs use, refuses anything else, skips `fuzzy` drafts, and takes each language's plural rule from the code (`PLURAL_RULES`), never from the file. Translations still subclass the standard `gettext.NullTranslations`.
- **Two domains:** `sugo` for Sugo's own text, `typer` for the text Typer marks.
- **Exceptions are translated where they are raised**, in the language active then. The PDF worker process sends fixed English sentences, marked with `N_`; the parent looks them up as they are and never uses them as format strings, since the worker parses hostile PDFs.
- **Operating-system reasons** come from Sugo's own wording per `errno` in Italian (`file o cartella inesistente`, `permesso negato`, …), without the path; English keeps the system's own words, so `--json` does not change, and unknown errors keep the system's text. TOML parser details stay in English inside parentheses.
- **Configuration errors** translate pydantic's complaints by error type (`unknown key`, `must be at least 32`, …), still without the value given.

### Typer

- Typer's marked text: the CLI points the `_` of `typer.core` and `typer.rich_utils` at the `typer` catalog, and refreshes the constants `typer.rich_utils` translates at import (panel titles, `[default: …]`, the help hint).
- Typer's copy of Click: the CLI's command classes write the usage line ("Uso:", still coloured by Typer's highlighter) and the help of `--help` themselves. Usage errors are recognised by their shape when Typer prints them, from a table of 24 patterns in `sugo.ports.cli.translation`, and rebuilt from Sugo's templates. User input fills placeholders but is never a format string. **A message that no pattern matches stays in English**: nothing is guessed and nothing fails.
- Typer is pinned below 0.28. Tests check each pattern against a message in Typer's wording and against real errors, and check that the `typer` catalog holds exactly what the installed Typer marks, so an upgrade that changes a text fails in CI, not on a user's screen.

### Encoding

On Windows, when stderr is not a console (a pipe, a file, Git Bash), Python would write it in the ANSI code page while those terminals expect UTF-8: "è" would appear as "�". The CLI already wrote piped stdout in UTF-8; it now does the same for stderr.

### Guarantees

- Tests: every text marked in the code has a translation and no translation is stale; `_`, `N_` and `ngettext` take literal text only; translations keep the placeholders and Rich markup of their source; translations contain no control characters (they reach the terminal); `--json` and the MCP server stay English.
- import-linter: `sugo.i18n` depends on nothing else in Sugo, nor on Typer or Rich; `sugo.ports.mcp` never imports `sugo.ports.cli`.

### Adding a language

Copy `locales/it/` to `locales/<code>/`, translate, add the plural rule to `PLURAL_RULES`, the code to `sugo.i18n.LANGUAGES` and to the `ui.language` values (a public contract change under ADR-051). The catalog tests then check it like Italian.

## Alternatives considered

| Alternative | Why not |
|---|---|
| Compiled `.mo` files in the repository | Binaries nobody reviews; the standard reader runs `exec` on the plural header |
| Babel, to compile catalogs | A new dependency for a build step `.po` reading makes unnecessary |
| Translate by error code at the port | Loses the details (limits, page numbers) the messages carry |
| Leave Typer's usage errors in English | Maintainer chose a complete interface; the table keeps the risk at "stays English" |
| Translate `--json` messages | Scripts and bug reports would differ by machine |
| An Italian MCP server | Agents read it; ADR-051 already keeps it independent of the agent's environment |

## Consequences

- Behaviour changes, in English too: the `--max-tokens` help now shows its default, in Typer's format (`[default: (chunking.max_tokens, 512)]`): the old text in brackets was swallowed by Rich as markup and never appeared; piped stderr is UTF-8. The PDF worker's page-count refusal is recognised by its exact text before it is translated.
- Every new user-facing text must be marked and translated in the same pull request, or the catalog test fails.
- Typer upgrades need the catalog and the pattern table to be checked; the tests say where.
