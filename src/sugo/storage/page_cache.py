"""Two-level per-page cache in SQLite, doubling as the page store (ADR-006, ADR-019).

Level one keeps pages as extracted, so OCR is never redone; level two keeps
pages as cleaned, so an unchanged document is not cleaned again. The page
store of a job is level one: an interrupted job resumes because its finished
pages are cache hits.

Pages are stored as their validated JSON, compressed with zlib: never pickle,
since reading a pickle runs code. Everything read back is treated as
untrusted: a record that is too big, does not decompress or fails the IR
validation is dropped and counted as a miss. The cache is regenerable, so a
broken or outdated database is rebuilt from scratch rather than repaired.

Log messages never contain document text, keys or file names (principle 11).
"""

import hashlib
import json
import logging
import shutil
import sqlite3
import tempfile
import time
import zlib
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from functools import cache
from importlib.metadata import version
from pathlib import Path
from types import TracebackType
from typing import Self

from pydantic import ValidationError

from sugo.core.constants import (
    CACHE_BUSY_TIMEOUT_S,
    CACHE_EVICT_TO_SHARE,
    CACHE_MAX_BYTES,
    CACHE_MAX_RECORD_BYTES,
    CACHE_MIN_FREE_BYTES,
)
from sugo.core.models import Page
from sugo.storage.paths import cache_dir, ensure_private_dir

_log = logging.getLogger(__name__)

