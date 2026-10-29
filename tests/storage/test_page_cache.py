"""Tests for the page cache: round trips, keys, untrusted records, eviction and privacy."""

import os
import sqlite3
import stat
import zlib
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest

from sugo.core.constants import CACHE_MAX_RECORD_BYTES
from sugo.core.models import (
    BBox,
    Block,
    BlockFlag,
    BlockType,
    Page,
    PageOrigin,
    Style,
    Table,
    TableCell,
)
from sugo.storage import page_cache
from sugo.storage.page_cache import (
    CacheLevel,
    CacheUnavailableError,
    PageCache,
    extraction_key,
    output_key,
)
from sugo.storage.paths import CACHE_DIR_ENV, StorageDirError, cache_dir, ensure_private_dir

SHA = "0" * 64
EXTRACTION = CacheLevel.EXTRACTION
OUTPUT = CacheLevel.OUTPUT


def page(index: int = 0, text: str = "Hello") -> Page:
    return Page(
        index=index,
        width=595,
        height=842,
        origin=PageOrigin.NATIVE,
        blocks=(Block(id="b0", type=BlockType.PARAGRAPH, text=text, origin_engine="t"),),
    )


def key(index: int = 0) -> bytes:
    return extraction_key(source_sha256=SHA, page_index=index, engine="pymupdf")


DAY = 24 * 3600


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def cache(tmp_path: Path) -> Iterator[PageCache]:
    with PageCache(tmp_path / "cache" / "cache.db") as opened:
        yield opened


def raw_insert(cache: PageCache, record: bytes, k: bytes = b"k") -> None:
    db = sqlite3.connect(cache._path)
    with db:
        db.execute("INSERT INTO entries VALUES (?, ?, ?, ?, ?)", ("extraction", k, record, 1, 0.0))
    db.close()


def test_page_round_trips_with_every_field(cache: PageCache) -> None:
    rich = Page(
        index=3,
        width=595.5,
        height=842,
        rotation=90,
        origin=PageOrigin.OCR,
        blocks=(
            Block(
                id="t",
                type=BlockType.TABLE,
                bbox=BBox(x0=0.1, y0=0.2, x1=0.9, y1=0.3),
                style=Style(font_size=9.5, bold=True),
                table=Table(
                    n_rows=1, n_cols=2, cells=(TableCell(row=0, col=0, text="a"),), header_rows=1
                ),
                origin_engine="rapidocr",
                confidence=0.75,
                flags=(BlockFlag.LOW_AGREEMENT,),
            ),
            Block(id="x", type=BlockType.PARAGRAPH, text="gone", origin_engine="t").mark_removed(
                "ui_chrome", "reason"
            ),
        ),
    )
    cache.put(EXTRACTION, key(3), rich)
    assert cache.get(EXTRACTION, key(3)) == rich


def test_levels_are_separate(cache: PageCache) -> None:
    cache.put(EXTRACTION, key(), page(text="raw"))
    assert cache.get(OUTPUT, key()) is None
    cache.put(OUTPUT, key(), page(text="clean"))
    assert cache.get(EXTRACTION, key()) == page(text="raw")
    assert cache.get(OUTPUT, key()) == page(text="clean")


def test_missing_page_is_none(cache: PageCache) -> None:
    assert cache.get(EXTRACTION, key()) is None


def test_keys_depend_on_every_input(monkeypatch: pytest.MonkeyPatch) -> None:
    base = extraction_key(source_sha256=SHA, page_index=0, engine="pymupdf")
    assert base == extraction_key(source_sha256=SHA, page_index=0, engine="pymupdf")
    others = {
        extraction_key(source_sha256="1" * 64, page_index=0, engine="pymupdf"),
        extraction_key(source_sha256=SHA, page_index=1, engine="pymupdf"),
        extraction_key(source_sha256=SHA, page_index=0, engine="rapidocr"),
    }
    assert base not in others
    assert len(others) == 3
    assert output_key(extraction=base, cleaning="a") != output_key(extraction=base, cleaning="b")
    assert output_key(extraction=base, cleaning="a") != base
    # Changed Sugo code never reuses pages made by the old code.
    monkeypatch.setattr(page_cache, "_code_fingerprint", lambda: "changed code")
    assert extraction_key(source_sha256=SHA, page_index=0, engine="pymupdf") != base


@pytest.mark.parametrize(
    "record",
    [
        b"not zlib",
        zlib.compress(b"{not json"),
        zlib.compress(b'{"index": -1, "width": 1, "height": 1, "origin": "native"}'),
        zlib.compress(page().model_dump_json().encode()) + b"trailing",
        zlib.compress(page().model_dump_json().encode())[:-4],
        # Inflates past the record limit: a compression bomb.
        zlib.compress(b" " * (CACHE_MAX_RECORD_BYTES + 1)),
    ],
    ids=["garbage", "bad-json", "invalid-page", "trailing", "truncated", "bomb"],
)
def test_untrusted_records_are_dropped(cache: PageCache, record: bytes) -> None:
    raw_insert(cache, record)
    assert cache.get(EXTRACTION, b"k") is None
    assert cache.stats().entries == 0


