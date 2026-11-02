"""Read gettext ``.po`` catalogs into translations, without compiling them (ADR-052).

The standard library reads only compiled ``.mo`` files, and its reader turns
the catalog's ``Plural-Forms`` header into Python code with ``exec``. Sugo
ships the ``.po`` text instead, which can be reviewed and is the format
translation tools such as Weblate edit, and takes the plural rule of each
language from ``PLURAL_RULES`` below, never from the file.

Only the subset of the format Sugo's catalogs use is read: ``msgid``,
``msgid_plural``, ``msgstr`` and ``msgstr[N]``, strings continued on the next
lines, comments and the ``fuzzy`` flag. Anything else is an error: the
catalogs ship with Sugo, so a malformed one is a bug the tests catch.
"""

import gettext
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

# Plural rules from the CLDR, per language: which form ``ngettext`` picks for n.
PLURAL_RULES: dict[str, Callable[[int], int]] = {
    "it": lambda n: 0 if n == 1 else 1,
}
_ESCAPES = {"n": "\n", "t": "\t", '"': '"', "\\": "\\"}


class CatalogError(ValueError):
    """A catalog does not follow the format Sugo reads."""


@dataclass
class Entry:
    """One message of a catalog."""

    msgid: str
    msgid_plural: str | None = None
    msgstr: list[str] = field(default_factory=list)
    fuzzy: bool = False
    line: int = 0


class Translations(gettext.NullTranslations):
    """Translations from one parsed catalog; untranslated messages stay in English."""

    def __init__(self, entries: list[Entry], plural: Callable[[int], int]) -> None:
        super().__init__()
        self._plural = plural
        self._singular: dict[str, str] = {}
        self._plurals: dict[str, list[str]] = {}
        for entry in entries:
            # The header has an empty msgid; fuzzy entries are drafts, as in GNU gettext.
            if not entry.msgid or entry.fuzzy or not all(entry.msgstr):
                continue
            if entry.msgid_plural is None:
                self._singular[entry.msgid] = entry.msgstr[0]
            else:
                self._plurals[entry.msgid] = entry.msgstr

    def gettext(self, message: str) -> str:
        return self._singular.get(message, message)

    def ngettext(self, msgid1: str, msgid2: str, n: int) -> str:
        forms = self._plurals.get(msgid1)
        if forms is None:
            return msgid1 if n == 1 else msgid2
        return forms[min(self._plural(n), len(forms) - 1)]


def translations(text: str, language: str) -> Translations:
    """Parse a catalog for ``language``.

    Raises:
        CatalogError: If the text is not a catalog Sugo can read, or Sugo has
            no plural rule for the language.
    """
    if language not in PLURAL_RULES:
        raise CatalogError(f"no plural rule for language {language!r}")
    return Translations(parse(text), PLURAL_RULES[language])


def parse(text: str) -> list[Entry]:
    """The entries of a ``.po`` catalog, in file order.

    Raises:
        CatalogError: If a line does not follow the format.
    """
    entries: list[Entry] = []
    current: Entry | None = None
    # The field that continuation lines extend: ("msgid" | "msgid_plural" | "msgstr", index).
    target: tuple[str, int] | None = None
    fuzzy = False
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            if line.startswith("#,") and "fuzzy" in line[2:].replace(",", " ").split():
                fuzzy = True
            continue
        keyword, _, rest = line.partition(" ")
        if line.startswith('"'):
            if current is None or target is None:
                raise CatalogError(f"line {number}: text outside a message")
            _extend(current, target, _unquote(line, number))
            continue
        value = _unquote(rest.strip(), number)
        if keyword == "msgid":
            if current is not None:
                entries.append(_checked(current))
            current = Entry(msgid=value, fuzzy=fuzzy, line=number)
            target = ("msgid", 0)
            fuzzy = False
        elif current is None:
            raise CatalogError(f"line {number}: {keyword} before msgid")
        elif keyword == "msgid_plural":
            current.msgid_plural = value
            target = ("msgid_plural", 0)
        elif keyword == "msgstr":
            current.msgstr = [value]
            target = ("msgstr", 0)
        elif keyword.startswith("msgstr[") and keyword.endswith("]"):
            index = _index(keyword, number)
            if index != len(current.msgstr):
                raise CatalogError(f"line {number}: plural forms out of order")
            current.msgstr.append(value)
            target = ("msgstr", index)
        else:
            raise CatalogError(f"line {number}: unknown keyword")
    if current is not None:
        entries.append(_checked(current))
    return entries


def _extend(entry: Entry, target: tuple[str, int], text: str) -> None:
    name, index = target
    if name == "msgid":
        entry.msgid += text
    elif name == "msgid_plural":
        entry.msgid_plural = (entry.msgid_plural or "") + text
    else:
        entry.msgstr[index] += text


def _checked(entry: Entry) -> Entry:
    if not entry.msgstr:
        raise CatalogError(f"line {entry.line}: message without msgstr")
    if (entry.msgid_plural is None) != (len(entry.msgstr) == 1):
        raise CatalogError(f"line {entry.line}: plural forms do not match msgid_plural")
    return entry


def _index(keyword: str, number: int) -> int:
    digits = keyword[len("msgstr[") : -1]
    if not digits.isdigit():
        raise CatalogError(f"line {number}: bad plural index")
    return int(digits)


def _unquote(quoted: str, number: int) -> str:
    """The text of a C-style quoted string, with the escapes ``.po`` files use."""
    if not (len(quoted) >= len('""') and quoted.startswith('"') and quoted.endswith('"')):
        raise CatalogError(f"line {number}: expected a quoted string")
    return "".join(_unescaped(quoted[1:-1], number))


def _unescaped(body: str, number: int) -> Iterator[str]:
    chars = iter(body)
    for char in chars:
        if char == '"':
            raise CatalogError(f"line {number}: unescaped quote")
        if char != "\\":
            yield char
            continue
        escape = next(chars, "")
        if escape not in _ESCAPES:
            raise CatalogError(f"line {number}: unknown escape")
        yield _ESCAPES[escape]
