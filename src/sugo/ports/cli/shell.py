"""The interactive shell: ``sugo`` with no arguments in a terminal (ADR-062).

A line is either a slash command or one or more files. Files can be dragged
onto the window or typed, with or without quotes, ``@`` in front or not: a
name with spaces typed without quotes is joined back when that file exists.
``Ctrl+V`` on an empty line, or ``/clip``, converts the clipboard image.

Everything reuses the command line's own code (``sugo.ports.cli.app``): the
same pipeline calls, limits, error messages and control-character removal.
The shell keeps its history in memory only, because typed lines hold file
names (principle 11), and it never runs typed text as anything but its own
commands.
"""

import glob
import logging
import os
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import typer
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import CompleteEvent, Completer, Completion, PathCompleter
from prompt_toolkit.document import Document
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent
from prompt_toolkit.styles import Style
from rich import box
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from sugo import i18n
from sugo.core.constants import CHUNK_MAX_TOKENS_LIMIT, CHUNK_MIN_TOKENS, DISTRIBUTION_NAME
from sugo.i18n import N_, ngettext
from sugo.i18n import gettext as _
from sugo.ports.cache import page_cache
from sugo.ports.cli import app as cli
from sugo.ports.errors import unreadable

if TYPE_CHECKING:
    from sugo.config.settings import Settings
    from sugo.core.pipeline import Conversion

_log = logging.getLogger(__name__)

# A right-pointing angle quote: the prompt's arrow.
ARROW = chr(0x203A)
PROMPT = f"sugo {ARROW} "
# Sugo's tomato red, as on the web page; Rich and prompt_toolkit both turn
# colours off for NO_COLOR and for terminals without them.
ACCENT = "#e8795f"
# Cells of the bar that shows how many tokens a conversion saved.
_BAR_CELLS = 12
_STYLE = Style.from_dict(
    {
        "brand": f"bold {ACCENT}",
        "arrow": ACCENT,
        "bottom-toolbar": "noreverse #8a8a8a",
        "bottom-toolbar.on": "noreverse #7fbf7f",
        "bottom-toolbar.off": "noreverse #8a8a8a",
        "completion-menu.completion": "bg:#2b2b2b #d0d0d0",
        "completion-menu.completion.current": f"bg:{ACCENT} #1a1a1a bold",
    }
)
# Entries /explain prints per list; the saved receipt holds every one.
EXPLAIN_SHOWN = 50
# Characters of a removed or edited text /explain prints on one line.
EXPLAIN_TEXT_CHARS = 120
_WILDCARDS = frozenset("*?[")
# Characters of the shortest quoted text: the two quotes.
_QUOTES_LENGTH = 2
# /verify takes the file and its receipt.
_VERIFY_NAMES = 2


@dataclass
class Result:
    """One converted file, kept for /save, /stats and /explain."""

    source: str
    # None for the clipboard image.
    path: Path | None
    conversion: "Conversion"
    # The clipboard image's bytes; a file is read again when needed.
    data: bytes | None = None


@dataclass
class State:
    """What the shell remembers between lines, in memory only."""

    settings: "Settings"
    chunk_tokens: int | None = None
    receipt: bool = False
    cache: bool = True
    last: list[Result] = field(default_factory=list)

    @property
    def persistent_cache(self) -> bool:
        return self.cache and self.settings.storage.cache == "persistent"


# --- Reading a line -------------------------------------------------------------


def split_files(line: str) -> list[str]:
    """The file names on a line, as dragged or typed.

    Quotes and a leading ``@`` are removed. Words of a name with spaces typed
    without quotes are joined back when the joined name is an existing file.
    Wildcards (``*.pdf``) are expanded here, as no shell did it.
    """
    text = line.strip()
    if not text:
        return []
    whole = _unquoted(text.removeprefix("@"))
    if _is_file(whole):
        return [whole]
    words = _words(text)
    names: list[str] = []
    start = 0
    while start < len(words):
        for end in range(len(words), start, -1):
            joined = " ".join(words[start:end])
            if end - start == 1 or _is_file(joined):
                names.append(joined)
                start = end
                break
    expanded: list[str] = []
    for name in names:
        if _WILDCARDS.intersection(name) and not _is_file(name):
            expanded.extend(sorted(glob.glob(os.path.expanduser(name))) or [name])
        else:
            expanded.append(name)
    return expanded


