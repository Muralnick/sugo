"""Interface languages: English in the code, other languages from catalogs (ADR-024, ADR-052).

Interface text is written in English and marked where it is written:
``_("...")`` (``gettext``) translates it at once, ``N_("...")`` only marks
text that is translated later, such as help texts built when a module is
imported, and ``ngettext`` picks a plural form. Placeholders use
``str.format`` and are filled after translation.

The active language is process-wide and English by default. Only the CLI
switches it, so the Python API, ``--json`` output and the MCP server always
speak English. Error codes, JSON keys and log messages are never translated.
"""

import errno
import gettext as _gettext
import locale
import os
import sys
from functools import cache
from importlib import resources

from sugo.i18n.catalog import Translations, translations

# Interface languages; English is the source text and needs no catalog.
LANGUAGES = ("en", "it")
# "sugo" for Sugo's own text; "typer" for the text Typer marks for translation.
DOMAINS = ("sugo", "typer")

# Windows language ids: the low ten bits name the language (LANGID primary
# language), e.g. 0x0410 Italian (Italy) and 0x0810 Italian (Switzerland).
_WINDOWS_PRIMARY_LANGUAGE = 0x3FF
_WINDOWS_LANGUAGES = {0x09: "en", 0x10: "it"}

_NO_LOCALE = ("C", "POSIX")

_ENGLISH = _gettext.NullTranslations()
_active_language = "en"
_active: dict[str, _gettext.NullTranslations] = {}


def gettext(message: str) -> str:
    """``message`` in the active language."""
    return _active.get("sugo", _ENGLISH).gettext(message)


def ngettext(singular: str, plural: str, n: int) -> str:
    """The form of a message for ``n`` things, in the active language."""
    return _active.get("sugo", _ENGLISH).ngettext(singular, plural, n)


def dgettext(domain: str, message: str) -> str:
    """``message`` from another domain's catalog, in the active language."""
    return _active.get(domain, _ENGLISH).gettext(message)


def dngettext(domain: str, singular: str, plural: str, n: int) -> str:
    """The form for ``n`` things from another domain's catalog."""
    return _active.get(domain, _ENGLISH).ngettext(singular, plural, n)


def translate(language: str, message: str) -> str:
    """``message`` in ``language``, whatever the active language.

    For text shown in several languages at once, such as the web page's;
    it switches nothing process-wide.

    Raises:
        ValueError: If Sugo has no interface in that language.
    """
    if language not in LANGUAGES:
        raise ValueError(f"no interface language {language!r}")
    return message if language == "en" else _catalog(language, "sugo").gettext(message)


def N_(message: str) -> str:  # noqa: N802 - the name translation tools look for
    """Mark ``message`` for translation without translating it now."""
    return message


# The interface languages' names, translated where they are shown.
LANGUAGE_NAMES = {"en": N_("English"), "it": N_("Italian")}


def activate(language: str) -> None:
    """Make ``language`` the interface language of this process.

    Raises:
        ValueError: If Sugo has no interface in that language.
    """
    global _active_language, _active
    if language not in LANGUAGES:
        raise ValueError(f"no interface language {language!r}")
    _active = {} if language == "en" else {domain: _catalog(language, domain) for domain in DOMAINS}
    _active_language = language


def active_language() -> str:
    """The interface language of this process."""
    return _active_language


def resolve(setting: str) -> str:
    """The language for a ``ui.language`` setting: ``auto`` follows the system."""
    return setting if setting in LANGUAGES else detect_language()[0]


def detect_language() -> tuple[str, str]:
    """The interface language for ``auto``, and where it comes from (ADR-052).

    Another language than English only on a clear signal: a locale variable,
    or the language of Windows' own menus. Without one, or for a language
    Sugo has no interface in, English. The Windows regional format (dates,
    numbers) is not used: it is often Italian on an English Windows.

    Returns:
        The language and its source: the variable's name (``LC_ALL``,
        ``LC_MESSAGES``, ``LANG``), ``windows``, or ``none`` without a signal.
    """
    found = _locale_variable()
    if found is not None:
        variable, value = found
        # "C" and "POSIX" ask for no localisation at all: English.
        code = "en" if value in _NO_LOCALE else value[:2].lower()
        return (code if code in LANGUAGES else "en"), variable
    windows = _windows_display_language()
    if windows is not None:
        return windows, "windows"
    return "en", "none"


def _locale_variable() -> tuple[str, str] | None:
    """The first locale variable set, as POSIX reads them: its name and value."""
    for variable in ("LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(variable)
        if value:
            return variable, value
    return None


def _windows_display_language() -> str | None:
    """The language of Windows' menus, if Sugo has its interface; None elsewhere."""
    if sys.platform != "win32":
        return None
    import ctypes

    try:
        # Takes nothing and changes nothing: it returns the user's display language id.
        language_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
    except (AttributeError, OSError):
        return None
    return _WINDOWS_LANGUAGES.get(int(language_id) & _WINDOWS_PRIMARY_LANGUAGE, "en")


def system_language() -> str | None:
    """The two-letter code of the system's language, if it names one.

    For the default languages of documents (ADR-051), where the regional
    format is a fair hint; the interface uses ``detect_language``.
    """
    found = _locale_variable()
    if found is not None and found[1] not in _NO_LOCALE:
        return found[1][:2].lower()
    name = locale.getlocale()[0]
    if not name:
        return None
    # Windows names locales in English: "Italian_Italy".
    names = {"italian": "it", "spanish": "es", "french": "fr", "german": "de", "english": "en"}
    return names.get(name.split("_")[0].lower(), name[:2].lower())


def os_reason(error: OSError) -> str:
    """Why a file operation failed, in the active language, without the path.

    English keeps the operating system's own words, as before translations
    existed (``--json`` output does not change); other languages get Sugo's.
    ``str(error)`` is never used: it repeats the path, which callers show
    separately.
    """
    if _active_language == "en" and error.strerror:
        return error.strerror
    reasons = {
        errno.ENOENT: N_("no such file or folder"),
        errno.EACCES: N_("permission denied"),
        errno.EPERM: N_("permission denied"),
        errno.EISDIR: N_("it is a folder"),
        errno.ENOTDIR: N_("a part of the path is not a folder"),
        errno.ENOSPC: N_("no space left on the disk"),
        errno.EROFS: N_("the disk is read-only"),
        errno.EEXIST: N_("it already exists"),
        errno.ENAMETOOLONG: N_("the name is too long"),
    }
    reason = reasons.get(error.errno) if error.errno is not None else None
    if reason is not None:
        return gettext(reason)
    return error.strerror or gettext("unknown error")


@cache
def _catalog(language: str, domain: str) -> Translations:
    text = (
        resources.files("sugo.i18n")
        .joinpath("locales", language, f"{domain}.po")
        .read_text(encoding="utf-8")
    )
    return translations(text, language)
