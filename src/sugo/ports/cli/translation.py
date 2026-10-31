"""Make Typer, and the copy of Click inside it, speak the CLI's interface language (ADR-052).

Typer marks part of its own text for gettext ("Options", "[required]", the
help hint), looked up in the process-wide domain. The CLI points those
lookups at Sugo's "typer" catalog and refreshes the constants Typer
translates when it is imported.

The copy of Click inside Typer writes its text in English, with no hook.
The command classes below write the usage line and the help of ``--help``
themselves, and usage errors are recognised by their shape when Typer
prints them, from the table ``USAGE_ERRORS``. A message that no pattern
matches stays in English; nothing is guessed.

Only the ``sugo`` command does this, in its own process; the Python API and
the MCP server never call it.
"""

import re
from typing import Any

import typer.core
import typer.rich_utils
from typer.core import TyperCommand, TyperGroup

from sugo import i18n
from sugo.i18n import N_
from sugo.i18n import gettext as _

# Typer's constants translated once, at import: their English source text.
TYPER_CONSTANTS = {
    "DEPRECATED_STRING": "(deprecated) ",
    "DEFAULT_STRING": "[default: {}]",
    "ENVVAR_STRING": "[env var: {}]",
    "REQUIRED_LONG_STRING": "[required]",
    "ARGUMENTS_PANEL_TITLE": "Arguments",
    "OPTIONS_PANEL_TITLE": "Options",
    "COMMANDS_PANEL_TITLE": "Commands",
    "ERRORS_PANEL_TITLE": "Error",
    "ABORTED_TEXT": "Aborted.",
    "RICH_HELP": "Try [blue]'{command_path} {help_option}'[/] for help.",
}

_S = re.DOTALL
# Usage errors of Typer's Click, as Typer 0.27 words them, and their text in
# Sugo's catalog. Named groups fill the placeholders; groups listed third are
# messages themselves, translated in turn. User input reaches the groups, so
# only the templates, which are Sugo's, are ever used as format strings.
USAGE_ERRORS: tuple[tuple[re.Pattern[str], str, tuple[str, ...]], ...] = (
    (re.compile(r"Invalid value for (?P<hint>.+?): (?P<message>.*)", _S),
     N_("Invalid value for {hint}: {message}"), ("message",)),
    (re.compile(r"Invalid value: (?P<message>.*)", _S),
     N_("Invalid value: {message}"), ("message",)),
    (re.compile(r"Missing argument(?P<hint>(?: .+?)?)\.(?P<extra>(?: .*)?)", _S),
     N_("Missing argument{hint}.{extra}"), ()),
    (re.compile(r"Missing option(?P<hint>(?: .+?)?)\.(?P<extra>(?: .*)?)", _S),
     N_("Missing option{hint}.{extra}"), ()),
    (re.compile(r"Missing parameter(?P<hint>(?: .+?)?)\.(?P<extra>(?: .*)?)", _S),
     N_("Missing parameter{hint}.{extra}"), ()),
    (re.compile(r"No such option: (?P<name>.+?) \(Possible options: (?P<options>.+)\)", _S),
     N_("No such option: {name} (possible options: {options})"), ()),
    (re.compile(r"No such option: (?P<name>.+)", _S),
     N_("No such option: {name}"), ()),
    (re.compile(r"Got unexpected extra argument\(s\) \((?P<arguments>.*)\)", _S),
     N_("Got unexpected extra argument(s) ({arguments})"), ()),
    (re.compile(r"Option (?P<name>.+) does not take a value\.", _S),
     N_("Option {name} does not take a value."), ()),
    (re.compile(r"Option (?P<name>.+) requires an argument\.", _S),
     N_("Option {name} requires an argument."), ()),
    (re.compile(r"Option (?P<name>.+) requires (?P<count>\d+) arguments\.", _S),
     N_("Option {name} requires {count} arguments."), ()),
    (re.compile(r"Argument (?P<name>.+) takes (?P<count>\d+) values\.", _S),
     N_("Argument {name} takes {count} values."), ()),
    (re.compile(r"(?P<count>\d+) values are required, but (?P<given>\d+) given\.", _S),
     N_("{count} values are required, but {given} given."), ()),
    (re.compile(r"(?P<value>.+) is not a valid (?:integer|int range)\.", _S),
     N_("{value} is not a valid integer."), ()),
    (re.compile(r"(?P<value>.+) is not a valid (?:float|float range)\.", _S),
     N_("{value} is not a valid number."), ()),
    (re.compile(r"(?P<value>.+) is not in the range (?P<range>.+)\.", _S),
     N_("{value} is not in the range {range}."), ()),
    (re.compile(r"(?P<value>.+) is not a valid boolean\. Recognized values: (?P<states>.+)", _S),
     N_("{value} is not a valid boolean. Recognized values: {states}"), ()),
    (re.compile(r"(?P<value>.+) is not one of (?P<choices>.+)\.", _S),
     N_("{value} is not one of {choices}."), ()),
    (re.compile(r"(?P<kind>File|Directory|Path) (?P<name>'.*') does not exist\.", _S),
     N_("{kind} {name} does not exist."), ("kind",)),
    (re.compile(r"(?P<kind>File|Directory|Path) (?P<name>'.*') is a file\.", _S),
     N_("{kind} {name} is a file."), ("kind",)),
    (re.compile(r"(?P<kind>File|Directory|Path) (?P<name>'.*') is a directory\.", _S),
     N_("{kind} {name} is a directory."), ("kind",)),
    (re.compile(r"(?P<kind>File|Directory|Path) (?P<name>'.*') is not readable\.", _S),
     N_("{kind} {name} is not readable."), ("kind",)),
    (re.compile(r"(?P<kind>File|Directory|Path) (?P<name>'.*') is not writable\.", _S),
     N_("{kind} {name} is not writable."), ("kind",)),
    (re.compile(r"Value must be an iterable\.", _S),
     N_("Value must be an iterable."), ()),
)  # fmt: skip
# Words the patterns above capture and translate.
_WORDS = {"File": N_("File"), "Directory": N_("Directory"), "Path": N_("Path")}

