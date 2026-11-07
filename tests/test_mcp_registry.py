"""The package and server.json agree, so the MCP Registry can run Sugo (ADR-060)."""

import json
import re
import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LITE = {"numpy", "onnxruntime", "pillow", "pymupdf", "rapidocr"}


def project() -> dict[str, Any]:
    with (ROOT / "pyproject.toml").open("rb") as file:
        return dict(tomllib.load(file)["project"])


def server() -> dict[str, Any]:
    return dict(json.loads((ROOT / "server.json").read_text(encoding="utf-8")))


def test_server_json_names_this_package_and_version() -> None:
    meta, described = project(), server()
    (package,) = described["packages"]
    assert package["registryType"] == "pypi"
    assert package["identifier"] == meta["name"]
    # A release bumps all three together.
    assert described["version"] == package["version"] == meta["version"]


def test_the_package_name_is_also_a_command() -> None:
    # uvx sugo-cli runs the executable named like the package.
    scripts = project()["scripts"]
    assert scripts[project()["name"]] == scripts["sugo"]


def test_the_readme_proves_ownership_of_the_server_name() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    found = re.findall(r"mcp-name: (\S+) -->", readme)
    assert found == [server()["name"]]


def test_the_lite_level_is_installed_by_default() -> None:
    meta = project()
    names = {re.split(r"[<>=!~ \[]", dep, maxsplit=1)[0].lower() for dep in meta["dependencies"]}
    assert names >= LITE
    # Kept, empty, so older "sugo-cli[lite]" commands still install.
    assert meta["optional-dependencies"]["lite"] == []


def test_the_server_is_started_as_sugo_mcp_with_a_root() -> None:
    (package,) = server()["packages"]
    arguments = package["packageArguments"]
    assert arguments[0] == {"type": "positional", "value": "mcp"}
    root = arguments[1]
    assert (root["name"], root["isRequired"], root["isRepeated"]) == ("--root", True, True)