def _words(text: str) -> list[str]:
    """Split on spaces outside quotes; on Linux and macOS a backslash escapes a space."""
    words: list[str] = []
    current: list[str] = []
    quote: str | None = None
    escaped = False
    started = False
    for char in text:
        if escaped:
            current.append(char)
            escaped = False
        elif quote is not None:
            if char == quote:
                quote = None
            else:
                current.append(char)
        elif char in "\"'":
            quote = char
            started = True
        elif char == "\\" and os.name != "nt":
            escaped = True
            started = True
        elif char.isspace():
            if current or started:
                words.append("".join(current))
            current, started = [], False
        else:
            if char == "@" and not current and not started:
                continue
            current.append(char)
            started = True
    if current or started:
        words.append("".join(current))
    return [word for word in words if word]


def _unquoted(text: str) -> str:
    if len(text) >= _QUOTES_LENGTH and text[0] == text[-1] and text[0] in "\"'":
        return text[1:-1]
    return text


def _is_file(name: str) -> bool:
    try:
        return Path(name).expanduser().is_file()
    except (OSError, ValueError):
        return False


# --- Commands -------------------------------------------------------------------


class Notice(Exception):  # noqa: N818 - shown to the user as a plain message
    """A shell message, such as a wrong argument; not an error code of the CLI."""


@dataclass(frozen=True)
class Command:
    usage: str
    help: str
    run: Callable[[State, str], None]


def _say(text: str, style: str | None = None) -> None:
    cli._stdout.print(Text(text, style=style or ""))


def _convert_files(state: State, names: list[str]) -> None:
    from sugo.core import pipeline

    settings = state.settings
    results: list[Result] = []
    with page_cache(enabled=state.persistent_cache) as cache:
        for name in names:
            path = Path(name).expanduser()
            source = path.as_posix()
            try:
                with cli._progress(cli._converting(source), quiet=False):
                    conversion = pipeline.convert_file(
                        path,
                        cache=cache,
                        count_raw_tokens=True,
                        max_chunk_tokens=state.chunk_tokens,
                        languages=settings.languages,
                        strip_tracking_urls=settings.cleaning.strip_tracking_urls,
                        receipt=state.receipt,
                    )
            except KeyboardInterrupt:
                raise
            except Exception as error:
                failure = unreadable(error) if isinstance(error, OSError) else None
                failure = failure or cli._as_cli_error(error)
                if failure is None:
                    raise
                cli._say_error(failure, source=source)
                continue
            result = Result(source, path, conversion)
            _show(result)
            results.append(result)
    if results:
        state.last = results
        _say(_("Type /save to write the Markdown to a folder, /stats or /explain for more."), "dim")


def _convert_clipboard(state: State, _argument: str = "") -> None:
    from sugo.core import pipeline
    from sugo.ports.cli.clipboard import read_clipboard_image

    data = read_clipboard_image()
    settings = state.settings
    with (
        page_cache(enabled=state.persistent_cache) as cache,
        cli._progress(_("Converting"), quiet=False),
    ):
        conversion = pipeline.convert(
            data,
            cache=cache,
            count_raw_tokens=True,
            max_chunk_tokens=state.chunk_tokens,
            languages=settings.languages,
            strip_tracking_urls=settings.cleaning.strip_tracking_urls,
            receipt=state.receipt,
        )
    result = Result(_("clipboard"), None, conversion, data)
    _show(result)
    state.last = [result]
    _say(_("Type /save to write the Markdown to a folder, /stats or /explain for more."), "dim")


