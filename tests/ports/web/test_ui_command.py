"""Tests for ``sugo ui``: the address it prints or opens, and stopping with Ctrl+C."""

import re
import webbrowser

import pytest
from typer.testing import CliRunner

from sugo.ports.cli import app as cli
from sugo.ports.cli.translation import use_language
from sugo.ports.web.server import WebServer

ADDRESS = re.compile(r"http://127\.0\.0\.1:\d+/#token=[A-Za-z0-9_-]{43}")


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
    served: list[WebServer], monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: list[str] = []

    def open_url(url: str) -> bool:
        opened.append(url)
        return True

    monkeypatch.setattr(webbrowser, "open", open_url)
    result = CliRunner().invoke(cli.app, ["ui"])
    assert result.exit_code == 0, result.output
    assert opened == [served[0].url]
    assert result.stdout == ""
    assert "Ctrl+C" in result.stderr


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