def test_verify_drops_only_broken_entries(cache: PageCache) -> None:
    cache.put(EXTRACTION, key(), page())
    raw_insert(cache, b"garbage")
    assert cache.verify() == 1
    assert cache.get(EXTRACTION, key()) == page()


def test_file_that_is_not_a_database_is_replaced(tmp_path: Path) -> None:
    path = tmp_path / "cache.db"
    path.write_bytes(b"this is not sqlite" * 100)
    with PageCache(path) as cache:
        cache.put(EXTRACTION, key(), page())
        assert cache.get(EXTRACTION, key()) == page()


def test_cache_from_another_schema_version_is_rebuilt(tmp_path: Path) -> None:
    path = tmp_path / "cache.db"
    db = sqlite3.connect(path)
    db.executescript("CREATE TABLE entries (x); PRAGMA user_version = 99;")
    db.close()
    with PageCache(path) as cache:
        cache.put(EXTRACTION, key(), page())
        assert cache.stats().entries == 1


def test_least_recently_used_pages_are_evicted(tmp_path: Path) -> None:
    clock = Clock()
    # Records differ by a byte or so; three always fit, four never do.
    size = max(len(zlib.compress(page(i).model_dump_json().encode())) for i in range(4))
    with PageCache(tmp_path / "cache.db", max_bytes=3 * size + 2, clock=clock) as cache:
        for index in range(3):
            clock.now += 1
            cache.put(EXTRACTION, key(index), page(index))
        # Two days later: page 0 is read again, then a new page is written.
        clock.now += 2 * DAY
        cache.get(EXTRACTION, key(0))
        cache.put(EXTRACTION, key(3), page(3))
        kept = [i for i in range(4) if cache.get(EXTRACTION, key(i)) is not None]
    # Over the limit: down to 90% of it, oldest first (pages 1, then 2).
    assert kept == [0, 3]


def test_pages_used_today_are_never_evicted(tmp_path: Path) -> None:
    # A job larger than the cache must find all its pages in its later passes.
    with PageCache(tmp_path / "cache.db", max_bytes=500) as cache:
        for index in range(10):
            cache.put(EXTRACTION, key(index), page(index))
        assert all(cache.get(EXTRACTION, key(i)) == page(i) for i in range(10))
        assert cache.stats().bytes > 500


def test_reading_a_recent_page_does_not_write(cache: PageCache) -> None:
    cache.put(EXTRACTION, key(), page())
    statements: list[str] = []
    cache._db.set_trace_callback(statements.append)
    assert cache.get(EXTRACTION, key()) == page()
    assert not any(s.startswith(("UPDATE", "DELETE", "BEGIN")) for s in statements)


def test_purge_removes_pages_unused_for_too_long(tmp_path: Path) -> None:
    clock = Clock()
    with PageCache(tmp_path / "cache.db", clock=clock) as cache:
        cache.put(EXTRACTION, key(0), page(0))
        clock.now += 100
        cache.put(EXTRACTION, key(1), page(1))
        assert cache.purge(older_than_s=50) == 1
        assert cache.get(EXTRACTION, key(0)) is None
        assert cache.get(EXTRACTION, key(1)) == page(1)


def test_clear_empties_the_cache(cache: PageCache) -> None:
    cache.put(EXTRACTION, key(), page())
    cache.clear()
    assert cache.stats().entries == 0
    cache.put(EXTRACTION, key(), page())
    assert cache.stats().entries == 1


