"""The settings of v0.1, read in layers from TOML files and the environment (ADR-051).

Layers, each overriding the one before (ADR-011):

    defaults < user (~/.config/sugo/config.toml)
             < project (./sugo.toml, or [tool.sugo] in ./pyproject.toml)
             < environment (SUGO_LANGUAGES, ...) < command options

The system layer with locked keys comes after v0.1. The project file is read
only from the current folder, never from a folder above it. The MCP server
reads the user layer only, so neither a project file nor the agent's
environment can change its settings.

Every value is validated. A key Sugo does not know, or a wrong value, stops
with ``ConfigError``: a typo is never ignored in silence. Keys the design
reserves for later versions (ARCHITECTURE §14) give a warning instead.
Errors name the file or variable and the key, never the value.
"""

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, ClassVar, Literal

import platformdirs
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from sugo.core.constants import CHUNK_MAX_TOKENS, CHUNK_MAX_TOKENS_LIMIT, CHUNK_MIN_TOKENS
from sugo.i18n import gettext as _
from sugo.i18n import os_reason, system_language
from sugo.languages.packs import PACKS

# Larger "configuration" files are not configuration.
MAX_CONFIG_BYTES = 1024 * 1024

# Environment variables and the key each one sets.
ENVIRONMENT: dict[str, tuple[str, str]] = {
    "SUGO_LANGUAGES": ("general", "languages"),
    "SUGO_STRIP_TRACKING_URLS": ("cleaning", "strip_tracking_urls"),
    "SUGO_CHUNK_MAX_TOKENS": ("chunking", "max_tokens"),
    "SUGO_CACHE": ("storage", "cache"),
    "SUGO_UI_LANGUAGE": ("ui", "language"),
}

# Keys of the designed schema (ARCHITECTURE §14) that v0.1 does not use yet.
_RESERVED: dict[str, frozenset[str] | None] = {
    "general": frozenset({"level"}),
    "target": None,
    "cleaning": frozenset({"compression"}),
    "chunking": frozenset({"keep_tables_whole"}),
    "privacy": None,
    "storage": frozenset({"retention_days"}),
    "hardware": None,
    "aliases": None,
}

_TRUE = frozenset({"1", "true", "yes", "on"})
_FALSE = frozenset({"0", "false", "no", "off"})


class ConfigError(ValueError):
    """A configuration file or variable is not valid."""

    code: ClassVar[str] = "CONFIG_INVALID"


