"""The ``sugo`` command: convert, stats, clip and doctor (ADR-022, ADR-048).

``sugo FILE`` is short for ``sugo convert FILE``. Results go to stdout,
messages and progress to stderr; Rich turns colours off when stderr is not a
terminal and honours ``NO_COLOR``. ``--json`` prints one JSON object instead.
Exit codes follow ``ExitCode``. Typer's rich tracebacks are off: they print
local variables, which can hold document text, and shell completion is off:
installing it would edit the user's shell profile.

Messages and help follow ``ui.language`` (ADR-052); ``--json`` output and
``sugo mcp`` are always in English, for the programs and agents that read them.
"""

import io
import json
import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from importlib.metadata import version
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any

import typer
from rich.console import Console
from rich.table import Table
from rich.text import Text

from sugo import i18n
from sugo.core.constants import CHUNK_MAX_TOKENS, CHUNK_MAX_TOKENS_LIMIT, CHUNK_MIN_TOKENS
from sugo.i18n import N_, ngettext
from sugo.i18n import gettext as _
from sugo.ports.cli.doctor import Status, missing_lite_packages, run_checks
from sugo.ports.cli.translation import TranslatedCommand, TranslatedGroup, use_language
from sugo.ports.errors import (
    ExitCode,
    PortError,
    from_exception,
    level_missing,
    unreadable,
)

if TYPE_CHECKING:
    from sugo.config.settings import Settings
    from sugo.core.estimate import SavingsEstimate
    from sugo.core.pipeline import Conversion
    from sugo.storage.page_cache import PageCache

_log = logging.getLogger(__name__)
# Markup and highlighting off: file names and messages are shown as typed.
_stderr = Console(stderr=True, markup=False, highlight=False, soft_wrap=True)
_stdout = Console(markup=False, highlight=False)
_STATUS_STYLES = {Status.OK: "green", Status.WARNING: "yellow", Status.ERROR: "bold red"}
_STATUS_NAMES = {Status.OK: N_("ok"), Status.WARNING: N_("warning"), Status.ERROR: N_("error")}
_KIND_NAMES = {"pdf": N_("pdf"), "image": N_("image")}


class _DefaultConvert(TranslatedGroup):
    """Makes ``sugo FILE`` mean ``sugo convert FILE``."""

    def parse_args(self, ctx: Any, args: list[str]) -> list[str]:  # click.Context
        if args and args[0] not in self.commands and args[0] not in ("--help", "--version"):
            args = ["convert", *args]
        return super().parse_args(ctx, args)


app = typer.Typer(
    cls=_DefaultConvert,
    name="sugo",
    help=N_("Documents, reduced: convert PDFs and images into compact Markdown, locally."),
    add_completion=False,
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)


def main() -> None:
    """Entry point of the ``sugo`` script."""
    for stream in (sys.stdout, sys.stderr):
        if not stream.isatty() and isinstance(stream, io.TextIOWrapper):
            # Piped output is read by other programs, or shown by terminals such
            # as Git Bash: UTF-8 everywhere, never the Windows code page, which
            # cannot encode most scripts. Messages have accents in Italian.
            stream.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.WARNING, format="sugo: %(levelname)s: %(message)s")
    use_language(_ui_language(sys.argv[1:]))
    app()


def _ui_language(args: list[str]) -> str:
    """The interface language, chosen before parsing so help and usage errors speak it."""
    if args and args[0] == "mcp":
        # The MCP server always speaks English, and reads no project file (ADR-049, ADR-051).
        return "en"
    from sugo.config.settings import ConfigError, load

    try:
        setting = load().settings.ui.language
    except ConfigError:
        # The command reports the error itself, in the system's language.
        setting = "auto"
    return i18n.resolve(setting)


def _show_version(value: bool) -> None:
    # Eager: runs while options are parsed, before a command is required.
    if value:
        _write(version("sugo") + "\n")
        raise typer.Exit()


