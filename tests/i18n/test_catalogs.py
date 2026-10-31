"""The shipped catalogs are complete, current and safe to print (ADR-024, ADR-052).

The marked text is found in the sources as ``xgettext`` would find it: Sugo
marks text with ``_``, ``N_``, ``gettext`` and ``ngettext``, Typer with ``_``.
A call whose arguments are not literal strings is listed apart: it translates
text marked somewhere else.
"""

import ast
import re
import string
from collections.abc import Iterable
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

import pytest
import typer

import sugo
from sugo.i18n import DOMAINS, LANGUAGES
from sugo.i18n.catalog import Entry, parse

SINGULAR = frozenset({"_", "N_", "gettext"})
PLURAL = frozenset({"ngettext"})


@dataclass
class Found:
    """The messages of some sources: singular msgids and (singular, plural) pairs."""

    singular: set[str] = field(default_factory=set)
    plural: set[tuple[str, str]] = field(default_factory=set)
    # "file:line" of marking calls whose arguments are not literal strings.
    dynamic: list[str] = field(default_factory=list)


def find(paths: Iterable[Path], *, names: frozenset[str] = SINGULAR | PLURAL) -> Found:
    """The messages marked in ``paths`` by calls to bare ``names``."""
    found = Found()
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in names
            ):
                continue
            count = 2 if node.func.id in PLURAL else 1
            texts = [
                arg.value
                for arg in node.args[:count]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
            ]
            if len(texts) != count:
                found.dynamic.append(f"{path.name}:{node.lineno}")
            elif count == 1:
                found.singular.add(texts[0])
            else:
                found.plural.add((texts[0], texts[1]))
    return found


TRANSLATED = [language for language in LANGUAGES if language != "en"]
# Rich markup Typer puts in its own messages, e.g. "[blue]...[/]".
_MARKUP = re.compile(r"\[/?(?:blue|bold|dim|red|green|yellow)?\]")


def _entries(language: str, domain: str) -> list[Entry]:
    text = (
        resources.files("sugo.i18n")
        .joinpath("locales", language, f"{domain}.po")
        .read_text(encoding="utf-8")
    )
    return [entry for entry in parse(text) if entry.msgid]


def _ids(entries: list[Entry]) -> tuple[set[str], set[tuple[str, str]]]:
    singular = {entry.msgid for entry in entries if entry.msgid_plural is None}
    plural = {(entry.msgid, entry.msgid_plural) for entry in entries if entry.msgid_plural}
    return singular, plural


def _placeholders(text: str) -> list[str]:
    fields = sorted(
        f"{{{name}{'!' + conversion if conversion else ''}{':' + spec if spec else ''}}}"
        for _, name, spec, conversion in string.Formatter().parse(text)
        if name is not None
    )
    return fields + sorted(_MARKUP.findall(text))


@pytest.mark.parametrize("language", TRANSLATED)
def test_sugo_catalog_matches_the_marked_text(language: str) -> None:
    source = Path(sugo.__file__).parent
    found = find(sorted(source.rglob("*.py")))
    singular, plural = _ids(_entries(language, "sugo"))
    assert sorted(found.singular - singular) == [], "marked in the code, missing in the catalog"
    assert sorted(singular - found.singular) == [], "in the catalog, no longer in the code"
    assert found.plural == plural


def test_only_gettext_translates_text_marked_elsewhere() -> None:
    # _, N_ and ngettext take literal text, so the catalogs can be checked.
    source = Path(sugo.__file__).parent
    found = find(sorted(source.rglob("*.py")), names=frozenset({"_", "N_", "ngettext"}))
    assert found.dynamic == []


@pytest.mark.parametrize("language", TRANSLATED)
def test_typer_catalog_matches_what_typer_marks(language: str) -> None:
    # An upgrade of Typer that changes its text fails here, not on a user's screen.
    found = find(sorted(Path(typer.__file__).parent.rglob("*.py")), names=frozenset({"_"}))
    singular, plural = _ids(_entries(language, "typer"))
    assert singular == found.singular
    assert plural == set()


@pytest.mark.parametrize("domain", DOMAINS)
@pytest.mark.parametrize("language", TRANSLATED)
def test_translations_keep_placeholders_and_markup(language: str, domain: str) -> None:
    for entry in _entries(language, domain):
        assert not entry.fuzzy, entry.msgid
        sources = [entry.msgid] + ([entry.msgid_plural] if entry.msgid_plural else [])
        # Plural forms beyond the second follow the plural msgid.
        for index, translation in enumerate(entry.msgstr):
            assert translation, entry.msgid
            source_text = sources[min(index, len(sources) - 1)]
            assert _placeholders(translation) == _placeholders(source_text), entry.msgid


@pytest.mark.parametrize("domain", DOMAINS)
@pytest.mark.parametrize("language", TRANSLATED)
def test_translations_are_printable(language: str, domain: str) -> None:
    # The catalogs reach the terminal: no escape sequences, only text and layout.
    for entry in _entries(language, domain):
        for translation in entry.msgstr:
            assert all(char.isprintable() or char in "\n\t" for char in translation)