class _Section(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class General(_Section):
    # None: the system's language and English (``default_languages``).
    languages: tuple[str, ...] | None = None

    @field_validator("languages", mode="before")
    @classmethod
    def _as_tuple(cls, value: object) -> object:
        # TOML arrays arrive as lists; strict mode wants the declared tuple.
        return tuple(value) if isinstance(value, list) else value

    @field_validator("languages", mode="after")
    @classmethod
    def _known(cls, value: tuple[str, ...] | None) -> tuple[str, ...] | None:
        if value is None:
            return None
        if not value:
            raise ValueError(_("at least one language is needed"))
        unknown = sorted(set(value) - set(PACKS))
        if unknown:
            raise ValueError(
                _("languages must be among: {languages}").format(languages=", ".join(sorted(PACKS)))
            )
        # Order and repeats do not change the output.
        return tuple(sorted(set(value)))


class Cleaning(_Section):
    strip_tracking_urls: bool = True


class Chunking(_Section):
    max_tokens: Annotated[int, Field(ge=CHUNK_MIN_TOKENS, le=CHUNK_MAX_TOKENS_LIMIT)] = (
        CHUNK_MAX_TOKENS
    )


class Storage(_Section):
    cache: Literal["persistent", "ephemeral"] = "persistent"


class Ui(_Section):
    language: Literal["auto", "en", "it"] = "auto"


class Settings(_Section):
    """The effective settings, after every layer."""

    general: General = General()
    cleaning: Cleaning = Cleaning()
    chunking: Chunking = Chunking()
    storage: Storage = Storage()
    ui: Ui = Ui()

    @property
    def languages(self) -> tuple[str, ...]:
        """The languages whose text rules apply; ``load`` always sets them."""
        return self.general.languages or ("en",)


@dataclass(frozen=True)
class Loaded:
    """Settings, the files they came from, and warnings for the user."""

    settings: Settings
    sources: tuple[Path, ...]
    warnings: tuple[str, ...]


def load(*, cwd: Path | None = None, project: bool = True, environment: bool = True) -> Loaded:
    """Read every layer and return the effective settings.

    Args:
        cwd: The folder whose project file is read; None for the current one.
        project: Read the project file. The MCP server does not.
        environment: Read the ``SUGO_*`` variables. The MCP server does not.

    Raises:
        ConfigError: If a file cannot be read or holds an unknown key or a
            wrong value, or a variable has a wrong value.
    """
    try:
        return _load(cwd, project=project, environment=environment)
    except OSError as error:
        # A folder that cannot be searched, e.g. a configuration folder with
        # no permissions: reported like any other configuration problem.
        name = printable(error.filename or _("configuration"))
        raise ConfigError(_unreadable(name, error)) from None


def _load(cwd: Path | None, *, project: bool, environment: bool) -> Loaded:
    layers: list[tuple[str, dict[str, Any]]] = []
    sources: list[Path] = []
    warnings: list[str] = []
    user = user_config_path()
    if user.is_file():
        layers.append((printable(str(user)), _read_toml(user)))
        sources.append(user)
    if project:
        found = _project_layer(Path.cwd() if cwd is None else cwd, warnings)
        if found is not None:
            path, table = found
            layers.append((printable(str(path)), table))
            sources.append(path)
    merged: dict[str, dict[str, Any]] = {}
    for name, table in layers:
        table = _without_reserved(name, table, warnings)
        _validate(name, table)
        _merge(merged, table)
    if environment:
        # Already validated variable by variable, so errors name the variable.
        _merge(merged, _environment())
    settings = _validate(_("configuration"), merged)
    if settings.general.languages is None:
        # Resolved here, once: without the environment layer (the MCP server)
        # the locale variables must not choose languages either.
        languages = default_languages() if environment else ("en",)
        settings = settings.model_copy(
            update={"general": settings.general.model_copy(update={"languages": languages})}
        )
    return Loaded(settings, tuple(sources), tuple(warnings))


def _merge(merged: dict[str, dict[str, Any]], table: dict[str, Any]) -> None:
    for section, values in table.items():
        merged.setdefault(section, {}).update(values)


def printable(text: str) -> str:
    """Text safe to print on a terminal: keys and paths come from files we do not control.

    A quoted TOML key, or a folder name, can hold ESC and other controls that
    a terminal would run as escape sequences (ADR-048).
    """
    return "".join(char if char.isprintable() else "?" for char in text)[:200]


def user_config_path() -> Path:
    """Where the user's configuration file lives on this system."""
    return Path(platformdirs.user_config_dir("sugo", appauthor=False)) / "config.toml"


def default_languages() -> tuple[str, ...]:
    """The system's language, if Sugo has a pack for it, and English."""
    found = {"en"}
    system = system_language()
    if system is not None and system in PACKS:
        found.add(system)
    return tuple(sorted(found))


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as file:
            data = file.read(MAX_CONFIG_BYTES + 1)
    except OSError as error:
        raise ConfigError(_unreadable(printable(str(path)), error)) from None
    if len(data) > MAX_CONFIG_BYTES:
        raise ConfigError(
            _("{name}: larger than {size} KB").format(
                name=printable(str(path)), size=MAX_CONFIG_BYTES // 1024
            )
        )
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        # The position only: the decoder's message would quote the byte.
        raise ConfigError(
            _("{name}: not UTF-8 (byte {byte})").format(name=printable(str(path)), byte=error.start)
        ) from None
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        # The parser's message gives the line and column, not the content.
        # Truncated and made printable: it may quote key names from the file.
        # The parser's own words stay in English (ADR-052).
        raise ConfigError(
            _("{name}: not valid TOML ({detail})").format(
                name=printable(str(path)), detail=printable(str(error))
            )
        ) from None


def _project_layer(folder: Path, warnings: list[str]) -> tuple[Path, dict[str, Any]] | None:
    own = folder / "sugo.toml"
    if own.is_file():
        return own, _read_toml(own)
    pyproject = folder / "pyproject.toml"
    if not pyproject.is_file():
        return None
    try:
        table = _read_toml(pyproject)
    except ConfigError:
        # Another tool's file: a problem in it is not Sugo's to report as an error.
        warnings.append(
            _("{name}: not readable as TOML; [tool.sugo] ignored").format(
                name=printable(str(pyproject))
            )
        )
        return None
    tool = table.get("tool")
    sugo = tool.get("sugo") if isinstance(tool, dict) else None
    if sugo is None:
        return None
    if not isinstance(sugo, dict):
        raise ConfigError(
            _("{name}: [tool.sugo] must be a table").format(name=printable(str(pyproject)))
        )
    return pyproject, sugo


def _environment() -> dict[str, Any]:
    table: dict[str, dict[str, Any]] = {}
    for variable, (section, key) in ENVIRONMENT.items():
        raw = os.environ.get(variable)
        if raw is None or raw == "":
            continue
        value = _from_text(variable, key, raw.strip())
        # One at a time, so an error names the variable.
        _validate(variable, {section: {key: value}})
        table.setdefault(section, {})[key] = value
    return table


def _from_text(variable: str, key: str, raw: str) -> object:
    if key == "languages":
        return [part.strip() for part in raw.split(",") if part.strip()]
    if key == "strip_tracking_urls":
        if raw.lower() in _TRUE:
            return True
        if raw.lower() in _FALSE:
            return False
        raise ConfigError(_("{name}: expected true or false").format(name=variable))
    if key == "max_tokens":
        try:
            return int(raw)
        except ValueError:
            raise ConfigError(_("{name}: expected a whole number").format(name=variable)) from None
    return raw


def _without_reserved(name: str, table: dict[str, Any], warnings: list[str]) -> dict[str, Any]:
    kept: dict[str, Any] = {}
    for section, values in table.items():
        reserved = _RESERVED.get(section, frozenset())
        if reserved is None:
            warnings.append(
                _("{name}: [{section}] is not used in this version").format(
                    name=name, section=section
                )
            )
            continue
        if not isinstance(values, dict):
            raise ConfigError(
                _("{name}: {section} must be a table").format(name=name, section=printable(section))
            )
        later = sorted(set(values) & reserved)
        for key in later:
            warnings.append(
                _("{name}: {key} is not used in this version").format(
                    name=name, key=f"{section}.{key}"
                )
            )
        kept[section] = {key: value for key, value in values.items() if key not in reserved}
    return kept


def _validate(name: str, table: dict[str, Any]) -> Settings:
    try:
        return Settings.model_validate(table)
    except ValidationError as error:
        # The keys at fault and what is expected, never the values.
        problems = sorted(
            f"{printable('.'.join(map(str, item['loc'])))}: {_problem(item)}"
            for item in error.errors()
        )
        raise ConfigError(f"{name}: {'; '.join(problems)}") from None


def _unreadable(name: str, error: OSError) -> str:
    return _("{name}: cannot be read ({reason})").format(name=name, reason=os_reason(error))


def _problem(item: Any) -> str:
    """Pydantic's complaint about one key in the interface language; never the value."""
    kind = item["type"]
    context = item.get("ctx", {})
    if kind == "value_error":
        # Raised by our own validators, already translated.
        return str(context["error"])
    if kind == "literal_error":
        expected = str(context["expected"]).replace(" or ", ", ")
        return _("expected one of: {expected}").format(expected=expected)
    if kind == "greater_than_equal":
        return _("must be at least {minimum}").format(minimum=context["ge"])
    if kind == "less_than_equal":
        return _("must be at most {maximum}").format(maximum=context["le"])
    messages = {
        "extra_forbidden": _("unknown key"),
        "bool_type": _("expected true or false"),
        "int_type": _("expected a whole number"),
        "string_type": _("expected text"),
        "tuple_type": _("expected a list"),
        "model_type": _("must be a table"),
    }
    return messages.get(kind, str(item["msg"]))