@app.callback()
def _root(
    show_version: Annotated[
        bool,
        typer.Option(
            "--version",
            is_eager=True,
            callback=_show_version,
            help=N_("Show the version and exit."),
        ),
    ] = False,
) -> None:
    """Options of the ``sugo`` command itself; the help is the Typer app's."""


# --- convert ------------------------------------------------------------------


@app.command(
    "convert",
    cls=TranslatedCommand,
    help=N_(
        "Convert files into compact Markdown (sugo FILE is short for sugo convert FILE).\n\n"
        "Without -o the Markdown of one file goes to stdout; with --chunks, its "
        "chunks as JSON Lines. With -o each file becomes NAME.md, and NAME.jsonl "
        "with --chunks. A file that fails does not stop the others."
    ),
)
def convert_command(
    files: Annotated[
        list[Path],
        # Not exists=True: a missing file is reported with the others, not as a
        # usage error that would stop the whole batch.
        typer.Argument(dir_okay=False, metavar="FILE...", help=N_("PDF, PNG, JPEG or WEBP files.")),
    ],
    output: Annotated[
        Path | None,
        typer.Option(
            "-o", "--output", file_okay=False, help=N_("Write NAME.md files to this folder.")
        ),
    ] = None,
    chunks: Annotated[
        bool, typer.Option("--chunks", help=N_("Also split into chunks (JSONL) for RAG."))
    ] = False,
    max_tokens: Annotated[
        int | None,
        typer.Option(
            "--max-tokens",
            min=CHUNK_MIN_TOKENS,
            max=CHUNK_MAX_TOKENS_LIMIT,
            help=N_("Chunk size in tokens."),
            # Typer's own default line: brackets in a help text would be Rich markup.
            show_default=f"chunking.max_tokens, {CHUNK_MAX_TOKENS}",
        ),
    ] = None,
    front_matter: Annotated[
        bool, typer.Option("--front-matter", help=N_("Start the Markdown with YAML metadata."))
    ] = False,
    no_cache: Annotated[
        bool, typer.Option("--no-cache", help=N_("Keep no page cache on disk."))
    ] = False,
    json_output: Annotated[bool, typer.Option("--json", help=N_("Print one JSON object."))] = False,
) -> None:
    """Convert files; the help text is in the decorator, for translation."""
    _english_for_json(json_output)
    if max_tokens is not None and not chunks:
        raise typer.BadParameter(_("--max-tokens needs --chunks"), param_hint="'--max-tokens'")
    if output is None and len(files) > 1:
        raise typer.BadParameter(_("several files need an output folder"), param_hint="'-o'")
    if front_matter and output is None and (chunks or json_output):
        # Only a Markdown file or Markdown on stdout can carry front matter.
        raise typer.BadParameter(
            _("front matter goes only into Markdown output"), param_hint="'--front-matter'"
        )
    targets = None if output is None else _targets(files, output, chunks=chunks)
    with _failures(json_output):
        settings = _settings(quiet=json_output)
        chunk_tokens = (max_tokens or settings.chunking.max_tokens) if chunks else None
        _require_lite()
        from sugo.core import pipeline

        if output is not None:
            _make_folder(output)
        documents: list[dict[str, Any]] = []
        errors: list[PortError] = []
        partial = False
        with _page_cache(enabled=not no_cache and settings.storage.cache == "persistent") as cache:
            for path in files:
                source = path.as_posix()
                try:
                    with _progress(_converting(source), quiet=json_output):
                        conversion = pipeline.convert_file(
                            path,
                            cache=cache,
                            max_chunk_tokens=chunk_tokens,
                            languages=settings.languages,
                            strip_tracking_urls=settings.cleaning.strip_tracking_urls,
                        )
                    written = (
                        None
                        if targets is None
                        else _write_outputs(conversion, targets[path], front_matter=front_matter)
                    )
                except Exception as error:
                    # Only reading raises OSError here: writing raises OUTPUT_UNWRITABLE.
                    failure = unreadable(error) if isinstance(error, OSError) else None
                    failure = failure or _as_cli_error(error)
                    if failure is None:
                        raise
                    errors.append(failure)
                    if json_output:
                        documents.append(_failed_json(source, failure))
                    else:
                        _say_error(failure, source=source)
                    continue
                partial = partial or bool(conversion.failed_pages)
                if json_output:
                    documents.append(_document_json(conversion, written, with_chunks=chunks))
                else:
                    _say_converted(source, conversion, written)
                    if written is None:
                        _print_result(conversion, chunks=chunks, front_matter=front_matter)
        if json_output:
            _write_json({"documents": documents})
        _finish(len(files), errors, partial=partial)


