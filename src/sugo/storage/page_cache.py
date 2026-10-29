"""Two-level per-page cache in SQLite, doubling as the page store (ADR-006, ADR-019).

Level one keeps pages as extracted, so OCR is never redone; level two keeps
pages as cleaned, so an unchanged document is not cleaned again. The page
store of a job is level one: an interrupted job resumes because its finished
pages are cache hits.

Pages are stored as their validated JSON, compressed with zlib: never pickle,
since reading a pickle runs code. Everything read back is treated as
untrusted: a record that is too big, does not decompress or fails the IR
validation is dropped and counted as a miss. The cache is regenerable, so a
damaged or outdated database is rebuilt from scratch rather than repaired;
one that is merely locked by another process is left alone.

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
from pathlib import Path
from types import TracebackType
from typing import Self

from pydantic import ValidationError

import sugo
from sugo.core.constants import (
    CACHE_BUSY_TIMEOUT_S,
    CACHE_EVICT_TO_SHARE,
    CACHE_MAX_BYTES,
    CACHE_MAX_RECORD_BYTES,
    CACHE_MIN_FREE_BYTES,
    CACHE_PROTECT_RECENT_S,
    CACHE_TOUCH_INTERVAL_S,
    CACHE_WAL_LIMIT_BYTES,
)
from sugo.core.models import Page
from sugo.storage.paths import cache_dir, ensure_private_dir

_log = logging.getLogger(__name__)

CACHE_FILE_NAME = "cache.db"
# Bumped when the table layout or the record format changes; an older cache
# is then rebuilt, never migrated, because everything in it is regenerable.
_SCHEMA_VERSION = 1
_SCHEMA = (
    # The record comes last, so reading the other columns never follows a
    # record into its overflow pages.
    "CREATE TABLE entries ("
    " level TEXT NOT NULL, key BLOB NOT NULL, size INTEGER NOT NULL,"
    " last_used REAL NOT NULL, record BLOB NOT NULL, PRIMARY KEY (level, key))",
    # Covers the size total and the eviction order without touching records.
    "CREATE INDEX entries_by_use ON entries (last_used, size, level, key)",
)


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
    encoded = json.dumps([_code_fingerprint(), *parts], ensure_ascii=False)
    return hashlib.sha256(encoded.encode()).digest()


@cache
def _code_fingerprint() -> str:
    """Digest of Sugo's own source code, part of every key.

    Fixed extractors or cleaners must never get pages made by the old code.
    The package version alone would not show it: it changes only on a
    release, and never in a development checkout.
    """
    root = Path(sugo.__file__).parent
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*.py")):
        digest.update(path.relative_to(root).as_posix().encode() + b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


class CacheUnavailableError(RuntimeError):
    """The cache cannot be opened now: locked by another process, or read-only.

    The caller runs the job without a cache; the file is left untouched.
    """


class PageCache:
    """The page cache of one user, in one SQLite file.

    Several processes may use the same cache: SQLite serialises writers, and
    a process that waits too long skips the cache operation instead of
    failing the job. Files are never deleted while the cache may be in use,
    except when SQLite reports them damaged.
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
            CacheUnavailableError: If the database is locked for too long or
                cannot be written.
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
                "SELECT record, last_used FROM entries WHERE level = ? AND key = ?",
                (level.value, key),
            ).fetchone()
        except sqlite3.DatabaseError:
            _log.warning("page cache busy or unreadable; reading skipped")
            return None
        if row is None:
            return None
        record, last_used = row
        page = _decode(record)
        now = self._clock()
        try:
            if page is None:
                _log.warning("dropped an invalid page cache entry")
                with self._db:
                    self._db.execute(
                        "DELETE FROM entries WHERE level = ? AND key = ?", (level.value, key)
                    )
            elif last_used < now - CACHE_TOUCH_INTERVAL_S:
                with self._db:
                    self._db.execute(
                        "UPDATE entries SET last_used = ? WHERE level = ? AND key = ?",
                        (now, level.value, key),
                    )
        except sqlite3.DatabaseError:
            # A busy writer only delays the LRU bookkeeping.
            _log.warning("page cache busy; usage time not updated")
        return page

    def put(self, level: CacheLevel, key: bytes, page: Page) -> bool:
        """Store a page, then evict the least recently used ones past the size limit.

        Skipped, with a warning, when the page is too large to be read back,
        the disk is nearly full or unreachable, or another process holds the
        cache for too long: the job goes on without it.

        Returns:
            Whether the page was stored.
        """
        raw = page.model_dump_json().encode()
        if len(raw) > CACHE_MAX_RECORD_BYTES:
            _log.warning("page too large for the cache; not cached")
            return False
        record = zlib.compress(raw)
        try:
            if shutil.disk_usage(self._path.parent).free - len(record) < CACHE_MIN_FREE_BYTES:
                _log.warning("little free disk space; page not cached")
                return False
            with self._db:
                self._db.execute(
                    "INSERT OR REPLACE INTO entries VALUES (?, ?, ?, ?, ?)",
                    (level.value, key, len(record), self._clock(), record),
                )
            self._estimated_bytes += len(record)
            if self._estimated_bytes > self._max_bytes:
                if self.stats().bytes > self._max_bytes:
                    self.evict(int(self._max_bytes * CACHE_EVICT_TO_SHARE))
                self._estimated_bytes = self.stats().bytes
        except (sqlite3.DatabaseError, OSError):
            _log.warning("page cache busy or unwritable; page not cached")
            return False
        return True

    def stats(self) -> CacheStats:
        """Return how many pages the cache holds and how many bytes they take."""
        # The covering index holds every size, so this never reads the records.
        entries, size = self._db.execute(
            "SELECT COUNT(*), COALESCE(SUM(size), 0) FROM entries INDEXED BY entries_by_use"
        ).fetchone()
        return CacheStats(entries=entries, bytes=size)

    def evict(self, max_bytes: int) -> int:
        """Remove least recently used pages until at most ``max_bytes`` remain; return how many.

        Pages used in the last day are kept, so the cache may stay above
        ``max_bytes`` while a large job is running.
        """
        total = self.stats().bytes
        doomed: list[tuple[str, bytes]] = []
        rows = self._db.execute(
            "SELECT level, key, size FROM entries INDEXED BY entries_by_use"
            " WHERE last_used < ? ORDER BY last_used, level, key",
            (self._clock() - CACHE_PROTECT_RECENT_S,),
        )
        for level, key, size in rows:
            if total <= max_bytes:
                break
            doomed.append((level, key))
            total -= size
        with self._db:
            self._db.executemany("DELETE FROM entries WHERE level = ? AND key = ?", doomed)
        self._reclaim()
        return len(doomed)

    def purge(self, older_than_s: float) -> int:
        """Remove pages unused for longer than ``older_than_s`` seconds (``retention_days``)."""
        with self._db:
            cursor = self._db.execute(
                "DELETE FROM entries WHERE last_used < ?", (self._clock() - older_than_s,)
            )
        self._reclaim()
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
        self._reclaim()
        return len(broken)

    def clear(self) -> None:
        """Remove every page and give the space back; a damaged database is replaced."""
        try:
            with self._db:
                self._db.execute("DELETE FROM entries")
            self._reclaim()
        except sqlite3.OperationalError:
            raise CacheUnavailableError("page cache is busy") from None
        except sqlite3.DatabaseError:
            _log.warning("page cache damaged; starting a new one")
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
        except sqlite3.OperationalError:
            # Locked by another process, or read-only: someone may be using
            # it, so it is left alone and the job runs without a cache.
            raise CacheUnavailableError("page cache is busy or read-only") from None
        except sqlite3.DatabaseError:
            # Not a database, or damaged: the cache is regenerable, so it
            # starts again empty.
            _log.warning("page cache unreadable; starting a new one")
            self._remove_files()
            return self._connect()

    def _connect(self) -> sqlite3.Connection:
        # Autocommit; "with db" or BEGIN opens each transaction explicitly.
        db = sqlite3.connect(self._path, timeout=CACHE_BUSY_TIMEOUT_S, isolation_level=None)
        try:
            # A file planted in the cache directory cannot use triggers or
            # views to run functions SQLite marks unsafe.
            db.execute("PRAGMA trusted_schema = OFF")
            db.execute("PRAGMA synchronous = NORMAL")
            db.execute(f"PRAGMA journal_size_limit = {CACHE_WAL_LIMIT_BYTES}")
            # Opening a current cache only reads; the schema is written once.
            if db.execute("PRAGMA user_version").fetchone()[0] != _SCHEMA_VERSION:
                self._create_schema(db)
            db.isolation_level = "DEFERRED"
        except BaseException:
            db.close()
            raise
        return db

    @staticmethod
    def _create_schema(db: sqlite3.Connection) -> None:
        if db.execute("PRAGMA user_version").fetchone()[0] != 0:
            # An older layout: drop it, then compact so the settings below,
            # which apply only to an empty file, take effect.
            db.execute("DROP TABLE IF EXISTS entries")
            db.execute("VACUUM")
        # Free pages go back to the file system after evictions.
        db.execute("PRAGMA auto_vacuum = INCREMENTAL")
        db.execute("PRAGMA journal_mode = WAL")
        db.execute("BEGIN IMMEDIATE")
        try:
            # Another process may have created it while this one waited.
            if db.execute("PRAGMA user_version").fetchone()[0] != _SCHEMA_VERSION:
                for statement in _SCHEMA:
                    db.execute(statement)
                db.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
            db.execute("COMMIT")
        except BaseException:
            db.execute("ROLLBACK")
            raise

    def _reclaim(self) -> None:
        """Give the space of deleted pages back to the file system."""
        try:
            self._db.execute("PRAGMA incremental_vacuum").fetchall()
            self._db.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchall()
        except sqlite3.OperationalError:
            _log.warning("page cache busy; space not given back yet")

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
