"""Tests for the interactive shell (ADR-062).

The shell is driven with ``run_shell(lines=...)``, which replaces the keyboard,
so every command runs end to end through the real CLI code.
"""

import json
import os
import re
import sys
from pathlib import Path

import pymupdf
import pytest
from typer.testing import CliRunner

from sugo import i18n
from sugo.ports.cli import app as cli
from sugo.ports.cli import shell
from sugo.ports.cli.doctor import Check, Status
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


@pytest.fixture
def workdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv(CACHE_DIR_ENV, str(tmp_path / "cache"))
    folder = tmp_path / "work"
    folder.mkdir()
    (folder / "my report [draft].pdf").write_bytes(report())
    (folder / "second.pdf").write_bytes(report())
    monkeypatch.chdir(folder)
    return folder


def plain(text: str) -> str:
    """Text without colours, as Rich may add them in CI."""
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def run(capsys: pytest.CaptureFixture[str], *lines: str) -> str:
    shell.run_shell(lines=[*lines, "/exit"])
    captured = capsys.readouterr()
    return plain(captured.out + captured.err)


# --- Reading a line ---------------------------------------------------------------


@pytest.mark.usefixtures("workdir")
@pytest.mark.parametrize(
    "line",
    [
        "my report [draft].pdf",  # typed without quotes
        '"my report [draft].pdf"',  # dragged on Windows Terminal
        "'my report [draft].pdf'",
        "@my report [draft].pdf",
        "  @'my report [draft].pdf'  ",
    ],
)
def test_one_name_with_spaces_is_found_however_it_is_typed(line: str) -> None:
    assert shell.split_files(line) == ["my report [draft].pdf"]


@pytest.mark.usefixtures("workdir")
def test_several_names_on_one_line() -> None:
    line = 'second.pdf "my report [draft].pdf" missing.pdf'
    assert shell.split_files(line) == ["second.pdf", "my report [draft].pdf", "missing.pdf"]
    # Unquoted words are joined back only into an existing file.
    assert shell.split_files("second.pdf my report [draft].pdf") == [
        "second.pdf",
        "my report [draft].pdf",
    ]


@pytest.mark.usefixtures("workdir")
def test_wildcards_are_expanded_by_the_shell() -> None:
    assert shell.split_files("*.pdf") == ["my report [draft].pdf", "second.pdf"]
    assert shell.split_files("*.docx") == ["*.docx"]  # Reported as missing later.


@pytest.mark.skipif(os.name == "nt", reason="a backslash is a path separator on Windows")
@pytest.mark.usefixtures("workdir")
def test_a_backslash_escapes_a_space_on_linux_and_macos() -> None:
    assert shell.split_files(r"my\ report\ [draft].pdf") == ["my report [draft].pdf"]


# --- Converting and the commands -----------------------------------------------------