_rich_format_error = typer.rich_utils.rich_format_error
_HIGHLIGHTS = list(typer.rich_utils.OptionHighlighter.highlights)


def use_language(language: str) -> None:
    """Make ``language`` the language of Sugo and Typer in this process.

    Raises:
        ValueError: If Sugo has no interface in that language.
    """
    i18n.activate(language)
    for module in (typer.core, typer.rich_utils):
        module._ = _typer_gettext  # type: ignore[attr-defined]
    for name, english in TYPER_CONSTANTS.items():
        setattr(typer.rich_utils, name, _typer_gettext(english))
    # Typer colours the usage line by finding its English prefix.
    usage = re.escape(_("Usage:") + " ")
    typer.rich_utils.OptionHighlighter.highlights = [*_HIGHLIGHTS, rf"(?P<usage>{usage})"]
    # Typer's main loop finds the function in its module when an error happens.
    typer.rich_utils.rich_format_error = _format_error


def translate_usage_error(message: str) -> str:
    """A usage error of Typer's Click in the interface language, if its shape is known."""
    if i18n.active_language() == "en":
        return message
    return _translated_error(message, depth=0)


def translate_help(command: Any) -> None:  # typer's click.Command
    """Translate the help of a command, its parameters and its subcommands, in place.

    Sugo's help texts are English, marked with ``N_`` where they are written
    and translated here, when the command line is parsed: they are built when
    the module is imported, before the language is known.
    """
    if getattr(command, "_sugo_translated", False):
        return
    command.help = _translated(command.help)
    command.short_help = _translated(command.short_help)
    for param in command.params:
        if hasattr(param, "help"):
            param.help = _translated(param.help)
    command._sugo_translated = True
    for subcommand in getattr(command, "commands", {}).values():
        translate_help(subcommand)


class _Translated:
    """The usage line and the help of ``--help``, which Typer's Click writes in English."""

    def format_usage(self, ctx: Any, formatter: Any) -> None:
        pieces = self.collect_usage_pieces(ctx)  # type: ignore[attr-defined]
        formatter.write_usage(ctx.command_path, " ".join(pieces), prefix=_("Usage:") + " ")

    def get_help_option(self, ctx: Any) -> Any:
        option = super().get_help_option(ctx)  # type: ignore[misc]
        if option is not None:
            option.help = _("Show this message and exit.")
        return option


class TranslatedCommand(_Translated, TyperCommand):
    """A Typer command whose usage line and ``--help`` follow the interface language."""


class TranslatedGroup(_Translated, TyperGroup):
    """A Typer group whose help, and its commands' help, follow the interface language."""

    def make_context(self, *args: Any, **kwargs: Any) -> Any:  # click.Context
        # Help texts are built at import, in English; the language is known now.
        translate_help(self)
        return super().make_context(*args, **kwargs)


def _format_error(self: Any) -> None:  # typer's click.ClickException
    # Named like the function it replaces, whose argument is named "self".
    english = self.format_message
    self.format_message = lambda: translate_usage_error(english())
    _rich_format_error(self)


def _translated_error(message: str, depth: int) -> str:
    # One level of nesting is enough: "Invalid value for X: <type's message>".
    for pattern, template, nested in USAGE_ERRORS:
        match = pattern.fullmatch(message)
        if match is None:
            continue
        values = {key: value or "" for key, value in match.groupdict().items()}
        for key in nested:
            value = values[key]
            if value in _WORDS:
                values[key] = i18n.gettext(_WORDS[value])
            elif depth == 0:
                values[key] = _translated_error(value, depth + 1)
        return i18n.gettext(template).format(**values)
    return message


def _translated(text: str | None) -> str | None:
    return None if text is None else i18n.gettext(text)


def _typer_gettext(message: str) -> str:
    return i18n.dgettext("typer", message)
