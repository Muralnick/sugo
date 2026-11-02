"""Tests for the sugo command: output streams, exit codes, files written and error reports."""

import json
from io import BytesIO
from pathlib import Path
from types import MappingProxyType

import pymupdf
import pytest
from PIL import Image
from typer.testing import CliRunner, Result

from sugo.config.settings import Settings
from sugo.core import pipeline
from sugo.core.pipeline import Conversion, InputKind
from sugo.extractors.pymupdf.extract import PdfTooLargeError
from sugo.ports.cli import app as cli
from sugo.ports.cli import clipboard
from sugo.ports.errors import ExitCode
from sugo.storage.paths import CACHE_DIR_ENV


def report(pages: int = 3) -> bytes:
    """A PDF with native text, a running header and page numbers: no OCR needed."""
    document = pymupdf.open()
    for n in range(pages):
        page = document.new_page()
        page.insert_text((72, 40), "ACME Corporation - Annual Report 2026", fontsize=10)
        page.insert_text((72, 120), f"Section {n + 1} says something new.", fontsize=10)
        page.insert_text((290, 815), str(n + 1), fontsize=10)
    return document.tobytes()


EXPECTED = "\n\n".join(f"Section {n} says something new." for n in range(1, 4))


def blank_png() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (400, 200), "white").save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture(autouse=True)
def private_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(CACHE_DIR_ENV, str(tmp_path / "cache"))


@pytest.fixture
def workdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    folder = tmp_path / "work"
    folder.mkdir()
    (folder / "report.pdf").write_bytes(report())
    (folder / "notes.txt").write_text("not a document")
    monkeypatch.chdir(folder)
    return folder


def run(*args: str) -> Result:
    return CliRunner().invoke(cli.app, list(args))


def converted(**changes: object) -> Conversion:
    fields: dict[str, object] = {
        "markdown": "text",
        "kind": InputKind.PDF,
        "source": "report.pdf",
        "source_sha256": "a" * 64,
        "pages": 3,
        "failed_pages": (),
        "removed": MappingProxyType({}),
        "chunks": (),
        "sugo_version": "0.0.0",
        "config_hash": "b" * 64,
    }
    fields.update(changes)
    return Conversion(**fields)  # type: ignore[arg-type]


def test_version_and_help() -> None:
    assert run("--version").stdout.strip() == "0.0.0"
    help_text = run("--help").stdout
    for command in ("convert", "stats", "clip", "doctor"):
        assert command in help_text
    # Completion would edit the user's shell profile.
    assert "--install-completion" not in help_text
    # The usage line names the argument, not Typer's internal placeholder.
    convert_help = run("convert", "--help").stdout
    assert "FILE..." in convert_help
    assert "{files}" not in convert_help


@pytest.mark.usefixtures("workdir")
def test_file_converts_to_stdout() -> None:
    result = run("report.pdf")
    assert result.exit_code == ExitCode.OK
    assert result.stdout == EXPECTED + "\n"
    assert run("convert", "report.pdf").stdout == result.stdout


@pytest.mark.usefixtures("workdir")
def test_chunks_go_to_stdout_as_json_lines() -> None:
    result = run("report.pdf", "--chunks", "--max-tokens", "32")
    assert result.exit_code == ExitCode.OK
    records = [json.loads(line) for line in result.stdout.splitlines()]
    assert records
    assert {record["schema_version"] for record in records} == {"1.0"}
    assert {record["source"] for record in records} == {"report.pdf"}


def test_output_folder_gets_one_file_per_input_and_a_bad_file_is_partial(workdir: Path) -> None:
    result = run("report.pdf", "notes.txt", "-o", "out", "--chunks")
    assert result.exit_code == ExitCode.PARTIAL
    assert (workdir / "out" / "report.md").read_text(encoding="utf-8") == EXPECTED + "\n"
    assert (workdir / "out" / "report.jsonl").read_text(encoding="utf-8").startswith("{")
    assert not (workdir / "out" / "notes.md").exists()
    assert "report.pdf -> out/report.md, out/report.jsonl" in result.stderr
    assert "notes.txt: error INPUT_UNSUPPORTED" in result.stderr
    assert result.stdout == ""


def test_front_matter_records_the_provenance(workdir: Path) -> None:
    assert run("report.pdf", "-o", "out", "--front-matter").exit_code == ExitCode.OK
    text = (workdir / "out" / "report.md").read_text(encoding="utf-8")
    assert text.startswith('---\nsource: "report.pdf"\nsource_sha256: "')
    assert text.endswith(EXPECTED + "\n")