def _targets(files: list[Path], output: Path, *, chunks: bool) -> dict[Path, list[Path]]:
    """Output paths per input; refuses names that collide or overwrite an input."""
    targets: dict[Path, list[Path]] = {}
    seen: dict[str, Path] = {}
    inputs = {path.resolve() for path in files}
    for path in files:
        # Case-insensitive: "Report.pdf" and "report.png" collide on Windows and macOS.
        key = path.stem.casefold()
        if key in seen and seen[key].resolve() != path.resolve():
            raise typer.BadParameter(
                _("{first} and {second} would both write {name}.md").format(
                    first=seen[key].as_posix(), second=path.as_posix(), name=path.stem
                ),
                param_hint="FILES",
            )
        seen[key] = path
        names = [output / f"{path.stem}.md"] + ([output / f"{path.stem}.jsonl"] if chunks else [])
        if any(name.resolve() in inputs for name in names):
            raise typer.BadParameter(
                _("writing {name}.md would overwrite an input file").format(name=path.stem),
                param_hint="'-o'",
            )
        targets[path] = names
    return targets


def _write_outputs(
    conversion: "Conversion", targets: list[Path], *, front_matter: bool
) -> list[str]:
    from sugo.exporters.jsonl import write_jsonl
    from sugo.exporters.markdown import write_markdown

    markdown_path, *rest = targets
    try:
        write_markdown(
            markdown_path,
            conversion.markdown,
            metadata=_metadata(conversion) if front_matter else None,
        )
        if rest:
            write_jsonl(rest[0], conversion.chunks)
    except OSError as error:
        raise PortError(
            code="OUTPUT_UNWRITABLE",
            message=i18n.os_reason(error),
            exit_code=ExitCode.ERROR,
            hint=_("Check the output folder: free space and permission to write."),
        ) from error
    return [target.as_posix() for target in targets]


def _print_result(conversion: "Conversion", *, chunks: bool, front_matter: bool) -> None:
    if chunks:
        from sugo.exporters.jsonl import jsonl_lines

        for line in jsonl_lines(conversion.chunks):
            _write(line)
        return
    if front_matter:
        from sugo.exporters.markdown import front_matter as render_front_matter

        _write(render_front_matter(_metadata(conversion)) + "\n")
    if conversion.markdown:
        _write(conversion.markdown + "\n")


def _metadata(conversion: "Conversion") -> dict[str, str | None]:
    return {
        "source": conversion.source,
        "source_sha256": conversion.source_sha256,
        "sugo_version": conversion.sugo_version,
        "config_hash": conversion.config_hash,
    }


# --- stats --------------------------------------------------------------------