@pytest.mark.usefixtures("workdir")
def test_a_dropped_file_is_converted_and_saved(
    workdir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = run(capsys, "my report [draft].pdf", "/save out")
    assert "Section 1 says something new." in output
    assert "ACME Corporation" not in output.split("✓")[0]  # The header was removed.
    assert "✓ my report [draft].pdf  3 pages" in output
    assert "% saved" in output
    saved = workdir / "out" / "my report [draft].md"
    assert "Section 2 says something new." in saved.read_text(encoding="utf-8")


@pytest.mark.usefixtures("workdir")
def test_several_files_are_saved_together(
    workdir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run(capsys, "*.pdf", "/save")
    assert (workdir / "my report [draft].md").exists()
    assert (workdir / "second.md").exists()


@pytest.mark.usefixtures("workdir")
def test_a_missing_file_is_reported_and_the_shell_goes_on(
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = run(capsys, "missing.pdf", "second.pdf")
    assert "FILE_UNREADABLE" in output
    assert "✓ second.pdf  3 pages" in output


@pytest.mark.usefixtures("workdir")
def test_stats_and_explain_describe_the_last_file(capsys: pytest.CaptureFixture[str]) -> None:
    output = run(capsys, "/stats", "second.pdf", "/stats", "/explain")
    assert "Nothing converted yet" in output
    assert "Text before and after cleaning" in output
    # /explain made a receipt on its own: headers and page numbers were removed.
    assert "Removed blocks: 6" in output
    assert "headers_footers" in output


@pytest.mark.usefixtures("workdir")
def test_chunks_and_receipt_switch_on_for_the_next_files(
    workdir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = run(capsys, "/chunks 64", "/receipt on", "second.pdf", "/save out")
    assert "Chunks: on, 64 tokens each" in output
    assert "Receipt: on" in output
    lines = (workdir / "out" / "second.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[0])["schema_version"] == "1.0"
    receipt = json.loads((workdir / "out" / "second.receipt.json").read_text(encoding="utf-8"))
    assert receipt["removed"]


@pytest.mark.usefixtures("workdir")
def test_wrong_arguments_get_a_message_not_a_crash(capsys: pytest.CaptureFixture[str]) -> None:
    output = run(capsys, "/chunks 5", "/verify only-one.pdf", "/nonsense")
    assert "Chunk size must be between" in output
    assert "Give the file and its receipt" in output
    assert "Unknown command /nonsense" in output


@pytest.mark.usefixtures("workdir")
def test_verify_and_doctor_reuse_the_cli(
    workdir: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "run_checks", lambda: [Check("cache", Status.OK, "fine")])
    output = run(
        capsys,
        "/receipt on",
        "second.pdf",
        "/save out",
        "/verify second.pdf out/second.receipt.json",
        "/doctor",
    )
    assert "matches the receipt" in output
    assert "fine" in output


@pytest.mark.usefixtures("workdir")
def test_saving_never_overwrites_the_input(
    workdir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (workdir / "paper.md").write_bytes(report(1))  # A PDF named .md.
    output = run(capsys, "paper.md", "/save")
    assert "would overwrite the file itself" in output
    assert (workdir / "paper.md").read_bytes().startswith(b"%PDF")


@pytest.mark.usefixtures("workdir")
def test_help_lists_every_command(capsys: pytest.CaptureFixture[str]) -> None:
    output = run(capsys, "/help")
    for name in shell.COMMANDS:
        assert name in output


@pytest.mark.usefixtures("workdir")
def test_help_translates_the_argument_names(capsys: pytest.CaptureFixture[str]) -> None:
    i18n.activate("it")
    try:
        output = run(capsys, "/help")
    finally:
        i18n.activate("en")
    assert "/save [CARTELLA]" in output
    assert "/chunks [on|off|DIMENSIONE]" in output
    assert "/verify FILE RICEVUTA" in output
    assert "FOLDER" not in output


# --- How the shell opens ----------------------------------------------------------------


def test_sugo_alone_outside_a_terminal_prints_the_help() -> None:
    result = CliRunner().invoke(cli.app, [])
    assert result.exit_code == ExitCode.USAGE
    assert "convert" in result.output
    assert "shell" in result.output


def test_the_nul_device_is_not_a_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    # On Windows NUL claims to be a terminal; it has no size.
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True, raising=False)

    def no_size(fd: int = 1) -> os.terminal_size:
        raise OSError("not a console")

    monkeypatch.setattr(os, "get_terminal_size", no_size)
    assert cli._interactive() is False


@pytest.mark.usefixtures("workdir")
def test_sugo_shell_works_with_a_plain_input_line() -> None:
    # Without a console (here: the test runner), the shell falls back to input().
    result = CliRunner().invoke(cli.app, ["shell"], input="second.pdf\n/exit\n")
    assert result.exit_code == ExitCode.OK
    assert "Section 1 says something new." in plain(result.output)


# --- Hints ---------------------------------------------------------------------------


@pytest.mark.usefixtures("workdir")
def test_the_first_hint_says_what_to_do_then_tips_take_turns() -> None:
    state = shell.State(cli._settings(quiet=True))
    assert "Drag a file here" in shell.hint(state)
    shell.run_line(state, "second.pdf")
    tips = set()
    for read in range(len(shell.HINTS)):
        state.lines_read = read
        tips.add(shell.hint(state))
    # Every tip comes up, and none of them is the first-time hint.
    assert len(tips) == len(shell.HINTS)
    assert not any("Drag a file here" in tip for tip in tips)


def test_every_hint_names_a_real_command() -> None:
    for tip in shell.HINTS:
        for word in tip.split():
            if word.startswith("/"):
                assert word in shell.COMMANDS, word
