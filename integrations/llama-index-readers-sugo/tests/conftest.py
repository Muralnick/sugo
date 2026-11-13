"""Every test runs with network access blocked (ADR-068): a loader or a
framework feature that tries to connect fails the test instead of downloading."""

import socket
from collections.abc import Callable
from pathlib import Path

import pytest

from loader_helpers import blocked


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)


@pytest.fixture(autouse=True)
def _no_user_configuration(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The developer's own Sugo settings and page cache never reach a test.
    home = tmp_path_factory.mktemp("home")
    monkeypatch.chdir(home)
    for variable in ("XDG_CONFIG_HOME", "XDG_CACHE_HOME", "APPDATA", "LOCALAPPDATA"):
        monkeypatch.setenv(variable, str(home / variable.lower()))
    monkeypatch.setenv("SUGO_CACHE_DIR", str(home / "cache"))
    monkeypatch.setenv("LANG", "C.UTF-8")


@pytest.fixture
def write(tmp_path: Path) -> Callable[[str, bytes], Path]:
    def _write(name: str, data: bytes) -> Path:
        path = tmp_path / name
        path.write_bytes(data)
        return path

    return _write
