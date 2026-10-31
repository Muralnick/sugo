"""Tests for the CLI's interface language: Italian help, messages and usage errors (ADR-052)."""

import ast
import json
import re
from pathlib import Path

import pytest
import typer.rich_utils
from typer.testing import CliRunner, Result

from sugo.core.constants import CHUNK_MAX_TOKENS, MAX_PDF_PAGES
from sugo.extractors.pymupdf.extract import _refusal
from sugo.extractors.pymupdf.guard import PAGES_REFUSAL
from sugo.extractors.pymupdf.protocol import Refused
from sugo.ports.cli import app as cli
from sugo.ports.cli.translation import (
    TYPER_CONSTANTS,
    USAGE_ERRORS,
    translate_usage_error,
    use_language,
)
from sugo.ports.errors import ExitCode
from sugo.storage.paths import CACHE_DIR_ENV


@pytest.fixture(autouse=True)
def italian(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(CACHE_DIR_ENV, str(tmp_path / "cache"))
    # Wide enough that Rich does not wrap the help columns.
    monkeypatch.setenv("COLUMNS", "200")
    monkeypatch.chdir(tmp_path)
    (tmp_path / "notes.txt").write_text("not a document")
    use_language("it")


def run(*args: str) -> Result:
    return CliRunner().invoke(cli.app, list(args))


def flat(text: str) -> str:
    """Text without Rich's colours, frames and line wrapping.

    Rich colours its output where it detects CI, e.g. GitHub Actions.
    """
    plain = re.sub(r"\x1b\[[0-9;]*m", "", text)
    return " ".join(plain.translate(str.maketrans("", "", "│|┌┐└┘╭╮╰╯─+")).split())


def test_help_is_italian() -> None:
    result = run("--help")
    assert result.exit_code == ExitCode.OK
    root = flat(result.stdout)
    for text in ("Uso: sugo", "Opzioni", "Comandi", "Mostra questo messaggio ed esci."):
        assert text in root
    assert "Documenti, ridotti" in root
    convert = flat(run("convert", "--help").stdout)
    for text in ("Argomenti", "File PDF, PNG, JPEG, WEBP o XML.", "[obbligatorio]"):
        assert text in convert
    assert "Dimensione dei chunk in token." in convert


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (["convert", "--bogus", "a.pdf"], "L'opzione --bogus non esiste"),
        (["convert"], "Argomento mancante 'FILE...'."),
        (
            ["convert", "--chunks", "--max-tokens", "5", "a.pdf"],
            "Valore non valido per '--max-tokens': 5 non è nell'intervallo",
        ),
        (
            ["convert", "--chunks", "--max-tokens", "many", "a.pdf"],
            "Valore non valido per '--max-tokens': 'many' non è un numero intero valido.",
        ),
        (["stats", "missing.pdf"], "File 'missing.pdf': non esiste."),
        (["stats", "notes.txt", "b.pdf"], "Argomenti in più non previsti (b.pdf)"),
        (["convert", "--output"], "L'opzione '--output' richiede un argomento."),
        (["convert", "a.pdf", "b.pdf"], "più file richiedono una cartella di uscita"),
    ],
)
def test_usage_errors_are_italian(args: list[str], expected: str) -> None:
    result = run(*args)
    assert result.exit_code == ExitCode.USAGE
    assert expected in flat(result.stderr)


def test_usage_line_is_italian() -> None:
    assert "Uso: sugo convert [OPTIONS] {FILE...} Prova 'sugo convert --help'" in flat(
        run("convert").stderr
    )


def test_errors_and_hints_are_italian() -> None:
    result = run("notes.txt")
    assert result.exit_code == ExitCode.ERROR
    assert result.stderr == (
        "notes.txt: errore INPUT_UNSUPPORTED: formato non supportato: attesi PDF, PNG, "
        "JPEG, WEBP o XML\n  suggerimento: Sugo legge file PDF, PNG, JPEG, WEBP e XML.\n"
    )


def test_json_output_stays_english() -> None:
    result = run("--json", "notes.txt")
    error = json.loads(result.stdout)["documents"][0]["error"]
    assert error == {
        "code": "INPUT_UNSUPPORTED",
        "message": "not a supported input: PDF, PNG, JPEG, WEBP or XML expected",
        "hint": "Sugo reads PDF, PNG, JPEG, WEBP and XML files.",
        "details": {},
    }
    doctor = json.loads(run("doctor", "--json").stdout)
    assert {check["name"] for check in doctor["checks"]} >= {"tokenizer", "config", "cache"}
    assert all("verificato" not in check["detail"] for check in doctor["checks"])


def test_doctor_table_is_italian() -> None:
    result = run("doctor")
    assert "configurazione" in result.stdout
    assert "o200k_base, SHA-256 verificato" in result.stdout


