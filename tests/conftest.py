"""Shared fixtures: every test runs without the developer's own Sugo configuration."""

import pytest

from sugo.config import settings
from sugo.config.settings import ENVIRONMENT


@pytest.fixture(autouse=True)
def _no_user_configuration(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing = tmp_path_factory.mktemp("config") / "config.toml"
    monkeypatch.setattr(settings, "user_config_path", lambda: missing)
    for variable in ENVIRONMENT:
        monkeypatch.delenv(variable, raising=False)
    # Default languages follow the locale: the same on every machine and in CI.
    for variable in ("LC_ALL", "LC_MESSAGES"):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("LANG", "C.UTF-8")
