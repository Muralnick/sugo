"""Which files an agent may read: inside an allowed root, never an excluded one.

An agent can be tricked by the documents it reads into asking for
``~/.ssh/id_ed25519`` (THREAT_MODEL D). Every path is therefore resolved,
symbolic links included, and checked against the roots the user gave to
``sugo mcp --root`` **before** Sugo even looks whether the file exists, so
an agent cannot probe the rest of the disk. Files and folders that hold keys
and passwords are refused everywhere, whatever the roots (principle 7).
"""

import fnmatch
from dataclasses import dataclass
from pathlib import Path

from sugo.core.constants import (
    MCP_EXCLUDED_DIRS,
    MCP_EXCLUDED_FILES,
    MCP_EXCLUDED_PATTERNS,
    MCP_MAX_PATH_CHARS,
)
from sugo.ports.cli.errors import CliError, ExitCode


@dataclass(frozen=True)
class Allowed:
    """A file an agent may read."""

    path: Path
    # The path relative to its root, e.g. "contracts/a.pdf": the document's
    # source name, without the user's home folder in it.
    source: str


def is_excluded(path: Path) -> bool:
    """True if any part of the path is a folder or file that holds secrets."""
    for part in (part.casefold() for part in path.parts):
        if part in MCP_EXCLUDED_DIRS or part in MCP_EXCLUDED_FILES:
            return True
        if any(fnmatch.fnmatchcase(part, pattern) for pattern in MCP_EXCLUDED_PATTERNS):
            return True
    return False


class Roots:
    """The allowed roots, resolved once when the server starts."""

    def __init__(self, roots: list[Path]) -> None:
        if not roots:
            raise ValueError("at least one allowed root is needed")
        self._roots = tuple(root.resolve(strict=True) for root in roots)
        if any(is_excluded(root) for root in self._roots):
            raise ValueError("an allowed root is inside a folder that holds secrets")

    def check(self, raw: str) -> Allowed:
        """Return the file ``raw`` names if an agent may read it.

        A relative path is taken from each root in turn.

        Raises:
            CliError: PATH_NOT_ALLOWED, PATH_EXCLUDED or FILE_UNREADABLE.
        """
        if not raw or len(raw) > MCP_MAX_PATH_CHARS or "\x00" in raw:
            raise _not_allowed()
        given = Path(raw)
        candidates = [given] if given.is_absolute() else [root / given for root in self._roots]
        inside = False
        for candidate in candidates:
            # Not strict: whether the file exists is only checked inside a root.
            resolved = candidate.resolve(strict=False)
            root = next((root for root in self._roots if resolved.is_relative_to(root)), None)
            if root is None:
                continue
            inside = True
            if is_excluded(resolved):
                raise CliError(
                    code="PATH_EXCLUDED",
                    message="This file is in a location Sugo never reads for agents.",
                    exit_code=ExitCode.SECURITY,
                    hint="Keys, tokens and password stores are always excluded.",
                )
            if not resolved.is_file():
                if len(candidates) > 1 and not resolved.exists():
                    continue
                raise CliError(
                    code="FILE_UNREADABLE",
                    message="No such file, or not a regular file.",
                    exit_code=ExitCode.ERROR,
                )
            return Allowed(path=resolved, source=resolved.relative_to(root).as_posix())
        if inside:
            raise CliError(
                code="FILE_UNREADABLE",
                message="No such file in the allowed roots.",
                exit_code=ExitCode.ERROR,
            )
        raise _not_allowed()


def _not_allowed() -> CliError:
    return CliError(
        code="PATH_NOT_ALLOWED",
        message="This path is outside the folders Sugo was allowed to read.",
        exit_code=ExitCode.SECURITY,
        hint="Ask the user to add its folder with: sugo mcp --root FOLDER",
    )
