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
from functools import cache
from importlib import resources

from sugo.i18n.catalog import Translations, translations

# Interface languages; English is the source text and needs no catalog.
LANGUAGES = ("en", "it")
# "sugo" for Sugo's own text; "typer" for the text Typer marks for translation.
DOMAINS = ("sugo", "typer")

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


def N_(message: str) -> str:  # noqa: N802 - the name translation tools look for
    """Mark ``message`` for translation without translating it now."""
    return message


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
    if setting in LANGUAGES:
        return setting
    system = system_language()
    return system if system in LANGUAGES else "en"


def system_language() -> str | None:
    """The two-letter code of the system's language, if it names one."""
    for variable in ("LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(variable)
        if value and value not in ("C", "POSIX"):
            return value[:2].lower()
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