@app.command(
    "stats",
    cls=TranslatedCommand,
    help=N_("Show the tokens Sugo saves on a file, per LLM provider."),
)
def stats_command(
    file: Annotated[
        Path,
        typer.Argument(exists=True, dir_okay=False, readable=True, help=N_("PDF or image file.")),
    ],
    provider: Annotated[
        list[str] | None,
        typer.Option("--provider", help=N_("Compare with this provider only; repeatable.")),
    ] = None,
    json_output: Annotated[bool, typer.Option("--json", help=N_("Print one JSON object."))] = False,
) -> None:
    """Show savings per provider; the help text is in the decorator, for translation."""
    _english_for_json(json_output)
    from sugo.metrics.providers import list_providers

    available = list_providers()
    providers = provider or available
    unknown = sorted(set(providers) - set(available))
    if unknown:
        raise typer.BadParameter(
            _("unknown provider {names}; choose from {choices}").format(
                names=", ".join(unknown), choices=", ".join(available)
            ),
            param_hint="'--provider'",
        )
    with _failures(json_output):
        settings = _settings(quiet=json_output)
        _require_lite()
        from sugo.core import pipeline
        from sugo.core.estimate import estimate_json, estimate_savings

        source = file.as_posix()
        with (
            _page_cache(enabled=settings.storage.cache == "persistent") as cache,
            _progress(_converting(source), quiet=json_output),
        ):
            try:
                data = pipeline.read_input(file)
            except OSError as error:
                raise unreadable(error) from error
            conversion = pipeline.convert(
                data,
                cache=cache,
                source=source,
                count_raw_tokens=True,
                languages=settings.languages,
                strip_tracking_urls=settings.cleaning.strip_tracking_urls,
            )
        estimate = estimate_savings(data, conversion, providers)
        if json_output:
            _write_json(
                {
                    "source": source,
                    "failed_pages": list(conversion.failed_pages),
                    **estimate_json(estimate),
                }
            )
        else:
            _print_stats(source, estimate)
        _finish(1, [], partial=bool(conversion.failed_pages))


def _print_stats(source: str, estimate: "SavingsEstimate") -> None:
    pages = ngettext("{count} page", "{count} pages", estimate.pages).format(count=estimate.pages)
    kind = i18n.gettext(_KIND_NAMES.get(estimate.kind.value, estimate.kind.value))
    _stdout.print(Text(f"{source}: {kind}, {pages}"))
    text = estimate.text
    summary = _("Text before and after cleaning: {before} -> {after} tokens ({saved:.1f}% saved)")
    _stdout.print(
        Text(
            summary.format(
                before=text.baseline_tokens, after=text.result_tokens, saved=text.saved_percent
            )
        )
    )
    if not estimate.images and not estimate.rejected_by:
        return
    table = Table(title=_("Sending the image vs sending its Markdown"))
    table.add_column(_("provider"))
    table.add_column(_("tier"))
    for column in (_("image tokens"), _("Markdown tokens"), _("saved")):
        table.add_column(column, justify="right")
    for image in estimate.images:
        name = (
            image.provider
            if image.formula_verified
            else _("{provider} (unverified)").format(provider=image.provider)
        )
        table.add_row(
            name,
            image.tier,
            str(image.baseline_tokens),
            str(image.result_tokens),
            f"{image.saved_percent:.1f}%",
        )
    for name in estimate.rejected_by:
        table.add_row(name, "-", _("rejected"), "-", "-")
    _stdout.print(table)


# --- clip ---------------------------------------------------------------------


@app.command(
    "clip", cls=TranslatedCommand, help=N_("Convert the image in the clipboard, e.g. a screenshot.")
)
def clip_command(
    output: Annotated[
        Path | None,
        typer.Option(
            "-o", "--output", file_okay=False, help=N_("Write clip-HASH.md to this folder.")
        ),
    ] = None,
    json_output: Annotated[bool, typer.Option("--json", help=N_("Print one JSON object."))] = False,
) -> None:
    """Convert the clipboard image; the help text is in the decorator, for translation."""
    _english_for_json(json_output)
    with _failures(json_output):
        settings = _settings(quiet=json_output)
        _require_lite()
        from sugo.core import pipeline
        from sugo.ports.cli.clipboard import read_clipboard_image

        data = read_clipboard_image()
        with (
            _page_cache(enabled=settings.storage.cache == "persistent") as cache,
            _progress(_("Converting"), quiet=json_output),
        ):
            conversion = pipeline.convert(
                data,
                cache=cache,
                languages=settings.languages,
                strip_tracking_urls=settings.cleaning.strip_tracking_urls,
            )
        written = None
        if output is not None:
            _make_folder(output)
            name = f"clip-{conversion.source_sha256[:12]}"
            written = _write_outputs(conversion, [output / f"{name}.md"], front_matter=False)
        if json_output:
            _write_json({"documents": [_document_json(conversion, written, with_chunks=False)]})
        else:
            _say_converted(_("clipboard"), conversion, written)
            if written is None:
                _print_result(conversion, chunks=False, front_matter=False)