def _show(result: Result) -> None:
    from sugo.metrics.tokenizer import count_tokens

    conversion = result.conversion
    console = cli._stdout
    console.rule(
        Text(cli._shown(result.source), style=f"bold {ACCENT}"), style=ACCENT, align="left"
    )
    if conversion.markdown:
        # Plain, with no frame around it, so it copies cleanly.
        cli._write(conversion.markdown + "\n")
    before = conversion.raw_tokens or 0
    after = count_tokens(conversion.markdown)
    saved = max(0.0, 100 * (before - after) / before) if before else 0.0
    pages = ngettext("{count} page", "{count} pages", conversion.pages).format(
        count=conversion.pages
    )
    line = Text()
    line.append("✓ ", style="bold green")
    line.append(cli._shown(result.source), style="bold")
    line.append(f"  {pages}  ", style="dim")
    line.append(_("{before} -> {after} tokens").format(before=before, after=after))
    line.append("  ")
    filled = round(saved / 100 * _BAR_CELLS)
    line.append("█" * filled, style="green")
    line.append("░" * (_BAR_CELLS - filled), style="dim")
    line.append("  ")
    line.append(_("{saved:.0f}% saved").format(saved=saved), style="bold green")
    console.print(line)
    cli._say_converted(result.source, conversion, None)


def _need_results(state: State) -> list[Result]:
    if not state.last:
        raise Notice(_("Nothing converted yet: drag a file here first."))
    return state.last


def _save(state: State, argument: str) -> None:
    results = _need_results(state)
    folders = split_files(argument) if argument.strip() else ["."]
    folder = Path(folders[0]).expanduser()
    cli._make_folder(folder)
    taken: set[str] = set()
    for result in results:
        conversion = result.conversion
        stem = result.path.stem if result.path else f"clip-{conversion.source_sha256[:12]}"
        name = stem
        number = 2
        while name.casefold() in taken:
            name = f"{stem} ({number})"
            number += 1
        taken.add(name.casefold())
        targets = [folder / f"{name}.md"]
        if conversion.chunks:
            targets.append(folder / f"{name}.jsonl")
        if conversion.receipt is not None:
            targets.append(folder / f"{name}.receipt.json")
        if result.path is not None and any(
            target.resolve() == result.path.resolve() for target in targets
        ):
            _say(
                cli._shown(result.source)
                + ": "
                + _("Saving here would overwrite the file itself; choose another folder."),
                "yellow",
            )
            continue
        written = cli._write_outputs(
            conversion,
            targets,
            front_matter=False,
            chunks=bool(conversion.chunks),
            receipt=conversion.receipt is not None,
        )
        _say(f"{cli._shown(result.source)} -> {', '.join(map(cli._shown, written))}")


def _stats(state: State, _argument: str) -> None:
    from sugo.core import pipeline
    from sugo.core.estimate import estimate_savings
    from sugo.metrics.providers import list_providers

    for result in _need_results(state):
        data = result.data
        if data is None and result.path is not None:
            try:
                data = pipeline.read_input(result.path)
            except OSError as error:
                raise unreadable(error) from error
        if data is None:
            continue
        estimate = estimate_savings(data, result.conversion, list_providers())
        cli._print_stats(result.source, estimate)


