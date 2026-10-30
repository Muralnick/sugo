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


def test_paths_outside_the_roots_never_touch_the_file_system(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    resolved: list[Path] = []
    original = Path.resolve

    def recording(self: Path, strict: bool = False) -> Path:
        resolved.append(self)
        return original(self, strict=strict)

    monkeypatch.setattr(Path, "resolve", recording)
    roots = Roots([root])
    resolved.clear()
    assert code(roots, str(root.parent / "outside.pdf")) == "PATH_NOT_ALLOWED"
    assert code(roots, "../outside.pdf") == "PATH_NOT_ALLOWED"
    assert resolved == []


@pytest.mark.skipif(os.name != "nt", reason="Windows path forms")
@pytest.mark.parametrize(
    "raw",
    [
        "\\\\192.0.2.1\\share\\x.pdf",
        "//192.0.2.1/share/x.pdf",
        "\\\\attacker.example@SSL@443\\dav\\x.pdf",
        "\\\\?\\UNC\\192.0.2.1\\share\\x.pdf",
        "\\\\.\\pipe\\sugo",
        "\\\\?\\C:\\x.pdf",
        # Rooted without a drive: taken on the root's drive, outside the root.
        "\\192.0.2.1\\share\\x.pdf",
        "contracts/a.pdf::$DATA",
        "contracts/a.pdf:hidden",
    ],
)
def test_network_device_and_stream_paths_are_refused_before_any_access(
    root: Path, monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    roots = Roots([root])
    # Resolving opens the path; os.path.abspath only rewrites the text.
    touched: list[object] = []
    original_resolve = Path.resolve

    def resolve(self: Path, strict: bool = False) -> Path:
        touched.append(self)
        return original_resolve(self, strict=strict)

    monkeypatch.setattr(Path, "resolve", resolve)
    try:
        roots.check(raw)
    except PortError as error:
        refused = error.code
    monkeypatch.undo()
    assert refused == "PATH_NOT_ALLOWED"
    assert touched == []