CACHE_FILE_NAME = "cache.db"
# Bumped when the table layout or the record format changes; an older cache
# is then rebuilt, never migrated, because everything in it is regenerable.
_SCHEMA_VERSION = 1
_SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    level TEXT NOT NULL,
    key BLOB NOT NULL,
    record BLOB NOT NULL,
    size INTEGER NOT NULL,
    last_used REAL NOT NULL,
    PRIMARY KEY (level, key)
);
CREATE INDEX IF NOT EXISTS entries_by_use ON entries (last_used);
"""


class CacheLevel(StrEnum):
    """Which stage of the pipeline a cached page comes from."""

    EXTRACTION = "extraction"
    OUTPUT = "output"


@dataclass(frozen=True)
class CacheStats:
    """Size of the cache, for ``sugo cache stats``."""

    entries: int
    bytes: int


def extraction_key(*, source_sha256: str, page_index: int, engine: str) -> bytes:
    """Key of an extracted page.

    Args:
        source_sha256: SHA-256 of the whole source file. A per-page content
            hash is deferred (ADR-045): a new edition of a document is
            extracted again in full.
        page_index: Index of the page in the source.
        engine: Extraction backend with everything that changes its output:
            engine and model versions, DPI, OCR settings.
    """
    return _digest("extraction", source_sha256, page_index, engine)


def output_key(*, extraction: bytes, cleaning: str) -> bytes:
    """Key of a cleaned page: its extraction key plus the cleaning configuration."""
    return _digest("output", extraction.hex(), cleaning)


def _digest(*parts: str | int) -> bytes:
    # Sugo's own version is part of every key: a fixed extractor or cleaner
    # must not keep serving pages produced by the old code.
    encoded = json.dumps([_sugo_version(), *parts], ensure_ascii=False)
    return hashlib.sha256(encoded.encode()).digest()


@cache
def _sugo_version() -> str:
    return version("sugo")


class PageCache:
    """The page cache of one user, in one SQLite file.

    Several processes may use the same cache: SQLite serialises writers, and
    a process that waits too long skips the cache operation instead of
    failing the job. A database damaged while in use is skipped the same
    way, and ``clear`` (``sugo cache clear``) starts a new one.
    """

    def __init__(
        self,
        path: Path,
        *,
        max_bytes: int = CACHE_MAX_BYTES,
        clock: Callable[[], float] = time.time,
    ) -> None:
        """Open, or create, the cache database at ``path``.

        Raises:
            StorageDirError: If the directory holding ``path`` is not private
                to the user and cannot be made so.
        """
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        self._path = path
        self._max_bytes = max_bytes
        self._clock = clock
        self._temp_dir: tempfile.TemporaryDirectory[str] | None = None
        ensure_private_dir(path.parent)
        self._db = self._open()
        # Summing every record on each write would slow writes as the cache
        # grows, so this process keeps a running total and sums only when it
        # passes the limit. Writes by other processes are seen at that point.
        self._estimated_bytes = self.stats().bytes

    @classmethod
    def default(cls, *, max_bytes: int = CACHE_MAX_BYTES) -> Self:
        """Open the user's persistent cache (``SUGO_CACHE_DIR`` or the platform cache folder)."""
        return cls(cache_dir() / CACHE_FILE_NAME, max_bytes=max_bytes)

    @classmethod
    def ephemeral(cls, *, max_bytes: int = CACHE_MAX_BYTES) -> Self:
        """Open a cache that is deleted when closed (``cache = "ephemeral"``).

        It still holds a large job's pages on disk, so memory does not grow
        with the document. Deleted files may survive on SSDs; full-disk
        encryption is the real protection (ARCHITECTURE §10).
        """
        temp_dir = tempfile.TemporaryDirectory(prefix="sugo-")
        try:
            cache = cls(Path(temp_dir.name) / CACHE_FILE_NAME, max_bytes=max_bytes)
        except BaseException:
            temp_dir.cleanup()
            raise
        cache._temp_dir = temp_dir
        return cache

    def get(self, level: CacheLevel, key: bytes) -> Page | None:
        """Return the cached page, or None if absent, unreadable or invalid."""
        try:
            row = self._db.execute(
                "SELECT record FROM entries WHERE level = ? AND key = ?", (level.value, key)
            ).fetchone()
        except sqlite3.DatabaseError:
            _log.warning("page cache busy or unreadable; reading skipped")
            return None
        if row is None:
            return None
        page = _decode(row[0])
        try:
            with self._db:
                if page is None:
                    _log.warning("dropped an invalid page cache entry")
                    self._db.execute(
                        "DELETE FROM entries WHERE level = ? AND key = ?", (level.value, key)
                    )
                else:
                    self._db.execute(
                        "UPDATE entries SET last_used = ? WHERE level = ? AND key = ?",
                        (self._clock(), level.value, key),
                    )
        except sqlite3.DatabaseError:
            # A busy writer only delays the LRU bookkeeping.
            _log.warning("page cache busy; usage time not updated")
        return page

    def put(self, level: CacheLevel, key: bytes, page: Page) -> None:
        """Store a page, then evict the least recently used ones past the size limit.

        Skipped, with a warning, when the disk is nearly full or another
        process holds the cache for too long: the job goes on without it.
        """
        record = zlib.compress(page.model_dump_json().encode())
        if shutil.disk_usage(self._path.parent).free - len(record) < CACHE_MIN_FREE_BYTES:
            _log.warning("little free disk space; page not cached")
            return
        try:
            with self._db:
                self._db.execute(
                    "INSERT OR REPLACE INTO entries VALUES (?, ?, ?, ?, ?)",
                    (level.value, key, record, len(record), self._clock()),
                )
            self._estimated_bytes += len(record)
            if self._estimated_bytes > self._max_bytes:
                if self.stats().bytes > self._max_bytes:
                    self.evict(int(self._max_bytes * CACHE_EVICT_TO_SHARE))
                self._estimated_bytes = self.stats().bytes
        except sqlite3.DatabaseError:
            _log.warning("page cache busy or unwritable; page not cached")

    def stats(self) -> CacheStats:
        """Return how many pages the cache holds and how many bytes they take."""
        entries, size = self._db.execute(
            "SELECT COUNT(*), COALESCE(SUM(size), 0) FROM entries"
        ).fetchone()
        return CacheStats(entries=entries, bytes=size)

    def evict(self, max_bytes: int) -> int:
        """Remove least recently used pages until at most ``max_bytes`` remain; return how many."""
        total = self.stats().bytes
        doomed: list[tuple[str, bytes]] = []
        rows = self._db.execute(
            "SELECT level, key, size FROM entries ORDER BY last_used, level, key"
        )
        for level, key, size in rows:
            if total <= max_bytes:
                break
            doomed.append((level, key))
            total -= size
        with self._db:
            self._db.executemany("DELETE FROM entries WHERE level = ? AND key = ?", doomed)
        return len(doomed)

    def purge(self, older_than_s: float) -> int:
        """Remove pages unused for longer than ``older_than_s`` seconds (``retention_days``)."""
        with self._db:
            cursor = self._db.execute(
                "DELETE FROM entries WHERE last_used < ?", (self._clock() - older_than_s,)
            )
        return cursor.rowcount

    def verify(self) -> int:
        """Drop every entry that no longer reads back as a valid page; return how many."""
        broken = [
            (level, key)
            for level, key, record in self._db.execute("SELECT level, key, record FROM entries")
            if _decode(record) is None
        ]
        with self._db:
            self._db.executemany("DELETE FROM entries WHERE level = ? AND key = ?", broken)
        return len(broken)

    def clear(self) -> None:
        """Remove every page by starting a new database; also repairs a damaged one."""
        self._db.close()
        self._remove_files()
        self._db = self._connect()
        self._estimated_bytes = 0

    def close(self) -> None:
        """Close the database; an ephemeral cache is deleted."""
        self._db.close()
        if self._temp_dir is not None:
            self._temp_dir.cleanup()
            self._temp_dir = None

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def _open(self) -> sqlite3.Connection:
        try:
            return self._connect()
        except sqlite3.DatabaseError:
            # Not a database, damaged, or from an incompatible Sugo: the cache
            # is regenerable, so it starts again empty.
            _log.warning("page cache unreadable; starting a new one")
            self._remove_files()
            return self._connect()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self._path, timeout=CACHE_BUSY_TIMEOUT_S, isolation_level=None)
        try:
            # A file planted in the cache directory cannot use triggers or
            # views to run functions SQLite marks unsafe.
            db.execute("PRAGMA trusted_schema = OFF")
            db.execute("PRAGMA journal_mode = WAL")
            db.execute("PRAGMA synchronous = NORMAL")
            row = db.execute("PRAGMA user_version").fetchone()
            if row[0] not in (0, _SCHEMA_VERSION):
                db.execute("DROP TABLE IF EXISTS entries")
            db.executescript(_SCHEMA)
            db.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
            # Autocommit mode above; "with db" then wraps each change in a transaction.
            db.isolation_level = "DEFERRED"
        except BaseException:
            db.close()
            raise
        return db

    def _remove_files(self) -> None:
        for suffix in ("", "-wal", "-shm"):
            self._path.with_name(self._path.name + suffix).unlink(missing_ok=True)


def _decode(record: object) -> Page | None:
    if not isinstance(record, bytes):
        return None
    inflater = zlib.decompressobj()
    try:
        raw = inflater.decompress(record, CACHE_MAX_RECORD_BYTES)
    except zlib.error:
        return None
    # Data left over means the record inflates past the limit, or carries trailing bytes.
    if inflater.unconsumed_tail or inflater.unused_data or not inflater.eof:
        return None
    try:
        return Page.model_validate_json(raw)
    except ValidationError:
        return None