def test_nearly_full_disk_skips_caching(cache: PageCache, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(page_cache.shutil, "disk_usage", lambda _: SimpleNamespace(free=1024))
    cache.put(EXTRACTION, key(), page())
    assert cache.stats().entries == 0


def test_busy_cache_is_skipped_not_fatal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(page_cache, "CACHE_BUSY_TIMEOUT_S", 0.05)
    path = tmp_path / "cache.db"
    with PageCache(path) as cache:
        other = sqlite3.connect(path, isolation_level=None)
        other.execute("BEGIN IMMEDIATE")  # Another process is writing.
        try:
            cache.put(EXTRACTION, key(), page())
        finally:
            other.execute("ROLLBACK")
            other.close()
        assert cache.get(EXTRACTION, key()) is None
        cache.put(EXTRACTION, key(), page())
        assert cache.get(EXTRACTION, key()) == page()


def test_ephemeral_cache_is_deleted_on_close() -> None:
    cache = PageCache.ephemeral()
    directory = cache._path.parent
    cache.put(EXTRACTION, key(), page())
    assert cache.get(EXTRACTION, key()) == page()
    cache.close()
    assert not directory.exists()


def test_default_cache_honours_the_environment_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(CACHE_DIR_ENV, str(tmp_path / "sugo-cache"))
    assert cache_dir() == tmp_path / "sugo-cache"
    with PageCache.default() as cache:
        cache.put(EXTRACTION, key(), page())
    assert (tmp_path / "sugo-cache" / "cache.db").is_file()


def test_default_cache_dir_is_per_user_without_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(CACHE_DIR_ENV, raising=False)
    # platformdirs ends the path in "sugo" on Linux and macOS, in "sugo\Cache" on Windows.
    assert "sugo" in cache_dir().parts


@pytest.mark.skipif(os.name != "posix", reason="POSIX permissions")
def test_cache_dir_is_private(tmp_path: Path) -> None:
    created = ensure_private_dir(tmp_path / "new" / "cache")
    assert stat.S_IMODE(created.stat().st_mode) == 0o700
    loose = tmp_path / "loose"
    loose.mkdir(mode=0o755)
    loose.chmod(0o755)
    ensure_private_dir(loose)
    assert stat.S_IMODE(loose.stat().st_mode) == 0o700


@pytest.mark.skipif(os.name != "posix", reason="POSIX symbolic links")
def test_cache_dir_symlink_is_refused(tmp_path: Path) -> None:
    (tmp_path / "elsewhere").mkdir()
    (tmp_path / "link").symlink_to(tmp_path / "elsewhere")
    with pytest.raises(StorageDirError, match="not a plain directory"):
        ensure_private_dir(tmp_path / "link")
    with pytest.raises(StorageDirError):
        PageCache(tmp_path / "link" / "cache.db")


def test_code_fingerprint_covers_sugo_source() -> None:
    fingerprint = page_cache._code_fingerprint()
    assert len(fingerprint) == 64
    assert fingerprint == page_cache._code_fingerprint()


def test_cache_opens_while_another_process_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(page_cache, "CACHE_BUSY_TIMEOUT_S", 0.05)
    path = tmp_path / "cache.db"
    with PageCache(path) as first:
        first.put(EXTRACTION, key(), page())
    other = sqlite3.connect(path, isolation_level=None)
    other.execute("BEGIN IMMEDIATE")  # Another process is writing.
    try:
        # Opening a current cache only reads, so it never waits for writers.
        with PageCache(path) as second:
            assert second.get(EXTRACTION, key()) == page()
    finally:
        other.execute("ROLLBACK")
        other.close()


def test_locked_cache_is_left_alone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(page_cache, "CACHE_BUSY_TIMEOUT_S", 0.05)
    path = tmp_path / "cache.db"
    # A database another process holds exclusively, before Sugo set it up.
    other = sqlite3.connect(path, isolation_level=None)
    other.execute("CREATE TABLE theirs (x)")
    other.execute("BEGIN EXCLUSIVE")
    other.execute("INSERT INTO theirs VALUES (1)")
    try:
        with pytest.raises(CacheUnavailableError):
            PageCache(path)
    finally:
        other.execute("COMMIT")
    # Nothing was deleted: the other process's data is still there.
    assert other.execute("SELECT x FROM theirs").fetchall() == [(1,)]
    other.close()


def test_clear_keeps_the_file_other_processes_use(tmp_path: Path) -> None:
    path = tmp_path / "cache.db"
    with PageCache(path) as job, PageCache(path) as command:
        job.put(EXTRACTION, key(0), page(0))
        inode = path.stat().st_ino
        command.clear()
        assert path.stat().st_ino == inode
        assert job.get(EXTRACTION, key(0)) is None
        job.put(EXTRACTION, key(1), page(1))
        assert command.get(EXTRACTION, key(1)) == page(1)


def test_deleted_pages_give_disk_space_back(tmp_path: Path) -> None:
    path = tmp_path / "cache.db"
    big = page(text=os.urandom(200_000).hex())
    with PageCache(path) as cache:
        for index in range(10):
            cache.put(EXTRACTION, key(index), big)
        full = path.stat().st_size + path.with_name("cache.db-wal").stat().st_size
        cache.purge(older_than_s=-1)
        empty = path.stat().st_size + path.with_name("cache.db-wal").stat().st_size
    assert empty < full / 10


def test_page_too_large_to_read_back_is_not_stored(
    cache: PageCache, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(page_cache, "CACHE_MAX_RECORD_BYTES", 100)
    cache.put(EXTRACTION, key(), page())
    assert cache.stats().entries == 0


def test_unreachable_disk_skips_caching(cache: PageCache, monkeypatch: pytest.MonkeyPatch) -> None:
    def gone(_: Path) -> None:
        raise FileNotFoundError

    monkeypatch.setattr(page_cache.shutil, "disk_usage", gone)
    cache.put(EXTRACTION, key(), page())
    assert cache.stats().entries == 0


def test_size_queries_never_read_records(cache: PageCache) -> None:
    plans = [
        " ".join(str(row[-1]) for row in cache._db.execute("EXPLAIN QUERY PLAN " + query))
        for query in (
            "SELECT COUNT(*), SUM(size) FROM entries INDEXED BY entries_by_use",
            "SELECT level, key, size FROM entries INDEXED BY entries_by_use"
            " WHERE last_used < 0 ORDER BY last_used, level, key",
        )
    ]
    assert all("COVERING INDEX entries_by_use" in plan for plan in plans), plans
