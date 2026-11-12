"""Tests for sugo uninstall and sugo cache clear: what they delete, when, and what they say."""

import sqlite3
from pathlib import Path

import pytest
from typer.testing import CliRunner, Result

from sugo.config import settings
from sugo.core.models import Block, BlockType, Page, PageOrigin
from sugo.ports.cli import app as cli
from sugo.ports.cli import uninstall
from sugo.ports.cli.translation import use_language
from sugo.ports.errors import ExitCode
from sugo.storage import page_cache
from sugo.storage.page_cache import CacheLevel, PageCache, extraction_key
from sugo.storage.paths import CACHE_DIR_ENV

PAGE = Page(
    index=0,
    width=595,
    height=842,
    origin=PageOrigin.NATIVE,
    blocks=(Block(id="b0", type=BlockType.PARAGRAPH, text="private text", origin_engine="t"),),
)


@pytest.fixture(autouse=True)
def cache_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    # Never the developer's own cache: these tests delete it.
    folder = tmp_path / "cache"
    monkeypatch.setenv(CACHE_DIR_ENV, str(folder))
    return folder


@pytest.fixture
def config_file() -> Path:
    # The conftest points the settings at a temporary folder.
    path = settings.user_config_path()
    path.write_text('[ui]\nlanguage = "en"\n')
    return path


@pytest.fixture
def filled(cache_folder: Path) -> Path:
    key = extraction_key(source_sha256="0" * 64, page_index=0, engine="t")
    with PageCache(cache_folder / "cache.db") as cache:
        cache.put(CacheLevel.EXTRACTION, key, PAGE)
    return cache_folder


@pytest.fixture
def terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "_interactive", lambda: True)


def run(*args: str, answer: str | None = None) -> Result:
    return CliRunner().invoke(cli.app, list(args), input=answer)


def test_cache_clear_deletes_the_cache(filled: Path) -> None:
    result = run("cache", "clear")
    assert result.exit_code == 0
    assert not filled.exists()
    assert "Deleted the cache" in result.stderr


def test_cache_clear_with_no_cache_says_so(cache_folder: Path) -> None:
    result = run("cache", "clear")
    assert result.exit_code == 0
    assert "already empty" in result.stderr


def test_cache_clear_in_use_reports_it(filled: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(page_cache, "CACHE_DELETE_WAIT_S", 0.05)
    writer = sqlite3.connect(filled / "cache.db", isolation_level=None)
    writer.execute("BEGIN IMMEDIATE")
    try:
        result = run("cache", "clear")
    finally:
        writer.execute("ROLLBACK")
        writer.close()
    assert result.exit_code == ExitCode.ERROR
    assert "CACHE_IN_USE" in result.stderr
    assert (filled / "cache.db").exists()


def test_uninstall_outside_a_terminal_needs_yes(filled: Path, config_file: Path) -> None:
    result = run("uninstall")
    assert result.exit_code == ExitCode.USAGE
    assert "--yes" in result.stderr
    assert (filled / "cache.db").exists()
    assert config_file.exists()


def test_uninstall_with_yes_deletes_settings_and_cache(filled: Path, config_file: Path) -> None:
    result = run("uninstall", "--yes")
    assert result.exit_code == 0
    assert not filled.exists()
    assert not config_file.exists()
    assert not config_file.parent.exists()
    assert "sugo-cli" in result.stderr  # the command that removes the program
    assert "claude mcp remove sugo" in result.stderr
    assert result.stdout == ""


def test_uninstall_can_keep_the_settings(filled: Path, config_file: Path) -> None:
    result = run("uninstall", "--yes", "--keep-config")
    assert result.exit_code == 0
    assert not filled.exists()
    assert config_file.exists()


def test_uninstall_lists_what_it_deletes_before_asking(
    filled: Path, config_file: Path, terminal: None
) -> None:
    result = run("uninstall", answer="\n")
    assert result.exit_code == 0
    assert str(config_file) in result.stderr
    assert str(filled) in result.stderr
    assert "text of converted documents" in result.stderr
    # Enter alone is no.
    assert "Nothing was deleted" in result.stderr
    assert (filled / "cache.db").exists()
    assert config_file.exists()


@pytest.mark.parametrize("answer", ["y", "yes", "Y"])
def test_uninstall_deletes_after_yes(
    filled: Path, config_file: Path, terminal: None, answer: str
) -> None:
    result = run("uninstall", answer=answer + "\n")
    assert result.exit_code == 0
    assert not filled.exists()
    assert not config_file.exists()


def test_italian_yes_is_accepted(filled: Path, terminal: None) -> None:
    use_language("it")
    result = run("uninstall", answer="sì\n")
    assert result.exit_code == 0
    assert not filled.exists()


def test_uninstall_with_nothing_to_delete_still_explains(cache_folder: Path) -> None:
    result = run("uninstall")
    assert result.exit_code == 0
    assert "no files to delete" in result.stderr
    assert "To remove the program" in result.stderr


def test_a_settings_folder_is_refused(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    folder = tmp_path / "config.toml"
    (folder / "inside").mkdir(parents=True)
    monkeypatch.setattr(settings, "user_config_path", lambda: folder)
    result = run("uninstall", "--yes")
    assert result.exit_code == ExitCode.SECURITY
    assert "STORAGE_REFUSED" in result.stderr
    assert (folder / "inside").exists()


@pytest.mark.parametrize(
    ("prefix", "command"),
    [
        ("/home/u/.local/share/uv/tools/sugo-cli", "uv tool uninstall sugo-cli"),
        ("C:/Users/u/AppData/Roaming/uv/data/tools/sugo-cli", "uv tool uninstall sugo-cli"),
        ("/home/u/.cache/uv/archive-v0/AbC123", "uv cache clean sugo-cli"),
        ("/home/u/.local/share/pipx/venvs/sugo-cli", "pipx uninstall sugo-cli"),
        ("/home/u/project/.venv", "pip uninstall sugo-cli"),
        ("/usr", "pip uninstall sugo-cli"),
    ],
)
def test_removal_command_follows_the_installer(prefix: str, command: str) -> None:
    assert uninstall.removal_command(Path(prefix)) == command
