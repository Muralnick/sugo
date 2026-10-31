"""Shared fixtures: every test runs without the developer's own Sugo configuration.

Tests also run in English unless they choose another interface language.
"""

from collections.abc import Iterator

import pytest

from sugo.config import settings
from sugo.config.settings import ENVIRONMENT
from sugo.ports.cli.translation import use_language


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


@pytest.fixture(autouse=True)
def _english_after_each_test() -> Iterator[None]:
    yield
    # The interface language is process-wide: a test that switches it switches it back.
    use_language("en")
