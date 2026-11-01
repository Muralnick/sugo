"""The user's page cache as the CLI and the web UI open it, once per job (ADR-045)."""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sugo.storage.page_cache import PageCache

_log = logging.getLogger(__name__)


@contextmanager
def page_cache(*, enabled: bool) -> Iterator["PageCache | None"]:
    """The user's persistent page cache; None (a temporary one per job) if off or unusable.

    SQLite connections belong to their thread: open it in the thread that converts.
    """
    if not enabled:
        yield None
        return
    from sugo.storage.page_cache import CacheUnavailableError, PageCache
    from sugo.storage.paths import StorageDirError

    try:
        cache = PageCache.default()
    except (CacheUnavailableError, StorageDirError, OSError):
        _log.warning("the page cache is unavailable; using a temporary one")
        yield None
        return
    with cache:
        yield cache
