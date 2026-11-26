"""Tests for the image tags a release may move (ADR-075)."""

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parent.parent


def load() -> ModuleType:
    path = ROOT / "scripts" / "release" / "image_tags.py"
    spec = importlib.util.spec_from_file_location("image_tags", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


image_tags = load()

# As git ls-remote --tags prints them, loader tags and annotated-tag lines included.
LS_REMOTE = [
    "aaaa\trefs/tags/v0.2.0",
    "bbbb\trefs/tags/v0.3.1",
    "cccc\trefs/tags/v0.3.1^{}",
    "dddd\trefs/tags/v0.4.0",
    "eeee\trefs/tags/langchain-sugo-v9.9.9",
    "ffff\trefs/tags/v0.1.0a1",
    "",
]


def test_the_newest_release_moves_every_tag() -> None:
    assert image_tags.tags("0.4.1", LS_REMOTE) == ["0.4.1", "0.4", "latest"]


def test_a_backport_keeps_latest_on_the_newest_line() -> None:
    assert image_tags.tags("0.3.2", LS_REMOTE) == ["0.3.2", "0.3"]


def test_an_old_patch_moves_only_its_own_tag() -> None:
    assert image_tags.tags("0.3.0", LS_REMOTE) == ["0.3.0"]


def test_the_release_being_tagged_may_already_be_listed() -> None:
    assert image_tags.tags("0.4.0", LS_REMOTE) == ["0.4.0", "0.4", "latest"]


def test_the_first_release_with_no_tags_is_latest() -> None:
    assert image_tags.tags("0.1.0", []) == ["0.1.0", "0.1", "latest"]


@pytest.mark.parametrize("version", ["v0.4.1", "0.4", "0.4.1a1", ""])
def test_anything_but_a_plain_version_is_refused(version: str) -> None:
    with pytest.raises(ValueError, match="not a stable"):
        image_tags.tags(version, LS_REMOTE)