def _explain(state: State, _argument: str) -> None:
    from sugo.serializers.escape import drop_controls

    def line(text: str) -> str:
        flat = " ".join(drop_controls(text).split())
        return flat if len(flat) <= EXPLAIN_TEXT_CHARS else flat[: EXPLAIN_TEXT_CHARS - 1] + "…"

    def entry(page: int, cleaner: str, reason: str, *texts: str) -> Text:
        row = Text("  ")
        row.append(_("page {page}").format(page=page), style="dim")
        row.append("  ")
        row.append(cleaner, style=ACCENT)
        row.append(f"  {reason}")
        for text in texts:
            row.append(f"\n      «{line(text)}»", style="dim italic")
        return row

    console = cli._stdout
    for result in _need_results(state):
        receipt = result.conversion.receipt or _with_receipt(state, result).conversion.receipt
        if receipt is None:
            continue
        console.rule(
            Text(cli._shown(result.source), style=f"bold {ACCENT}"), style=ACCENT, align="left"
        )
        _say(_("Removed blocks: {count}").format(count=len(receipt.removed)), "bold")
        for removal in receipt.removed[:EXPLAIN_SHOWN]:
            texts = (removal.text,) if removal.text.strip() else ()
            console.print(entry(removal.page, removal.removed_by, removal.reason, *texts))
        _say(_("Edited text: {count}").format(count=len(receipt.edited)), "bold")
        for edit in receipt.edited[:EXPLAIN_SHOWN]:
            console.print(
                entry(
                    edit.page,
                    edit.edited_by,
                    edit.reason,
                    f"{line(edit.original)} -> {line(edit.replacement)}",
                )
            )
        _say(_("Uncertain blocks: {count}").format(count=len(receipt.flagged)), "bold")
        hidden = max(len(receipt.removed), len(receipt.edited)) - EXPLAIN_SHOWN
        if hidden > 0:
            _say(_("Some entries are not shown; /receipt and /save write them all."), "dim")


def _with_receipt(state: State, result: Result) -> Result:
    """The result converted again with a receipt; the page cache makes this quick."""
    from sugo.core import pipeline

    data = result.data
    if data is None and result.path is not None:
        try:
            data = pipeline.read_input(result.path)
        except OSError as error:
            raise unreadable(error) from error
    if data is None:
        return result
    settings = state.settings
    with (
        page_cache(enabled=state.persistent_cache) as cache,
        cli._progress(cli._converting(result.source), quiet=False),
    ):
        conversion = pipeline.convert(
            data,
            cache=cache,
            source=None if result.path is None else result.path.as_posix(),
            count_raw_tokens=True,
            max_chunk_tokens=state.chunk_tokens,
            languages=settings.languages,
            strip_tracking_urls=settings.cleaning.strip_tracking_urls,
            receipt=True,
        )
    updated = Result(result.source, result.path, conversion, result.data)
    state.last = [updated if item is result else item for item in state.last]
    return updated


def _switch(argument: str, current: bool) -> bool:
    word = argument.strip().casefold()
    if word in {"on", "si", "sì", "yes"}:
        return True
    if word in {"off", "no"}:
        return False
    return not current


def _on_off(value: bool) -> str:
    return _("on") if value else _("off")


def _chunks(state: State, argument: str) -> None:
    word = argument.strip().casefold()
    if word.isdigit():
        size = int(word)
        if not CHUNK_MIN_TOKENS <= size <= CHUNK_MAX_TOKENS_LIMIT:
            raise Notice(
                _("Chunk size must be between {min} and {max} tokens.").format(
                    min=CHUNK_MIN_TOKENS, max=CHUNK_MAX_TOKENS_LIMIT
                )
            )
        state.chunk_tokens = size
    elif _switch(word, state.chunk_tokens is not None):
        state.chunk_tokens = state.chunk_tokens or state.settings.chunking.max_tokens
    else:
        state.chunk_tokens = None
    if state.chunk_tokens is None:
        _say(_("Chunks: off"))
    else:
        _say(_("Chunks: on, {tokens} tokens each").format(tokens=state.chunk_tokens))


def _receipt(state: State, argument: str) -> None:
    state.receipt = _switch(argument, state.receipt)
    _say(_("Receipt: {value}").format(value=_on_off(state.receipt)))


def _cache(state: State, argument: str) -> None:
    if state.settings.storage.cache != "persistent":
        _say(_("The cache is off in your configuration file."))
        return
    state.cache = _switch(argument, state.cache)
    _say(_("Cache on disk: {value}").format(value=_on_off(state.cache)))


def _verify(_state: State, argument: str) -> None:
    names = split_files(argument)
    if len(names) != _VERIFY_NAMES:
        raise Notice(_("Give the file and its receipt: /verify FILE RECEIPT"))
    cli.verify_command(Path(names[0]).expanduser(), Path(names[1]).expanduser(), False)