@pytest.mark.usefixtures("workdir")
def test_json_reports_every_document() -> None:
    result = run("report.pdf", "notes.txt", "-o", "out", "--json")
    assert result.exit_code == ExitCode.PARTIAL
    documents = json.loads(result.stdout)["documents"]
    assert documents[0]["status"] == "ok"
    assert documents[0]["outputs"] == ["out/report.md"]
    assert documents[0]["removed"] == {"headers_footers": 3, "page_numbers": 3}
    assert documents[1] == {
        "source": "notes.txt",
        "status": "error",
        "error": {
            "code": "INPUT_UNSUPPORTED",
            "message": "not a supported input: PDF, DOCX, PNG, JPEG, WEBP or XML expected",
            "hint": "Sugo reads PDF, DOCX, PNG, JPEG, WEBP and XML files.",
            "details": {},
        },
    }
    single = json.loads(run("report.pdf", "--json").stdout)["documents"][0]
    assert single["markdown"] == EXPECTED
    assert "chunks" not in single


@pytest.mark.usefixtures("workdir")
def test_only_failure_exits_with_its_own_code() -> None:
    result = run("notes.txt")
    assert result.exit_code == ExitCode.ERROR
    assert result.stdout == ""


@pytest.mark.usefixtures("workdir")
@pytest.mark.parametrize(
    "args",
    [
        ["report.pdf", "notes.txt"],  # Several files need -o.
        ["report.pdf", "--max-tokens", "64"],  # Needs --chunks.
        ["report.pdf", "--chunks", "--max-tokens", "8"],  # Below the minimum.
        ["."],  # Folders are not inputs in v0.1.
        ["report.pdf", "--chunks", "--front-matter"],  # Front matter needs Markdown.
        ["report.pdf", "--json", "--front-matter"],
    ],
)
def test_usage_errors_exit_with_2(args: list[str]) -> None:
    assert run(*args).exit_code == ExitCode.USAGE


def test_outputs_never_collide_nor_overwrite_inputs(workdir: Path) -> None:
    (workdir / "sub").mkdir()
    (workdir / "sub" / "Report.png").write_bytes(blank_png())
    assert run("report.pdf", "sub/Report.png", "-o", "out").exit_code == ExitCode.USAGE
    # A PDF named .md, converted into its own folder, would replace itself.
    (workdir / "paper.md").write_bytes(report())
    assert run("paper.md", "-o", ".").exit_code == ExitCode.USAGE
    assert (workdir / "paper.md").read_bytes().startswith(b"%PDF")


def test_missing_file_is_reported_without_stopping_the_others(workdir: Path) -> None:
    alone = run("missing.pdf")
    assert alone.exit_code == ExitCode.ERROR
    assert "missing.pdf: error FILE_UNREADABLE" in alone.stderr
    batch = run("missing.pdf", "report.pdf", "-o", "out")
    assert batch.exit_code == ExitCode.PARTIAL
    assert (workdir / "out" / "report.md").exists()


@pytest.mark.usefixtures("workdir")
def test_security_refusal_exits_with_4(monkeypatch: pytest.MonkeyPatch) -> None:
    def too_large(*args: object, **kwargs: object) -> Conversion:
        raise PdfTooLargeError("PDF file exceeds 10 bytes")

    monkeypatch.setattr(pipeline, "convert_file", too_large)
    result = run("report.pdf")
    assert result.exit_code == ExitCode.SECURITY
    assert "PDF_TOO_LARGE" in result.stderr
    assert "hint: Split the PDF" in result.stderr


@pytest.mark.usefixtures("workdir")
def test_unreadable_pages_make_the_run_partial(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pipeline, "convert_file", lambda *a, **k: converted(failed_pages=(2, 5)))
    result = run("report.pdf")
    assert result.exit_code == ExitCode.PARTIAL
    assert "report.pdf: pages 2, 5 could not be read" in result.stderr


@pytest.mark.usefixtures("workdir")
def test_interruption_exits_with_130(monkeypatch: pytest.MonkeyPatch) -> None:
    def interrupted(*args: object, **kwargs: object) -> Conversion:
        raise KeyboardInterrupt

    monkeypatch.setattr(pipeline, "convert_file", interrupted)
    assert run("report.pdf").exit_code == ExitCode.INTERRUPTED


@pytest.mark.usefixtures("workdir")
def test_unexpected_errors_are_not_swallowed(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*args: object, **kwargs: object) -> Conversion:
        raise RuntimeError("bug")

    monkeypatch.setattr(pipeline, "convert_file", broken)
    result = run("report.pdf")
    assert isinstance(result.exception, RuntimeError)
    assert result.exit_code == ExitCode.ERROR


