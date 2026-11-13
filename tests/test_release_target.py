"""Tests for the release workflow's tag check (ADR-033, ADR-068)."""

import importlib.util
import tomllib
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parent.parent


def load() -> ModuleType:
    path = ROOT / "scripts" / "release" / "release_target.py"
    spec = importlib.util.spec_from_file_location("release_target", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def version(directory: str) -> str:
    text = (ROOT / directory / "pyproject.toml").read_text(encoding="utf-8")
    return str(tomllib.loads(text)["project"]["version"])


release_target = load()


@pytest.mark.parametrize(
    ("prefix", "directory", "name"),
    [
        ("", ".", "sugo-cli"),
        ("langchain-sugo-", "integrations/langchain-sugo", "langchain-sugo"),
        (
            "llama-index-readers-sugo-",
            "integrations/llama-index-readers-sugo",
            "llama-index-readers-sugo",
        ),
    ],
)
def test_each_tag_publishes_its_own_project(prefix: str, directory: str, name: str) -> None:
    tag = f"{prefix}v{version(directory)}"
    assert release_target.target(tag) == (directory, name)


@pytest.mark.parametrize(
    "ref",
    [
        "v9.9.9",  # not sugo-cli's version
        "langchain-sugo-v9.9.9",
        "other-package-v0.1.0",
        "v0.2.0a1",  # pre-releases are published by hand (ADR-033)
        "main",
        "",
    ],
)
def test_a_tag_that_does_not_match_stops_the_release(ref: str) -> None:
    with pytest.raises(release_target.ReleaseTargetError):
        release_target.target(ref)


def test_a_project_name_is_a_dry_run_without_version_check() -> None:
    assert release_target.target("langchain-sugo") == (
        "integrations/langchain-sugo",
        "langchain-sugo",
    )


def test_every_project_folder_names_its_distribution() -> None:
    for name, directory in release_target.PROJECTS.items():
        text = (ROOT / directory / "pyproject.toml").read_text(encoding="utf-8")
        assert tomllib.loads(text)["project"]["name"] == name
