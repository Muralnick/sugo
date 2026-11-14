"""Tests for sugo models list, pull and remove: what they ask, say and exit with (ADR-070)."""

import json
from pathlib import Path
from types import MappingProxyType

import pytest
from tests.internal.test_net import FakeServer
from tests.models.test_models import BODY, CARD, ByHost
from typer.testing import CliRunner, Result

from sugo._internal import net
from sugo.models import registry, store
from sugo.ports.cli import app as cli
from sugo.ports.errors import ExitCode
from sugo.storage.paths import CACHE_DIR_ENV


@pytest.fixture(autouse=True)
def test_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(CACHE_DIR_ENV, str(tmp_path / "cache"))
    monkeypatch.setattr(registry, "REGISTRY", MappingProxyType({CARD.id: CARD}))


def serve(monkeypatch: pytest.MonkeyPatch, opener: ByHost) -> ByHost:
    monkeypatch.setattr(net, "_default_opener", lambda: opener)
    return opener


def run(*args: str) -> Result:
    return CliRunner().invoke(cli.app, list(args))


@pytest.fixture
def terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "_interactive", lambda: True)


def test_list_shows_what_is_installed() -> None:
    result = run("models", "list", "--json")
    assert result.exit_code == 0
    assert json.loads(result.stdout) == {
        "models": [
            {
                "id": "ocr-test",
                "task": "ocr-recognition",
                "languages": ["xx"],
                "installed": False,
                "size_bytes": len(BODY),
                "licence": "Apache-2.0",
            }
        ]
    }
    assert "ocr-test" in run("models", "list").stdout


def test_pull_outside_a_terminal_needs_yes(monkeypatch: pytest.MonkeyPatch) -> None:
    opener = serve(monkeypatch, ByHost(github=FakeServer(BODY)))
    result = run("models", "pull", "ocr-test")
    assert result.exit_code == ExitCode.USAGE
    assert "add --yes" in result.stderr
    assert opener.asked == []


def test_pull_asks_and_downloads(monkeypatch: pytest.MonkeyPatch, terminal: None) -> None:
    serve(monkeypatch, ByHost(github=FakeServer(BODY)))
    monkeypatch.setattr(cli, "_download", lambda card, offline: store_body())
    result = CliRunner().invoke(cli.app, ["models", "pull", "ocr-test"], input="y\n")
    assert result.exit_code == 0, result.stderr
    assert "Apache-2.0" in result.stderr
    assert "From: GitHub, ModelScope" in result.stderr
    assert "Downloaded and verified ocr-test." in result.stderr


def store_body() -> None:
    store.prepare(CARD)
    store.model_path(CARD).write_bytes(BODY)


def test_pull_answer_no_downloads_nothing(monkeypatch: pytest.MonkeyPatch, terminal: None) -> None:
    opener = serve(monkeypatch, ByHost(github=FakeServer(BODY)))
    result = CliRunner().invoke(cli.app, ["models", "pull", "ocr-test"], input="n\n")
    assert result.exit_code == 0
    assert "Nothing was downloaded." in result.stderr
    assert opener.asked == []


def test_pull_with_yes_downloads_and_verifies(monkeypatch: pytest.MonkeyPatch) -> None:
    serve(monkeypatch, ByHost(github=FakeServer(status=404), modelscope=FakeServer(BODY)))
    result = run("models", "pull", "ocr-test", "--yes")
    assert result.exit_code == 0, result.stderr
    assert store.model_path(CARD).read_bytes() == BODY
    again = run("models", "pull", "ocr-test", "--yes")
    assert "already installed" in again.stderr


def test_pull_in_offline_mode_says_so_before_asking(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUGO_OFFLINE", "1")
    result = run("models", "pull", "ocr-test")
    assert result.exit_code == ExitCode.ERROR
    assert "OFFLINE" in result.stderr
    assert "Sugo will download" not in result.stderr


def test_every_source_failing_is_download_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    serve(monkeypatch, ByHost(github=FakeServer(status=404), modelscope=FakeServer(status=500)))
    result = run("models", "pull", "ocr-test", "--yes")
    assert result.exit_code == ExitCode.ERROR
    assert "DOWNLOAD_FAILED" in result.stderr


def test_unknown_model_is_a_usage_error() -> None:
    result = run("models", "pull", "ocr-klingon", "--yes")
    assert result.exit_code == ExitCode.USAGE
    assert "MODEL_UNKNOWN" in result.stderr


def test_a_damaged_model_is_downloaded_again(monkeypatch: pytest.MonkeyPatch) -> None:
    serve(monkeypatch, ByHost(github=FakeServer(BODY)))
    store.prepare(CARD)
    store.model_path(CARD).write_bytes(b"z" * len(BODY))
    result = run("models", "pull", "ocr-test", "--yes")
    assert result.exit_code == 0, result.stderr
    assert "damaged" in result.stderr
    assert store.model_path(CARD).read_bytes() == BODY


def test_remove(monkeypatch: pytest.MonkeyPatch) -> None:
    assert "is not installed" in run("models", "remove", "ocr-test").stderr
    store_body()
    result = run("models", "remove", "ocr-test")
    assert result.exit_code == 0
    assert "Deleted ocr-test" in result.stderr
    assert store.find(CARD) is None
