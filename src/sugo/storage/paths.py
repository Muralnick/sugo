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
    # A link could point the cache, and so document text, anywhere.
    check_plain_dir(path)
    # Windows has no POSIX owners or modes; a profile folder is private by
    # default there, and this is documented in ADR-045.
    if os.name == "posix" and stat.S_IMODE(path.lstat().st_mode) & 0o077:
        path.chmod(0o700)
    return path


def check_plain_dir(path: Path) -> None:
    """Make sure an existing directory is safe to delete files from, changing nothing (ADR-066).

    Raises:
        FileNotFoundError: If the path does not exist.
        StorageDirError: If the path is a symbolic link, not a directory, or
            (on Linux and macOS) owned by another user.
    """
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise StorageDirError("storage path is not a plain directory")
    if os.name == "posix" and info.st_uid != os.getuid():
        raise StorageDirError("storage directory belongs to another user")


def check_private_file(path: Path) -> None:
    """Make sure an existing file in a private directory cannot leak to another user.

    A directory that was not private when Sugo first used it may already hold
    a link planted by another user: SQLite would follow it and write document
    text into their file (security review F9, 2026-11-02). A missing file is
    fine; SQLite then creates it inside the private directory.

    Raises:
        StorageDirError: If the path is a symbolic link, not a regular file,
            has more than one hard link, or (on Linux and macOS) belongs to
            another user.
    """
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise StorageDirError("storage file is not a plain file")
    if info.st_nlink > 1:
        raise StorageDirError("storage file has other hard links")
    if os.name == "posix" and info.st_uid != os.getuid():
        raise StorageDirError("storage file belongs to another user")
