"""What ``sugo uninstall`` and ``sugo cache clear`` delete, and how (ADR-066).

Sugo leaves two things on disk: the user's settings file and the page
cache, which holds text of converted documents. This module finds them and
deletes them; the commands in ``app`` ask and report. Only Sugo's own files
are deleted, never a folder with anything else in it, and no other program
is run: removing the package is left to the tool that installed it, whose
command is only shown.
"""

import stat
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from sugo import i18n
from sugo.config.settings import printable
from sugo.core.constants import DISTRIBUTION_NAME
from sugo.i18n import gettext as _
from sugo.ports.errors import ExitCode, PortError
from sugo.storage.page_cache import CacheUnavailableError, cache_files, delete_cache
from sugo.storage.paths import StorageDirError, cache_dir, check_plain_dir


@dataclass(frozen=True)
class Found:
    """Sugo's files on this computer; None for what is not there."""

    settings: Path | None
    cache: Path | None
    cache_bytes: int


def find() -> Found:
    """Look for the settings file and the cache, changing nothing."""
    from sugo.config.settings import user_config_path

    settings = user_config_path()
    folder = cache_dir()
    sizes = [size for size in map(_size, cache_files(folder)) if size is not None]
    return Found(
        settings=settings if _size(settings) is not None else None,
        cache=folder if sizes else None,
        cache_bytes=sum(sizes),
    )


def clear_cache() -> Path | None:
    """Delete the page cache, and its folder if nothing else is in it.

    Returns:
        The folder, if it was kept because it holds other files.

    Raises:
        PortError: CACHE_IN_USE, STORAGE_REFUSED or DELETE_FAILED; then
            nothing in the cache was deleted, except for DELETE_FAILED.
    """
    folder = cache_dir()
    refused = _(
        "Not deleted: the cache folder or a file in it is a link, not plain, "
        "or belongs to another user."
    )
    with _deleting(folder, refused=refused):
        removed = delete_cache(folder)
    return folder if not removed and folder.is_dir() else None


def delete_settings() -> None:
    """Delete the settings file, and its folder if nothing else is in it.

    A file that is a link is removed, never the file it points to; a folder
    that is a link, or not the user's, is refused, since deleting through it
    would delete a file somewhere else.

    Raises:
        PortError: STORAGE_REFUSED if the file or its folder is not plain,
            DELETE_FAILED if the system refuses.
    """
    from sugo.config.settings import user_config_path

    path = user_config_path()
    refused = _("Not deleted: the settings file or its folder is not plain, or not yours.")
    with _deleting(path, refused=refused):
        try:
            check_plain_dir(path.parent)
        except FileNotFoundError:
            return
        try:
            mode: int | None = path.lstat().st_mode
        except FileNotFoundError:
            mode = None
        if mode is not None:
            if not (stat.S_ISREG(mode) or stat.S_ISLNK(mode)):
                raise StorageDirError("settings path is not a plain file")
            path.unlink()
        # On Windows the cache folder is inside this one; it is gone by now.
        if not any(path.parent.iterdir()):
            path.parent.rmdir()


def removal_command(prefix: Path | None = None) -> str:
    """The command that removes the package, guessed from where Sugo runs.

    The guess reads the path of the Python environment: uv keeps tools in a
    ``tools`` folder and uvx runs from its cache's ``archive-v0``, pipx keeps
    each app in ``venvs``. Anything else gets pip's command.
    """
    parts = {part.lower() for part in (prefix or Path(sys.prefix)).parts}
    if {"uv", "tools"} <= parts:
        return f"uv tool uninstall {DISTRIBUTION_NAME}"
    if {"uv", "archive-v0"} <= parts:
        return f"uv cache clean {DISTRIBUTION_NAME}"
    if {"pipx", "venvs"} <= parts:
        return f"pipx uninstall {DISTRIBUTION_NAME}"
    return f"pip uninstall {DISTRIBUTION_NAME}"


def _size(path: Path) -> int | None:
    """The size of ``path`` itself, a link not followed; None if it is not there."""
    try:
        return path.lstat().st_size
    except OSError:
        return None


@contextmanager
def _deleting(path: Path, *, refused: str) -> Iterator[None]:
    try:
        yield
    except StorageDirError:
        raise PortError(
            code="STORAGE_REFUSED",
            message=refused,
            exit_code=ExitCode.SECURITY,
            hint=_("Check it by hand: Sugo deletes only plain files that are yours."),
            details={"path": path.as_posix()},
        ) from None
    except CacheUnavailableError:
        raise PortError(
            code="CACHE_IN_USE",
            message=_("The cache is in use by another Sugo: nothing was deleted."),
            exit_code=ExitCode.ERROR,
            hint=_("Close Sugo in other windows and AI agents, then try again."),
        ) from None
    except OSError as error:
        name = printable(str(error.filename or path))
        raise PortError(
            code="DELETE_FAILED",
            message=_("Could not delete {path}: {reason}").format(
                path=name, reason=i18n.os_reason(error)
            ),
            exit_code=ExitCode.ERROR,
        ) from error