@pytest.mark.usefixtures("workdir")
def test_missing_lite_level_exits_with_5(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "missing_lite_packages", lambda: ["rapidocr"])
    result = run("report.pdf")
    assert result.exit_code == ExitCode.MISSING
    assert "LEVEL_MISSING" in result.stderr
    assert 'pip install "sugo[lite]"' in result.stderr
    as_json = run("report.pdf", "--json")
    assert json.loads(as_json.stderr)["error"]["details"] == {"missing": ["rapidocr"]}
    assert as_json.stdout == ""


def test_names_are_shown_as_typed_never_as_markup(workdir: Path) -> None:
    (workdir / "[red]odd.txt").write_text("not a document")
    result = run("[red]odd.txt")
    assert "[red]odd.txt: error INPUT_UNSUPPORTED" in result.stderr


@pytest.mark.usefixtures("workdir")
def test_persistent_cache_is_used_unless_disabled(tmp_path: Path) -> None:
    database = tmp_path / "cache" / "cache.db"
    run("report.pdf", "--no-cache")
    assert not database.exists()
    run("report.pdf")
    assert database.exists()


# --- stats --------------------------------------------------------------------


@pytest.mark.usefixtures("workdir")
def test_stats_of_a_pdf_measure_the_cleaning() -> None:
    result = run("stats", "report.pdf", "--json")
    assert result.exit_code == ExitCode.OK
    stats = json.loads(result.stdout)
    assert (stats["kind"], stats["pages"], stats["images"]) == ("pdf", 3, [])
    text = stats["text"]
    assert text["baseline_tokens"] > text["result_tokens"] > 0
    assert text["saved_tokens"] == text["baseline_tokens"] - text["result_tokens"]
    human = run("stats", "report.pdf")
    assert human.stdout.startswith("report.pdf: pdf, 3 pages\nText before and after cleaning:")


def test_stats_of_an_image_compare_each_provider(workdir: Path) -> None:
    (workdir / "blank.png").write_bytes(blank_png())
    result = run("stats", "blank.png", "--provider", "claude", "--provider", "gemini", "--json")
    assert result.exit_code == ExitCode.OK
    images = json.loads(result.stdout)["images"]
    assert [image["provider"] for image in images] == ["claude", "gemini"]
    assert all(image["baseline_tokens"] > 0 for image in images)
    table = run("stats", "blank.png").stdout
    for provider in ("claude", "gemini", "openai"):
        assert provider in table


@pytest.mark.usefixtures("workdir")
def test_stats_refuse_unknown_providers() -> None:
    result = run("stats", "report.pdf", "--provider", "nobody")
    assert result.exit_code == ExitCode.USAGE


# --- clip ---------------------------------------------------------------------


def test_clip_converts_the_clipboard_image(workdir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data = blank_png()
    monkeypatch.setattr(clipboard, "read_clipboard_image", lambda: data)
    printed = run("clip")
    assert printed.exit_code == ExitCode.OK
    assert printed.stdout == ""  # A blank image has no text.
    written = run("clip", "-o", "out", "--json")
    document = json.loads(written.stdout)["documents"][0]
    assert document["source"] is None
    name = f"clip-{document['source_sha256'][:12]}.md"
    assert document["outputs"] == [f"out/{name}"]
    assert (workdir / "out" / name).exists()


@pytest.mark.usefixtures("workdir")
def test_clip_with_no_image_explains_what_to_do(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("PIL.ImageGrab.grabclipboard", lambda: None)
    result = run("clip")
    assert result.exit_code == ExitCode.ERROR
    assert "CLIPBOARD_NO_IMAGE" in result.stderr


# --- doctor -------------------------------------------------------------------


def test_doctor_reports_every_check() -> None:
    result = run("doctor", "--json")
    checks = {check["name"]: check for check in json.loads(result.stdout)["checks"]}
    assert set(checks) == {
        "sugo",
        "python",
        "cpus",
        "level lite",
        "ocr models",
        "pymupdf",
        "tokenizer",
        "config",
        "cache",
        "clipboard",
    }
    assert checks["ocr models"]["status"] == "ok"
    assert checks["tokenizer"]["status"] == "ok"
    assert result.exit_code == ExitCode.OK
    assert "level lite" in run("doctor").stdout


def test_doctor_fails_when_a_check_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    from sugo.ports.cli import doctor

    monkeypatch.setattr(doctor, "missing_lite_packages", lambda: ["onnxruntime"])
    result = run("doctor", "--json")
    assert result.exit_code == ExitCode.ERROR
    checks = {check["name"]: check for check in json.loads(result.stdout)["checks"]}
    assert checks["level lite"]["status"] == "error"
    assert "ocr models" not in checks


def test_source_is_the_path_as_typed_normalised_never_absolute(workdir: Path) -> None:
    document = json.loads(run("./report.pdf", "--json").stdout)["documents"][0]
    assert document["source"] == "report.pdf"
    # A file named like a command is reached with a path.
    (workdir / "stats").write_bytes(report())
    converted_file = json.loads(run("./stats", "--json").stdout)["documents"][0]
    assert (converted_file["source"], converted_file["status"]) == ("stats", "ok")


def tracked_report() -> bytes:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 120), "See https://a.it/p?id=7&utm_source=mail now.", fontsize=10)
    return document.tobytes()


