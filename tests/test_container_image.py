"""The Dockerfile keeps ADR-065's rules, and its MCP probe works (ADR-065)."""

import importlib.util
import re
import sys
import tomllib
from pathlib import Path
from types import ModuleType

import pytest

from sugo.storage.paths import CACHE_DIR_ENV

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = (ROOT / "Dockerfile").read_text(encoding="utf-8")


def from_images() -> list[str]:
    return re.findall(r"^FROM\s+(\S+)", DOCKERFILE, flags=re.MULTILINE)


def final_stage() -> str:
    return DOCKERFILE.rsplit("\nFROM ", 1)[1]


def load_probe() -> ModuleType:
    path = ROOT / "scripts" / "container" / "mcp_probe.py"
    spec = importlib.util.spec_from_file_location("mcp_probe", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_base_image_is_pinned_by_digest() -> None:
    images = from_images()
    assert len(images) == 3
    for image in images:
        assert re.fullmatch(r"[\w./-]+:[\w.-]+@sha256:[0-9a-f]{64}", image), image


def test_both_stages_use_the_same_supported_python() -> None:
    pythons = [image for image in from_images() if image.startswith("python:")]
    assert len(pythons) == 2
    assert pythons[0] == pythons[1]
    minor = re.match(r"python:3\.(\d+)\.", pythons[0])
    assert minor is not None
    with (ROOT / "pyproject.toml").open("rb") as file:
        requires = tomllib.load(file)["project"]["requires-python"]
    low, high = (int(n) for n in re.findall(r"3\.(\d+)", requires))
    assert low <= int(minor.group(1)) < high


def test_uv_is_the_version_ci_uses() -> None:
    (uv_image,) = [image for image in from_images() if "astral-sh/uv:" in image]
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    versions = set(re.findall(r'^\s+version: "(\d+\.\d+\.\d+)"', ci, flags=re.MULTILINE))
    assert versions == {uv_image.split(":")[1].split("@")[0]}


def test_packages_come_only_from_the_lock() -> None:
    syncs = re.findall(r"^RUN uv sync (.+)$", DOCKERFILE, flags=re.MULTILINE)
    assert syncs
    assert all("--locked" in flags and "--no-dev" in flags for flags in syncs)
    # Installing Sugo itself must not fetch an unpinned build backend.
    assert "--offline" in syncs[-1]
    assert "pip install" not in DOCKERFILE
    assert "UV_PYTHON_DOWNLOADS=never" in DOCKERFILE


def test_the_server_runs_unprivileged_and_reads_only_data() -> None:
    stage = final_stage()
    users = re.findall(r"^USER\s+(\S+)", stage, flags=re.MULTILINE)
    assert users
    assert users[-1] not in {"root", "0"}
    assert 'ENTRYPOINT ["sugo", "mcp"]' in stage
    assert 'CMD ["--root", "/data"]' in stage
    # No document text is kept in the container between documents.
    assert 'cache = "ephemeral"' in stage
    assert "XDG_CONFIG_HOME=/etc/sugo" in stage
    # Neither uv nor the source tree reaches the final image.
    assert "/uv" not in stage
    assert "COPY src" not in stage


def test_the_build_context_is_an_allow_list() -> None:
    lines = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    rules = [line for line in lines if line and not line.startswith("#")]
    assert rules[0] == "*"
    allowed = {rule[1:].rstrip("/") for rule in rules if rule.startswith("!")}
    assert allowed == {"pyproject.toml", "uv.lock", "README.md", "LICENSE", "src"}


def test_the_probe_accepts_sugos_mcp_server(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The server runs in a child process: keep it off the real cache and, on
    # Linux and macOS, off the real user configuration.
    monkeypatch.setenv(CACHE_DIR_ENV, str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    sugo = Path(sys.executable).with_name("sugo.exe" if sys.platform == "win32" else "sugo")
    command = [str(sugo), "mcp", "--root", str(tmp_path)]
    assert load_probe().probe(command) is None


def test_the_probe_rejects_a_server_that_does_not_answer() -> None:
    assert load_probe().probe([sys.executable, "-c", "pass"]) is not None