# --- doctor -------------------------------------------------------------------


@app.command(
    "doctor",
    cls=TranslatedCommand,
    help=N_("Check the installation: levels, verified models, cache and clipboard."),
)
def doctor_command(
    json_output: Annotated[bool, typer.Option("--json", help=N_("Print one JSON object."))] = False,
) -> None:
    """Run the checks; the help text is in the decorator, for translation."""
    _english_for_json(json_output)
    checks = run_checks()
    if json_output:
        _write_json(
            {
                "checks": [
                    {"name": check.name, "status": check.status.value, "detail": check.detail}
                    for check in checks
                ]
            }
        )
    else:
        table = Table(show_header=False, box=None)
        for check in checks:
            table.add_row(
                i18n.gettext(check.name),
                Text(i18n.gettext(_STATUS_NAMES[check.status]), style=_STATUS_STYLES[check.status]),
                check.detail,
            )
        _stdout.print(table)
    if any(check.status is Status.ERROR for check in checks):
        raise typer.Exit(ExitCode.ERROR)


# --- mcp ----------------------------------------------------------------------


@app.command(
    "mcp",
    cls=TranslatedCommand,
    help=N_("Serve Sugo to AI agents over MCP (stdio), reading only inside the given folders."),
)
def mcp_command(
    root: Annotated[
        list[Path],
        typer.Option(
            "--root",
            exists=True,
            file_okay=False,
            help=N_("A folder agents may read; repeatable. Required."),
        ),
    ],
) -> None:
    """Serve over MCP, in English: ``main`` chooses no other language for it."""
    from sugo.ports.mcp.access import Roots

    try:
        roots = Roots(root)
    except ValueError as error:
        raise typer.BadParameter(str(error), param_hint="'--root'") from None
    with _failures(json_output=False):
        from sugo.config.settings import load

        # The user's file only: neither a project file in the folder the agent
        # was started in nor the agent's environment may change the settings.
        loaded = load(project=False, environment=False)
        _warn(loaded.warnings)
        _require_lite()
        from sugo.ports.mcp.server import serve

        serve(roots, loaded.settings)


# --- shared -------------------------------------------------------------------


def _settings(*, quiet: bool) -> "Settings":
    """The effective settings; warnings go to stderr unless ``quiet``.

    With --json, stderr carries only a JSON error, so warnings are left to
    ``sugo doctor``.

    Raises:
        sugo.config.settings.ConfigError: If a file or variable is not valid.
    """
    from sugo.config.settings import load

    loaded = load()
    if not quiet:
        _warn(loaded.warnings)
    return loaded.settings


def _english_for_json(json_output: bool) -> None:
    """``--json`` output is read by programs: its messages are always in English."""
    if json_output:
        use_language("en")


def _converting(source: str) -> str:
    return _("Converting {source}").format(source=source)


def _warn(warnings: tuple[str, ...]) -> None:
    for warning in warnings:
        _stderr.print(Text(_("warning: {message}").format(message=warning)))


def _require_lite() -> None:
    """Fail with LEVEL_MISSING before importing the pipeline, which needs the lite level."""
    missing = missing_lite_packages()
    if missing:
        raise level_missing(missing)


def _as_cli_error(error: Exception) -> PortError | None:
    return error if isinstance(error, PortError) else from_exception(error)


