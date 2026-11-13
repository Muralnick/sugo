"""Pick the project a release tag publishes, and refuse a tag that does not match it.

The release workflow serves three distributions (ADR-033, ADR-068). The tag
says which one: ``v0.2.0`` is sugo-cli, ``langchain-sugo-v0.1.0`` and
``llama-index-readers-sugo-v0.1.0`` are the loaders. The version in the tag
must equal the one in that project's pyproject.toml, so a mistyped tag stops
the release before anything is built.

Usage (inside the release workflow):
    python3 scripts/release/release_target.py <tag-or-project-name>

Prints ``directory=...`` and ``name=...`` lines for ``$GITHUB_OUTPUT``. A
plain project name (a manual dry run on a branch) skips the version check.
"""

import re
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# Distribution name -> its folder, relative to the repository root.
PROJECTS = {
    "sugo-cli": ".",
    "langchain-sugo": "integrations/langchain-sugo",
    "llama-index-readers-sugo": "integrations/llama-index-readers-sugo",
}
_TAG = re.compile(r"(?:(?P<prefix>[a-z][a-z-]*)-)?v(?P<version>\d+\.\d+\.\d+)")


class ReleaseTargetError(ValueError):
    """The tag names no project, or its version is not the project's."""


def target(ref: str, root: Path = REPO_ROOT) -> tuple[str, str]:
    """The (directory, distribution name) the tag or project name ``ref`` publishes."""
    if ref in PROJECTS:
        return PROJECTS[ref], ref
    match = _TAG.fullmatch(ref)
    if match is None:
        raise ReleaseTargetError(f"not a release tag or project name: {ref!r}")
    name = match["prefix"] or "sugo-cli"
    if name not in PROJECTS:
        raise ReleaseTargetError(f"no project is released with the tag prefix {name!r}")
    directory = PROJECTS[name]
    pyproject = tomllib.loads((root / directory / "pyproject.toml").read_text(encoding="utf-8"))
    project = pyproject["project"]
    if project["name"] != name:
        raise ReleaseTargetError(f"{directory}/pyproject.toml names {project['name']!r}")
    if project["version"] != match["version"]:
        raise ReleaseTargetError(
            f"tag {ref!r} says {match['version']}, but {name} is {project['version']}"
        )
    return directory, name


def main() -> None:
    if len(sys.argv) != 2:  # noqa: PLR2004  (script name and one argument)
        sys.exit(__doc__)
    try:
        directory, name = target(sys.argv[1])
    except ReleaseTargetError as error:
        sys.exit(f"release_target: {error}")
    sys.stdout.write(f"directory={directory}\nname={name}\n")


if __name__ == "__main__":
    main()