def test_configuration_chooses_the_language(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUGO_UI_LANGUAGE", "it")
    assert cli._ui_language(["convert"]) == "it"
    monkeypatch.setenv("SUGO_UI_LANGUAGE", "en")
    monkeypatch.setenv("LANG", "it_IT.UTF-8")
    assert cli._ui_language([]) == "en"
    monkeypatch.setenv("SUGO_UI_LANGUAGE", "auto")
    assert cli._ui_language([]) == "it"


def test_invalid_configuration_falls_back_to_the_system_language(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SUGO_UI_LANGUAGE", "klingon")
    monkeypatch.setenv("LANG", "it_IT.UTF-8")
    assert cli._ui_language(["convert"]) == "it"


def test_mcp_server_is_always_english(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUGO_UI_LANGUAGE", "it")
    # The project file in the agent's folder is not even read.
    (tmp_path / "sugo.toml").write_text("not = [valid")
    assert cli._ui_language(["mcp", "--root", "."]) == "en"


# English as Typer 0.27 words each message, one per pattern of the table.
TYPER_MESSAGES = [
    "Invalid value for '-o': it is wrong",
    "Invalid value: it is wrong",
    "Missing argument 'FILE...'.",
    "Missing option '--root'.",
    "Missing parameter.",
    "No such option: --chunk (Possible options: --chunks)",
    "No such option: --bogus",
    "Got unexpected extra argument(s) (b.pdf c.pdf)",
    "Option '--json' does not take a value.",
    "Option '-o' requires an argument.",
    "Option '-o' requires 2 arguments.",
    "Argument 'files' takes 2 values.",
    "2 values are required, but 1 given.",
    "'x' is not a valid integer.",
    "'x' is not a valid float.",
    "5 is not in the range 32<=x<=8192.",
    "'x' is not a valid boolean. Recognized values: 0, 1",
    "'x' is not one of 'a', 'b'.",
    "File 'a.pdf' does not exist.",
    "File 'a.pdf' is a file.",
    "Directory 'out' is a directory.",
    "Path 'a.pdf' is not readable.",
    "Path 'out' is not writable.",
    "Value must be an iterable.",
]


def test_every_pattern_has_a_message_and_translates_it() -> None:
    assert len(TYPER_MESSAGES) == len(USAGE_ERRORS)
    for (pattern, _, _), message in zip(USAGE_ERRORS, TYPER_MESSAGES, strict=True):
        assert pattern.fullmatch(message), message
        assert translate_usage_error(message) != message


def test_nested_messages_and_words_are_translated() -> None:
    assert translate_usage_error("Invalid value for 'file': File 'a.pdf' does not exist.") == (
        "Valore non valido per 'file': File 'a.pdf': non esiste."
    )
    assert translate_usage_error("Directory 'out' is a file.") == "Cartella 'out': è un file."


def test_user_input_is_never_a_format_string() -> None:
    message = "Invalid value for '--max-tokens': '{0.__class__}' is not a valid integer."
    assert translate_usage_error(message) == (
        "Valore non valido per '--max-tokens': '{0.__class__}' non è un numero intero valido."
    )


def test_unknown_messages_stay_as_they_are() -> None:
    assert translate_usage_error("Something new in Typer 0.28.") == ("Something new in Typer 0.28.")
    use_language("en")
    assert translate_usage_error("No such option: --bogus") == "No such option: --bogus"


def test_typer_constants_are_the_ones_typer_translates() -> None:
    # A renamed or reworded constant would otherwise stay English in silence.
    source = Path(typer.rich_utils.__file__).read_text(encoding="utf-8")
    marked = {
        node.targets[0].id: node.value.args[0].value
        for node in ast.parse(source).body
        if isinstance(node, ast.Assign)
        and isinstance(node.targets[0], ast.Name)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id == "_"
        and isinstance(node.value.args[0], ast.Constant)
    }
    assert marked == TYPER_CONSTANTS


def test_help_shows_the_chunk_size_default() -> None:
    # Brackets inside a help text would be eaten as Rich markup: Typer shows it.
    expected = f"[predefinito: (chunking.max_tokens, {CHUNK_MAX_TOKENS})]"
    assert expected in flat(run("convert", "--help").stdout)


def test_page_count_refusal_is_translated_and_only_when_recognised() -> None:
    too_many = Refused(code="PDF_TOO_LARGE", message=PAGES_REFUSAL.format(pages=MAX_PDF_PAGES))
    assert str(_refusal(too_many)) == f"il PDF ha più di {MAX_PDF_PAGES} pagine"
    # Any other text from the worker is data: looked up, never formatted.
    other = Refused(code="PDF_TOO_LARGE", message="the PDF has more than {pages} pages")
    assert str(_refusal(other)) == "il PDF ha più di {pages} pagine"
    unknown = Refused(code="PDF_INVALID", message="{0.__class__} something new")
    assert str(_refusal(unknown)) == "{0.__class__} something new"
