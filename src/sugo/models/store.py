"""Where downloaded models live, how they are checked and removed (ADR-070, ADR-071).

A model's files are kept in ``<cache dir>/models/<folder>/<path>``, inside
the private cache folder (ADR-045), with the paths the registry gives. Every
file is checked against the registry's SHA-256 each time the model is loaded,
like the bundled models (ADR-039): a file changed on disk is refused.
Removing deletes only the files this module knows by name, then empty
folders, never a folder with anything else in it, and follows no links
(ADR-066 §4).

Nothing here touches the network, so every port may ask what is installed.
"""

import hashlib
import os
import stat
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from sugo.models.errors import ModelBusyError, ModelInvalidError
from sugo.models.registry import ModelCard, ModelFile
from sugo.storage.paths import (
    StorageDirError,
    cache_dir,
    check_plain_dir,
    check_private_file,
    ensure_private_dir,
)

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl

MODELS_DIR_NAME = "models"
PART_SUFFIX = ".part"
_HASH_CHUNK_BYTES = 1024 * 1024
# How long a second download of the same model waits for the first.
LOCK_TIMEOUT_S = 15 * 60.0
_LOCK_POLL_S = 0.5


@dataclass(frozen=True)
class Installed:
    """A model whose files are all on disk; their hashes are checked when it is loaded."""

    card: ModelCard
    root: Path

    def path(self, file: ModelFile | None = None) -> Path:
        """Where one of its files is; the first one by default."""
        return file_path(self.card, file or self.card.files[0])


def models_dir() -> Path:
    """The folder that holds every downloaded model, without creating it."""
    return cache_dir() / MODELS_DIR_NAME


def model_dir(card: ModelCard) -> Path:
    """The folder of a model, shared with others of the same ``folder``; not created."""
    return models_dir() / card.folder


def file_path(card: ModelCard, file: ModelFile) -> Path:
    """Where one file of a model goes."""
    return model_dir(card).joinpath(*PurePosixPath(file.path).parts)


def lock_path(card: ModelCard) -> Path:
    """The lock file of a model's downloads."""
    return model_dir(card) / f".{card.id}.lock"


def find(card: ModelCard) -> Installed | None:
    """The installed model, if every file is a plain file of the right size.

    The size check is cheap; the hashes are checked by ``verify`` before loading.
    """
    for file in card.files:
        if not _present(card, file):
            return None
    return Installed(card, model_dir(card))


def verify(installed: Installed) -> Path:
    """Check every file against the registry's SHA-256 and return the model's folder.

    Raises:
        ModelInvalidError: If one does not match, or cannot be read.
    """
    for file in installed.card.files:
        if not file_valid(installed.card, file):
            raise ModelInvalidError(installed.card.id)
    return installed.root


def file_valid(card: ModelCard, file: ModelFile) -> bool:
    """Whether one file is on disk, plain, of the right size and hash."""
    path = file_path(card, file)
    if not _present(card, file):
        return False
    digest = hashlib.sha256()
    try:
        check_private_file(path)
        with path.open("rb") as handle:
            while chunk := handle.read(_HASH_CHUNK_BYTES):
                digest.update(chunk)
    except (OSError, StorageDirError):
        return False
    return digest.hexdigest() == file.sha256


def _present(card: ModelCard, file: ModelFile) -> bool:
    path = file_path(card, file)
    try:
        _check_folders(path)
        info = path.lstat()
    except (OSError, StorageDirError):
        return False
    return stat.S_ISREG(info.st_mode) and info.st_size == file.size


def _check_folders(path: Path) -> None:
    """Check every folder from the file's own up to the cache folder, links included.

    ``lstat`` does not follow the file itself, but it does follow a linked
    folder on the way, which could lead a model file outside the cache. The
    folders checked are the ones ``prepare`` creates private.

    Raises:
        FileNotFoundError: If a folder is missing.
        StorageDirError: If a folder is a link, not a directory, (on Linux
            and macOS) not the user's, or the file is not inside the cache.
    """
    top = cache_dir()
    folder = path.parent
    while True:
        check_plain_dir(folder)
        if folder == top:
            return
        if folder == folder.parent:
            raise StorageDirError("model file is not inside the cache folder")
        folder = folder.parent


def prepare(card: ModelCard) -> Path:
    """Create the model's folders, private to the user, and return its folder.

    Raises:
        StorageDirError: If the cache, models or a model folder is not safe.
    """
    ensure_private_dir(cache_dir())
    ensure_private_dir(models_dir())
    root = ensure_private_dir(model_dir(card))
    for file in card.files:
        folder = root
        for part in PurePosixPath(file.path).parts[:-1]:
            folder = ensure_private_dir(folder / part)
    return root


def remove(card: ModelCard) -> int:
    """Delete the model's files and the folders they leave empty.

    Returns:
        The bytes freed; 0 if nothing was installed.

    Raises:
        StorageDirError: If a folder or file on the way is a link, not plain,
            or not the user's; nothing is deleted then.
        OSError: If the system refuses to delete a file.
    """
    root = model_dir(card)
    try:
        check_plain_dir(root)
    except FileNotFoundError:
        return 0
    known: list[Path] = [lock_path(card)]
    folders: set[Path] = set()
    for file in card.files:
        path = file_path(card, file)
        folder = path.parent
        while folder != root:
            try:
                check_plain_dir(folder)
            except FileNotFoundError:
                break
            folders.add(folder)
            folder = folder.parent
        known += [path, path.with_name(path.name + PART_SUFFIX)]
    for path in known:
        check_private_file(path)
    freed = 0
    for path in known:
        try:
            size = path.lstat().st_size
        except FileNotFoundError:
            continue
        path.unlink()
        if path != lock_path(card):
            freed += size
    # Deepest first, so a parent is empty once its children are gone.
    for folder in sorted(folders, key=lambda f: len(f.parts), reverse=True):
        if folder.is_dir() and not any(folder.iterdir()):
            folder.rmdir()
    if not any(root.iterdir()):
        root.rmdir()
    return freed


@contextmanager
def download_lock(card: ModelCard) -> Iterator[None]:
    """Hold the model's lock: a second download of it waits for the first.

    Raises:
        ModelBusyError: If the lock is not free within ``LOCK_TIMEOUT_S``.
        StorageDirError: If the lock file is a link or not the user's.
    """
    prepare(card)
    path = lock_path(card)
    check_private_file(path)
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        _acquire(descriptor)
        yield
    finally:
        # Closing the file releases the lock on every system.
        os.close(descriptor)


def _acquire(descriptor: int) -> None:
    deadline = time.monotonic() + LOCK_TIMEOUT_S
    while True:
        try:
            if sys.platform == "win32":
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            if time.monotonic() >= deadline:
                raise ModelBusyError("model is being downloaded by another Sugo") from None
            time.sleep(_LOCK_POLL_S)
        else:
            return