def test_configuration_file_changes_the_conversion(workdir: Path) -> None:
    (workdir / "links.pdf").write_bytes(tracked_report())
    assert "utm_source" not in run("links.pdf").stdout
    (workdir / "sugo.toml").write_text("[cleaning]\nstrip_tracking_urls = false\n")
    assert "utm_source=mail" in run("links.pdf").stdout


def test_option_overrides_configured_chunk_size(workdir: Path) -> None:
    def config_hash(*args: str) -> str:
        return str(
            json.loads(run("report.pdf", "--chunks", *args).stdout.splitlines()[0])["config_hash"]
        )

    default = config_hash()
    (workdir / "sugo.toml").write_text("[chunking]\nmax_tokens = 40\n")
    # The chunk size is part of the config hash every chunk records.
    assert config_hash() == config_hash("--max-tokens", "40") != default
    assert config_hash("--max-tokens", "512") == default


def test_invalid_configuration_stops_with_usage_exit(workdir: Path) -> None:
    (workdir / "sugo.toml").write_text('[storage]\ncache = "disk"\n')
    result = run("report.pdf", "--json")
    assert result.exit_code == ExitCode.USAGE
    error = json.loads(result.stderr)["error"]
    assert error["code"] == "CONFIG_INVALID"
    assert "storage.cache" in error["message"]
    assert result.stdout == ""


def test_reserved_keys_warn_and_convert(workdir: Path) -> None:
    (workdir / "sugo.toml").write_text("[privacy]\noffline = true\n")
    result = run("report.pdf")
    assert result.exit_code == ExitCode.OK
    assert "not used in this version" in result.stderr


def test_ephemeral_cache_leaves_nothing_on_disk(
    workdir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SUGO_CACHE", "ephemeral")
    assert run("report.pdf").exit_code == ExitCode.OK
    assert not (tmp_path / "cache").exists()


def test_mcp_ignores_project_file_and_environment(
    workdir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sugo.ports.mcp import server

    (workdir / "sugo.toml").write_text("[cleaning]\nstrip_tracking_urls = false\n")
    monkeypatch.setenv("SUGO_LANGUAGES", "de")
    monkeypatch.setenv("LANG", "it_IT.UTF-8")  # the locale does not choose either
    seen: list[Settings] = []
    monkeypatch.setattr(server, "serve", lambda roots, settings: seen.append(settings))
    assert run("mcp", "--root", str(workdir)).exit_code == ExitCode.OK
    assert [(s.languages, s.cleaning.strip_tracking_urls) for s in seen] == [(("en",), True)]


def test_doctor_reports_an_invalid_configuration(workdir: Path) -> None:
    (workdir / "sugo.toml").write_text("[clening]\n")
    result = run("doctor", "--json")
    checks = {check["name"]: check for check in json.loads(result.stdout)["checks"]}
    assert checks["config"]["status"] == "error"
    assert result.exit_code == ExitCode.ERROR


def test_json_mode_keeps_stderr_parseable_with_warnings(workdir: Path) -> None:
    (workdir / "sugo.toml").write_text("[privacy]\noffline = true\n")
    result = run("missing.pdf", "--json")
    assert result.exit_code == ExitCode.ERROR
    assert "warning" not in result.stderr


def test_configuration_errors_never_reach_the_terminal_as_escapes(workdir: Path) -> None:
    (workdir / "sugo.toml").write_text('[general]\n"\\u001b]0;PWNED\\u0007" = 1\n')
    result = run("report.pdf")
    assert result.exit_code == ExitCode.USAGE
    assert "\x1b" not in result.stderr
    assert "\x07" not in result.stderr


def test_too_large_chunk_size_is_refused(workdir: Path) -> None:
    assert run("report.pdf", "--chunks", "--max-tokens", "100000").exit_code == ExitCode.USAGE
