"""Tests for allowed roots and fixed exclusions: what an agent may read through MCP."""

import os
from pathlib import Path

import pytest

from sugo.ports.errors import PortError
from sugo.ports.mcp.access import Roots, is_excluded


@pytest.fixture
def root(tmp_path: Path) -> Path:
    folder = tmp_path / "docs"
    (folder / "contracts").mkdir(parents=True)
    (folder / "contracts" / "a.pdf").write_bytes(b"%PDF-1.7")
    (tmp_path / "outside.pdf").write_bytes(b"%PDF-1.7")
    return folder


def code(roots: Roots, raw: str) -> str:
    with pytest.raises(PortError) as caught:
        roots.check(raw)
    return caught.value.code


def test_files_inside_a_root_are_allowed_with_a_relative_source(root: Path) -> None:
    roots = Roots([root])
    for raw in (
        "contracts/a.pdf",
        str(root / "contracts" / "a.pdf"),
        "./contracts/../contracts/a.pdf",
    ):
        allowed = roots.check(raw)
        assert allowed.source == "contracts/a.pdf"
        assert allowed.path == (root / "contracts" / "a.pdf").resolve()


def test_paths_outside_every_root_are_refused(root: Path) -> None:
    roots = Roots([root])
    assert code(roots, str(root.parent / "outside.pdf")) == "PATH_NOT_ALLOWED"
    assert code(roots, "../outside.pdf") == "PATH_NOT_ALLOWED"
    assert code(roots, "") == "PATH_NOT_ALLOWED"
    assert code(roots, "a\x00b") == "PATH_NOT_ALLOWED"


def test_existence_outside_the_roots_is_never_revealed(root: Path) -> None:
    roots = Roots([root])
    # Same answer whether the outside file exists or not.
    assert code(roots, str(root.parent / "outside.pdf")) == "PATH_NOT_ALLOWED"
    assert code(roots, str(root.parent / "missing.pdf")) == "PATH_NOT_ALLOWED"
    assert code(roots, "contracts/missing.pdf") == "FILE_UNREADABLE"
    assert code(roots, "contracts") == "FILE_UNREADABLE"


@pytest.mark.skipif(not hasattr(os, "symlink") or os.name != "posix", reason="POSIX symbolic links")
def test_symbolic_links_are_resolved_before_the_check(root: Path) -> None:
    (root / "link.pdf").symlink_to(root.parent / "outside.pdf")
    assert code(Roots([root]), "link.pdf") == "PATH_NOT_ALLOWED"


@pytest.mark.parametrize(
    "relative",
    [
        ".ssh/id_ed25519.png",
        "home/.SSH/notes.pdf",
        ".gnupg/x.pdf",
        ".aws/credentials.png",
        ".local/share/keyrings/login.pdf",
        "project/.env",
        "project/.env.local",
        "keys/id_rsa.pub",
        "vault.kdbx",
        "certs/server.pem",
    ],
)
def test_secret_locations_are_excluded_everywhere(root: Path, relative: str) -> None:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"%PDF-1.7")
    assert code(Roots([root]), relative) == "PATH_EXCLUDED"


def test_ordinary_names_are_not_excluded() -> None:
    assert not is_excluded(Path("docs/environment.pdf"))
    assert not is_excluded(Path("docs/ssh-guide.pdf"))


def test_roots_must_exist_and_not_be_secret(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="at least one"):
        Roots([])
    with pytest.raises(FileNotFoundError):
        Roots([tmp_path / "missing"])
    (tmp_path / ".ssh").mkdir()
    with pytest.raises(ValueError, match="secrets"):
        Roots([tmp_path / ".ssh"])


def test_relative_paths_are_tried_in_every_root(tmp_path: Path) -> None:
    first, second = tmp_path / "one", tmp_path / "two"
    first.mkdir()
    second.mkdir()
    (second / "b.png").write_bytes(b"\x89PNG")
    assert Roots([first, second]).check("b.png").path == (second / "b.png").resolve()