@contextmanager
def _failures(json_output: bool) -> Iterator[None]:
    """Report a failure that ends the command, and exit with its code."""
    try:
        yield
    except KeyboardInterrupt:
        _stderr.print(_("Interrupted."))
        raise typer.Exit(ExitCode.INTERRUPTED) from None
    except Exception as caught:
        error = _as_cli_error(caught)
        if error is None:
            raise
        if json_output:
            _stderr.file.write(json.dumps({"error": error.as_json()}, ensure_ascii=False) + "\n")
        else:
            _say_error(error)
        raise typer.Exit(error.exit_code) from None


@contextmanager
def _page_cache(*, enabled: bool) -> Iterator["PageCache | None"]:
    """The user's persistent page cache; None (a temporary one per job) if off or unusable."""
    if not enabled:
        yield None
        return
    from sugo.storage.page_cache import CacheUnavailableError, PageCache
    from sugo.storage.paths import StorageDirError

    try:
        cache = PageCache.default()
    except (CacheUnavailableError, StorageDirError, OSError):
        _log.warning("the page cache is unavailable; using a temporary one")
        yield None
        return
    with cache:
        yield cache


@contextmanager
def _progress(message: str, quiet: bool) -> Iterator[None]:
    if quiet or not _stderr.is_terminal:
        yield
        return
    with _stderr.status(Text(message)):
        yield


def _make_folder(output: Path) -> None:
    try:
        output.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise PortError(
            code="OUTPUT_UNWRITABLE",
            message=i18n.os_reason(error),
            exit_code=ExitCode.ERROR,
            details={"output": output.as_posix()},
        ) from error


def _finish(total: int, errors: list[PortError], *, partial: bool) -> None:
    """Exit with the code for the whole run: one broken file never hides the others."""
    if not errors:
        if partial:
            raise typer.Exit(ExitCode.PARTIAL)
        return
    if len(errors) < total:
        raise typer.Exit(ExitCode.PARTIAL)
    codes = {error.exit_code for error in errors}
    raise typer.Exit(codes.pop() if len(codes) == 1 else ExitCode.ERROR)


def _document_json(
    conversion: "Conversion", written: list[str] | None, *, with_chunks: bool
) -> dict[str, Any]:
    from sugo.metrics.tokenizer import count_tokens

    document: dict[str, Any] = {
        "source": conversion.source,
        "status": "ok",
        "kind": conversion.kind.value,
        "source_sha256": conversion.source_sha256,
        "pages": conversion.pages,
        "failed_pages": list(conversion.failed_pages),
        "tokens": count_tokens(conversion.markdown),
        "removed": dict(conversion.removed),
    }
    if written is not None:
        document["outputs"] = written
    else:
        document["markdown"] = conversion.markdown
        if with_chunks:
            document["chunks"] = [chunk.model_dump(mode="json") for chunk in conversion.chunks]
    return document


def _failed_json(source: str, error: PortError) -> dict[str, Any]:
    return {"source": source, "status": "error", "error": error.as_json()}


def _say_converted(source: str, conversion: "Conversion", written: list[str] | None) -> None:
    if written is not None:
        _stderr.print(Text(f"{source} -> {', '.join(written)}"))
    if conversion.failed_pages:
        pages = ", ".join(str(page) for page in conversion.failed_pages)
        message = ngettext(
            "{source}: page {pages} could not be read",
            "{source}: pages {pages} could not be read",
            len(conversion.failed_pages),
        )
        _stderr.print(Text(message.format(source=source, pages=pages), style="yellow"))


def _say_error(error: PortError, source: str | None = None) -> None:
    line = Text()
    if source is not None:
        line.append(f"{source}: ")
    line.append(_("error"), style="bold red")
    line.append(f" {error.code}: {error.message}")
    _stderr.print(line)
    if error.hint:
        _stderr.print(Text("  " + _("hint: {hint}").format(hint=error.hint), style="dim"))


def _write(text: str) -> None:
    sys.stdout.write(text)
    sys.stdout.flush()


def _write_json(value: object) -> None:
    _write(json.dumps(value, ensure_ascii=False) + "\n")
