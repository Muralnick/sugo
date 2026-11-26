"""Pick the container image tags a sugo-cli release may move (ADR-075).

Every release tags its image ``X.Y.Z``. ``X.Y`` and ``latest`` are moved
only when this release is the highest of its minor line and of all sugo-cli
releases: a security backport such as v0.3.4 after v0.4.0 must not take
``latest`` back to an older line. The repository's release tags are read
from standard input, one per line, as ``git ls-remote --tags`` prints them
(or as plain tag names).

Usage (inside the release workflow):
    git ls-remote --tags origin | python3 scripts/release/image_tags.py <version>

Prints the tags, one per line, ``X.Y.Z`` first.
"""

import re
import sys

_STABLE = re.compile(r"(?:refs/tags/)?v(\d+)\.(\d+)\.(\d+)")


def _version(text: str) -> tuple[int, int, int] | None:
    match = _STABLE.fullmatch(text)
    if match is None:
        return None
    major, minor, patch = (int(part) for part in match.groups())
    return major, minor, patch


def tags(version: str, released: list[str]) -> list[str]:
    """The tags this release's image gets, given the released tag names."""
    current = _version(f"v{version}")
    if current is None:
        raise ValueError(f"not a stable sugo-cli version: {version!r}")
    known = {current}
    for line in released:
        name = line.split()[-1] if line.strip() else ""
        found = _version(name)
        if found is not None:
            known.add(found)
    result = [version]
    if current == max(v for v in known if v[:2] == current[:2]):
        result.append(f"{current[0]}.{current[1]}")
    if current == max(known):
        result.append("latest")
    return result


def main() -> None:
    if len(sys.argv) != 2:  # noqa: PLR2004  (script name and one argument)
        sys.exit(__doc__)
    try:
        chosen = tags(sys.argv[1], sys.stdin.read().splitlines())
    except ValueError as error:
        sys.exit(f"image_tags: {error}")
    sys.stdout.write("".join(f"{tag}\n" for tag in chosen))


if __name__ == "__main__":
    main()
