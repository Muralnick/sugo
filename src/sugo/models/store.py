"""Where downloaded models live, how they are checked and removed (ADR-070).

A model is kept as ``<cache dir>/models/<id>/<sha256><suffix>``, in the
private cache folder (ADR-045). Its name is its hash, so a new version never
overwrites the old one. It is checked against the registry's SHA-256 every
time it is loaded, like the bundled models (ADR-039): a file changed on disk
is refused. Removing deletes only the files this module knows by name, never
a folder with anything else in it, and follows no links (ADR-066 §4).

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
from pathlib import Path

from sugo.models.errors import ModelBusyError, ModelInvalidError
from sugo.models.registry import ModelCard
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
LOCK_FILE_NAME = "download.lock"
PART_SUFFIX = ".part"
_HASH_CHUNK_BYTES = 1024 * 1024
# How long a second download of the same model waits for the first.
LOCK_TIMEOUT_S = 15 * 60.0
_LOCK_POLL_S = 0.5


@dataclass(frozen=True)
class Installed:
    """A model file found on disk; its hash is checked when it is loaded."""

    card: ModelCard
    path: Path


def models_dir() -> Path:
    """The folder that holds every downloaded model, without creating it."""
    return cache_dir() / MODELS_DIR_NAME


def model_dir(card: ModelCard) -> Path:
    """The folder of one model, without creating it."""
    return models_dir() / card.id


def model_path(card: ModelCard) -> Path:
    """Where the model's file is, once installed."""
    return model_dir(card) / (card.sha256 + card.suffix)


def find(card: ModelCard) -> Installed | None:
    """The installed file, if a plain file of the right size is there.

    The size check is cheap; the hash is checked by ``verify`` before loading.
    """
    path = model_path(card)
    try:
        info = path.lstat()
    except OSError:
        return None
    if not stat.S_ISREG(info.st_mode) or info.st_size != card.size:
        return None
    return Installed(card, path)


def verify(installed: Installed) -> Path:
    """Check the file against the registry's SHA-256 and return its path.

    Raises:
        ModelInvalidError: If it does not match, or cannot be read.
    """
    digest = hashlib.sha256()
    try:
        check_private_file(installed.path)
        with installed.path.open("rb") as file:
            while chunk := file.read(_HASH_CHUNK_BYTES):
                digest.update(chunk)
    except (OSError, StorageDirError):
        raise ModelInvalidError(installed.card.id) from None
    if digest.hexdigest() != installed.card.sha256:
        raise ModelInvalidError(installed.card.id)
    return installed.path


def prepare(card: ModelCard) -> Path:
    """Create the model's folder, private to the user, and return it.

    Raises:
        StorageDirError: If the cache, models or model folder is not safe.
    """
    ensure_private_dir(cache_dir())
    ensure_private_dir(models_dir())
    return ensure_private_dir(model_dir(card))


def remove(card: ModelCard) -> int:
    """Delete the model's files and, if then empty, its folder.

    Returns:
        The bytes freed; 0 if nothing was installed.

    Raises:
        StorageDirError: If the folder or a file in it is a link, not plain,
            or not the user's; nothing is deleted then.
        OSError: If the system refuses to delete a file.
    """
    folder = model_dir(card)
    try:
        check_plain_dir(folder)
    except FileNotFoundError:
        return 0
    known = [
        model_path(card),
        folder / (card.sha256 + card.suffix + PART_SUFFIX),
        folder / LOCK_FILE_NAME,
    ]
    for path in known:
        check_private_file(path)
    freed = 0
    for path in known:
        try:
            size = path.lstat().st_size
        except FileNotFoundError:
            continue
        path.unlink()
        if path.name != LOCK_FILE_NAME:
            freed += size
    if not any(folder.iterdir()):
        folder.rmdir()
    return freed


@contextmanager
def download_lock(card: ModelCard) -> Iterator[None]:
    """Hold the model's lock: a second download of it waits for the first.

    Raises:
        ModelBusyError: If the lock is not free within ``LOCK_TIMEOUT_S``.
        StorageDirError: If the lock file is a link or not the user's.
    """
    path = prepare(card) / LOCK_FILE_NAME
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