def _doctor(_state: State, _argument: str) -> None:
    cli.doctor_command(False)


def _help(_state: State, _argument: str) -> None:
    table = Table(
        title=_("Commands"),
        title_justify="left",
        title_style=f"bold {ACCENT}",
        box=box.ROUNDED,
        border_style=ACCENT,
        show_header=False,
        padding=(0, 1),
    )
    table.add_column(style=f"bold {ACCENT}", no_wrap=True)
    table.add_column()
    for command in COMMANDS.values():
        table.add_row(command.usage, i18n.gettext(command.help))
    cli._stdout.print(table)
    _say(_("Drag a file onto this window or type its path, then press Enter."), "dim")
    _say(_("Ctrl+V on an empty line converts the image in the clipboard."), "dim")


class _Exit(Exception):  # noqa: N818 - a signal, not an error
    """Leave the shell."""


def _exit(_state: State, _argument: str) -> None:
    raise _Exit


COMMANDS: dict[str, Command] = {
    "/save": Command(
        "/save [FOLDER]", N_("Write the last result as NAME.md (default: here)"), _save
    ),
    "/stats": Command("/stats", N_("Tokens saved per LLM provider for the last result"), _stats),
    "/explain": Command("/explain", N_("What was removed or edited, and why"), _explain),
    "/clip": Command("/clip", N_("Convert the image in the clipboard"), _convert_clipboard),
    "/chunks": Command(
        "/chunks [on|off|SIZE]", N_("Also split the next files into chunks for RAG"), _chunks
    ),
    "/receipt": Command(
        "/receipt [on|off]", N_("Also make a receipt for the next files"), _receipt
    ),
    "/cache": Command("/cache [on|off]", N_("Keep the page cache on disk or not"), _cache),
    "/verify": Command("/verify FILE RECEIPT", N_("Check a receipt, as sugo verify"), _verify),
    "/doctor": Command("/doctor", N_("Check the installation, as sugo doctor"), _doctor),
    "/help": Command("/help", N_("Show this help"), _help),
    "/exit": Command("/exit", N_("Leave the shell (or Ctrl+D)"), _exit),
}


def run_line(state: State, line: str) -> None:
    """Run one line: a slash command or files. Errors are reported, never raised."""
    text = line.strip()
    if not text:
        return
    try:
        if text.startswith("/"):
            name, _space, argument = text.partition(" ")
            command = COMMANDS.get(name.casefold())
            if command is None:
                _say(
                    _("Unknown command {name}; type /help.").format(name=cli._shown(name)), "yellow"
                )
                return
            command.run(state, argument)
        else:
            _convert_files(state, split_files(text))
    except _Exit:
        raise
    except Notice as notice:
        _say(str(notice), "yellow")
    except KeyboardInterrupt:
        _say(_("Cancelled."), "yellow")
    except typer.Exit:
        # A reused command (verify, doctor) already printed its result.
        pass
    except typer.TyperException as error:
        # Typer carries its own copy of Click: click itself is not installed.
        message = getattr(error, "format_message", None)
        _say(message() if callable(message) else str(error), "yellow")
    except Exception as error:
        failure = cli._as_cli_error(error)
        if failure is None:
            raise
        cli._say_error(failure)


# --- The input line -------------------------------------------------------------


class _ShellCompleter(Completer):
    """Slash commands, then paths, for the word under the cursor."""

    def __init__(self) -> None:
        self._paths = PathCompleter(expanduser=True)

    def get_completions(self, document: Document, event: CompleteEvent) -> Iterator[Completion]:
        text = document.text_before_cursor
        if text.startswith("/") and " " not in text:
            for name in COMMANDS:
                if name.startswith(text.casefold()):
                    yield Completion(name, start_position=-len(text))
            return
        word = text.rsplit(" ", 1)[-1].lstrip("@\"'")
        yield from self._paths.get_completions(Document(word, len(word)), event)


