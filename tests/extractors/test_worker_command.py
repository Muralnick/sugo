"""How worker processes are started: isolated, yet able to find Sugo (ADR-061)."""

import os
import site
import subprocess
import sys
from pathlib import Path

import pytest

import sugo
from sugo.extractors import worker

SUGO_PACKAGE = Path(sugo.__file__).resolve().parent


def flags(command: tuple[str, ...]) -> list[str]:
    """The interpreter flags: everything between the executable and "-m"."""
    assert command[0] == sys.executable
    end = command.index("-m")
    assert command[end + 1 :] == ("sugo.extractors.pymupdf.worker",)
    return list(command[1:end])


def test_an_ordinary_install_runs_the_worker_fully_isolated() -> None:
    # -E -P -s is exactly what -I means.
    assert flags(worker.module_command("sugo.extractors.pymupdf.worker")) == ["-E", "-P", "-s"]


def test_a_user_install_lets_the_worker_find_sugo(monkeypatch: pytest.MonkeyPatch) -> None:
    # pip install --user: Sugo lives in the user's site-packages.
    monkeypatch.setattr(site, "ENABLE_USER_SITE", True)
    monkeypatch.setattr(site, "getusersitepackages", lambda: str(SUGO_PACKAGE.parent))
    assert flags(worker.module_command("sugo.extractors.pymupdf.worker")) == ["-E", "-P"]


def test_the_user_site_stays_out_when_python_disables_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(site, "ENABLE_USER_SITE", False)
    monkeypatch.setattr(site, "getusersitepackages", lambda: str(SUGO_PACKAGE.parent))
    assert "-s" in flags(worker.module_command("sugo.extractors.pymupdf.worker"))


@pytest.mark.parametrize("user_install", [False, True])
def test_neither_environment_nor_current_folder_can_change_the_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, user_install: bool
) -> None:
    if user_install:
        monkeypatch.setattr(site, "ENABLE_USER_SITE", True)
        monkeypatch.setattr(site, "getusersitepackages", lambda: str(SUGO_PACKAGE.parent))
    # A planted "sugo" in the current folder and on PYTHONPATH.
    fake = tmp_path / "sugo"
    fake.mkdir()
    (fake / "__init__.py").write_text("raise SystemExit('planted code ran')\n")
    interpreter = flags(worker.module_command("sugo.extractors.pymupdf.worker"))
    result = subprocess.run(  # noqa: S603 - fixed arguments, no shell
        [sys.executable, *interpreter, "-c", "import sugo; print(sugo.__file__)"],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(tmp_path)},
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert Path(result.stdout.strip()).resolve().parent == SUGO_PACKAGE
