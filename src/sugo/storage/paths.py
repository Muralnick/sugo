"""Where Sugo keeps regenerable files, on Linux, Windows and macOS (ARCHITECTURE §10).

The cache holds document text, so its directory is private to the user:
created owner-only, tightened if it is not, and refused if it belongs to
someone else or is a symbolic link (ADR-019, ADR-045).
"""

import os
import stat
from pathlib import Path

import platformdirs

# Overrides the cache location, e.g. for a Docker volume (ARCHITECTURE §10).
CACHE_DIR_ENV = "SUGO_CACHE_DIR"


class StorageDirError(RuntimeError):
    """A storage directory exists but is not safe to use."""


def cache_dir() -> Path:
    """Return the cache directory, without creating it."""
    override = os.environ.get(CACHE_DIR_ENV)
    if override:
        return Path(override).expanduser().absolute()
    return Path(platformdirs.user_cache_dir("sugo", appauthor=False))


def ensure_private_dir(path: Path) -> Path:
    """Create ``path`` if needed and make sure only the current user can use it.

    Raises:
        StorageDirError: If the path is a symbolic link, not a directory, or
            (on Linux and macOS) owned by another user.
    """
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.lstat()
    # A link could point the cache, and so document text, anywhere.
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise StorageDirError("storage path is not a plain directory")
    # Windows has no POSIX owners or modes; a profile folder is private by
    # default there, and this is documented in ADR-045.
    if os.name == "posix":
        if info.st_uid != os.getuid():
            raise StorageDirError("storage directory belongs to another user")
        if stat.S_IMODE(info.st_mode) & 0o077:
            path.chmod(0o700)
    return path