def _key_bindings(clipboard_line: str) -> KeyBindings:
    bindings = KeyBindings()

    @Condition
    def empty() -> bool:
        from prompt_toolkit.application.current import get_app

        return not get_app().current_buffer.text

    @bindings.add("c-v", filter=empty)
    def _paste_image(event: KeyPressEvent) -> None:
        # Terminals that keep Ctrl+V for their own paste never send it: /clip.
        event.app.exit(result=clipboard_line)

    @bindings.add("escape", eager=True)
    def _clear(event: KeyPressEvent) -> None:
        event.app.current_buffer.reset()

    return bindings


def _short_folder() -> str:
    """The current folder, with the home folder written as ~ to keep it short."""
    folder = Path.cwd()
    try:
        return str(Path("~") / folder.relative_to(Path.home()))
    except ValueError:
        return str(folder)


def _banner() -> None:
    from importlib.metadata import version

    body = Text()
    body.append("Sugo", style=f"bold {ACCENT}")
    body.append(f"  {version(DISTRIBUTION_NAME)}", style="dim")
    body.append("\n" + _("Documents, reduced.") + "\n\n", style="italic")
    body.append(_("Drag a file onto this window or type its path, then press Enter.") + "\n")
    body.append(_("/help for the commands · /clip for a screenshot · /exit to leave"), style="dim")
    body.append(
        "\n" + _("Folder: {folder}").format(folder=cli._shown(_short_folder())), style="dim"
    )
    cli._stdout.print(
        Panel(body, box=box.ROUNDED, border_style=ACCENT, padding=(1, 2), expand=False)
    )


def run_shell(lines: Iterable[str] | None = None) -> None:
    """Run the shell until /exit or Ctrl+D; ``lines`` replaces the keyboard in tests."""
    with cli._failures(json_output=False):
        settings = cli._settings(quiet=False)
        cli._require_lite()
    state = State(settings)
    _banner()
    if lines is not None:
        for line in lines:
            try:
                run_line(state, line)
            except _Exit:
                return
        return
    read = _line_reader(state)
    while True:
        try:
            line = read()
        except KeyboardInterrupt:
            continue
        except EOFError:
            return
        try:
            run_line(state, line)
        except _Exit:
            return


def _line_reader(state: State) -> Callable[[], str]:
    """prompt_toolkit's input line, or plain ``input`` where it cannot run.

    prompt_toolkit needs a real console on Windows; terminals such as Git
    Bash's mintty are not one. The plain line still converts files and runs
    every command, without Tab completion, history or Ctrl+V.
    """

    def toolbar() -> FormattedText:
        parts: list[tuple[str, str]] = [("", " ")]
        switches = (
            (_("chunks"), state.chunk_tokens is not None),
            (_("receipt"), state.receipt),
            (_("cache"), state.persistent_cache),
        )
        for index, (name, value) in enumerate(switches):
            if index:
                parts.append(("", "  ·  "))
            parts.append(("", f"{name} "))
            parts.append(
                ("class:bottom-toolbar.on" if value else "class:bottom-toolbar.off", _on_off(value))
            )
        parts.append(("", "     " + _("Tab completes · Esc clears · /help")))
        return FormattedText(parts)

    try:
        session: PromptSession[str] = PromptSession(
            history=InMemoryHistory(),
            completer=_ShellCompleter(),
            complete_while_typing=False,
            key_bindings=_key_bindings("/clip"),
            bottom_toolbar=toolbar,
            style=_STYLE,
        )
    except Exception as error:  # noqa: BLE001 - any failure means: no rich input line here
        _log.info("simple input line: %s", type(error).__name__)
        _say(
            _("Simple mode in this terminal: no Tab completion; use /clip for screenshots."), "dim"
        )
        return lambda: input(PROMPT)
    message = FormattedText([("class:brand", "sugo"), ("class:arrow", f" {ARROW} ")])
    return lambda: session.prompt(message)
