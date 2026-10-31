"""Tests for interface languages: catalog reading, language choice and translation."""

import errno

import pytest

from sugo import i18n
from sugo.i18n.catalog import CatalogError, parse, translations

CATALOG = r"""
# A comment.
msgid ""
msgstr ""
"Language: it\n"

msgid "Hello"
msgstr "Ciao"

msgid ""
"A long "
"message\twith \"quotes\"\n"
msgstr "Un messaggio "
"lungo"

#, fuzzy
msgid "Draft"
msgstr "Bozza"

msgid "Empty"
msgstr ""

msgid "{count} page"
msgid_plural "{count} pages"
msgstr[0] "{count} pagina"
msgstr[1] "{count} pagine"
"""


def test_catalog_reads_lines_escapes_and_plurals() -> None:
    entries = parse(CATALOG)
    assert [entry.msgid for entry in entries] == [
        "",
        "Hello",
        'A long message\twith "quotes"\n',
        "Draft",
        "Empty",
        "{count} page",
    ]
    assert entries[0].msgstr == ["Language: it\n"]
    assert entries[3].fuzzy
    assert entries[5].msgstr == ["{count} pagina", "{count} pagine"]


def test_translations_skip_drafts_and_empty_messages() -> None:
    catalog = translations(CATALOG, "it")
    assert catalog.gettext("Hello") == "Ciao"
    assert catalog.gettext('A long message\twith "quotes"\n') == "Un messaggio lungo"
    assert catalog.gettext("Draft") == "Draft"
    assert catalog.gettext("Empty") == "Empty"
    assert catalog.gettext("Unknown") == "Unknown"
    assert catalog.gettext("") == ""


@pytest.mark.parametrize(("n", "expected"), [(0, "pagine"), (1, "pagina"), (2, "pagine")])
def test_plural_rule_comes_from_sugo_not_the_file(n: int, expected: str) -> None:
    # The file's Plural-Forms header is never evaluated (no exec, ADR-052).
    catalog = translations(CATALOG.replace('"Language: it\\n"', '"Plural-Forms: x\\n"'), "it")
    assert catalog.ngettext("{count} page", "{count} pages", n) == "{count} " + expected
    assert catalog.ngettext("one", "many", n) == ("one" if n == 1 else "many")


@pytest.mark.parametrize(
    "text",
    [
        'msgstr "orphan"',
        '"text outside a message"',
        'msgid "a"\nmsgtxt "b"',
        'msgid "a"',
        'msgid "a"\nmsgstr "b" junk',
        'msgid "a\\q"\nmsgstr "b"',
        'msgid "a"b"\nmsgstr "c"',
        'msgid "a"\nmsgid_plural "as"\nmsgstr "b"',
        'msgid "a"\nmsgid_plural "as"\nmsgstr[1] "b"',
        'msgid "a"\nmsgstr "b"\nmsgstr[x] "c"',
    ],
)
def test_malformed_catalogs_are_refused(text: str) -> None:
    with pytest.raises(CatalogError):
        parse(text)


def test_language_without_plural_rule_is_refused() -> None:
    with pytest.raises(CatalogError):
        translations(CATALOG, "xx")


def test_english_is_the_default_and_needs_no_catalog() -> None:
    assert i18n.active_language() == "en"
    assert i18n.gettext("Converting") == "Converting"
    assert i18n.ngettext("{count} page", "{count} pages", 2) == "{count} pages"


def test_activate_switches_every_domain() -> None:
    i18n.activate("it")
    assert i18n.active_language() == "it"
    assert i18n.gettext("Converting") == "Conversione in corso"
    assert i18n.ngettext("{count} page", "{count} pages", 1) == "{count} pagina"
    assert i18n.dgettext("typer", "Options") == "Opzioni"
    assert i18n.dngettext("typer", "one", "many", 2) == "many"
    i18n.activate("en")
    assert i18n.gettext("Converting") == "Converting"


def test_unknown_language_is_refused() -> None:
    with pytest.raises(ValueError, match="no interface language"):
        i18n.activate("xx")


@pytest.mark.parametrize(
    ("variables", "expected"),
    [
        ({"LANG": "it_IT.UTF-8"}, "it"),
        ({"LANG": "de_DE.UTF-8"}, "de"),
        ({"LC_MESSAGES": "it_IT", "LANG": "en_US"}, "it"),
        ({"LC_ALL": "es_ES", "LC_MESSAGES": "it_IT"}, "es"),
    ],
)
def test_system_language_follows_the_locale_variables(
    monkeypatch: pytest.MonkeyPatch, variables: dict[str, str], expected: str
) -> None:
    for name, value in variables.items():
        monkeypatch.setenv(name, value)
    assert i18n.system_language() == expected


@pytest.mark.parametrize(
    ("locale_name", "expected"),
    [("Italian_Italy", "it"), ("it_IT", "it"), (None, None)],
)
def test_system_language_falls_back_to_the_os_locale(
    monkeypatch: pytest.MonkeyPatch, locale_name: str | None, expected: str | None
) -> None:
    monkeypatch.setenv("LANG", "C")
    monkeypatch.setattr(i18n.locale, "getlocale", lambda: (locale_name, None))
    assert i18n.system_language() == expected


@pytest.mark.parametrize(
    ("setting", "lang", "expected"),
    [
        ("auto", "it_IT.UTF-8", "it"),
        ("auto", "de_DE.UTF-8", "en"),
        ("en", "it_IT.UTF-8", "en"),
        ("it", "de_DE.UTF-8", "it"),
    ],
)
def test_resolve_follows_the_system_only_for_auto(
    monkeypatch: pytest.MonkeyPatch, setting: str, lang: str, expected: str
) -> None:
    monkeypatch.setenv("LANG", lang)
    assert i18n.resolve(setting) == expected


def test_os_errors_are_explained_without_the_path() -> None:
    error = FileNotFoundError(errno.ENOENT, "No such file or directory", "secret/name.pdf")
    assert i18n.os_reason(error) == "no such file or folder"
    i18n.activate("it")
    assert i18n.os_reason(error) == "file o cartella inesistente"
    # An error Sugo has no words for keeps the system's, never the path.
    assert i18n.os_reason(OSError(errno.EIO, "I/O error", "secret")) == "I/O error"
    assert i18n.os_reason(OSError("no errno")) == "errore sconosciuto"
