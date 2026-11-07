"""Tests for ``sugo ui``: the address it prints or opens, and stopping with Ctrl+C."""

import os
import re
import stat
import webbrowser
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from typer.testing import CliRunner

from sugo.ports.cli import app as cli
from sugo.ports.cli.translation import use_language
from sugo.ports.web import launcher
from sugo.ports.web.server import WebServer

ADDRESS = re.compile(r"http://127\.0\.0\.1:\d+/#token=[A-Za-z0-9_-]{43}")


@pytest.fixture
def launched(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    """The launcher pages the command wrote, while they exist."""
    paths: list[Path] = []
    original = launcher.launcher_page

    @contextmanager
    def recording(url: str) -> Iterator[Path]:
        with original(url) as path:
            paths.append(path)
            yield path

    monkeypatch.setattr(launcher, "launcher_page", recording)
    return paths


@pytest.fixture
def served(monkeypatch: pytest.MonkeyPatch) -> list[WebServer]:
    """Servers the command started; each stops at once, as with Ctrl+C."""
    started: list[WebServer] = []

    def interrupted(self: WebServer, poll_interval: float = 0.5) -> None:
        started.append(self)
        raise KeyboardInterrupt

    monkeypatch.setattr(WebServer, "serve_forever", interrupted)
    return started


def test_no_browser_prints_the_address(
    served: list[WebServer], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(webbrowser, "open", lambda url: pytest.fail("no browser expected"))
    result = CliRunner().invoke(cli.app, ["ui", "--no-browser"])
    assert result.exit_code == 0, result.output
    assert result.stdout.strip() == served[0].url
    assert ADDRESS.fullmatch(result.stdout.strip())
    assert "Stopped." in result.stderr


def test_the_browser_opens_the_address(
    served: list[WebServer], launched: list[Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: list[str] = []
    pages: list[str] = []

    def open_url(url: str) -> bool:
        opened.append(url)
        pages.append(launched[0].read_text(encoding="utf-8"))
        return True

    monkeypatch.setattr(webbrowser, "open", open_url)
    result = CliRunner().invoke(cli.app, ["ui"])
    assert result.exit_code == 0, result.output
    # Security review F7: the token never reaches the browser's command line
    # nor the terminal; a private page forwards to the address.
    (url,) = opened
    assert url == launched[0].as_uri()
    assert "token" not in url
    assert served[0].url in pages[0]
    assert served[0].token not in result.output
    assert result.stdout == ""
    assert "Ctrl+C" in result.stderr


@pytest.mark.usefixtures("served")
def test_the_launcher_page_is_private_and_deleted_after(
    launched: list[Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    def open_url(url: str) -> bool:
        if os.name == "posix":
            assert stat.S_IMODE(launched[0].stat().st_mode) == 0o600
            assert stat.S_IMODE(launched[0].parent.stat().st_mode) == 0o700
        return True

    monkeypatch.setattr(webbrowser, "open", open_url)
    CliRunner().invoke(cli.app, ["ui"])
    assert not launched[0].exists()


def test_the_server_is_closed_after_stopping(served: list[WebServer]) -> None:
    CliRunner().invoke(cli.app, ["ui", "--no-browser"])
    assert served[0].socket.fileno() == -1


def test_without_a_browser_the_address_is_still_shown(
    served: list[WebServer], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(webbrowser, "open", lambda url: False)
    result = CliRunner().invoke(cli.app, ["ui"])
    assert served[0].url in result.stderr
    assert "No browser found" in result.stderr


def test_the_help_is_translated() -> None:
    use_language("it")
    result = CliRunner().invoke(cli.app, ["ui", "--help"], terminal_width=200)
    assert "Apri la pagina di Sugo nel browser" in result.stdout


def test_ctrl_c_while_the_browser_opens_stops_cleanly(
    served: list[WebServer], monkeypatch: pytest.MonkeyPatch
) -> None:
    def interrupted(url: str) -> bool:
        raise KeyboardInterrupt

    monkeypatch.setattr(webbrowser, "open", interrupted)
    result = CliRunner().invoke(cli.app, ["ui"])
    assert result.exit_code == 0
    assert "Stopped." in result.stderr
    assert served == []
