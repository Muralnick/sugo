"""Run Docling on documents in its worker process and collect their pages (ADR-071, ADR-072).

Outside a ``warm_docling()`` block, a worker reads one document and exits.
Inside one, as the shell, the web UI, the MCP server and multi-file
conversions use it, one worker per Sugo process stays loaded between
documents: it is replaced after any failure and after
``DOCLING_RECYCLE_DOCUMENTS`` documents, and stopped after
``DOCLING_IDLE_S`` without work, which returns its memory (ADR-072 §2).

Frames are validated twice: against the protocol, then as IR pages. A
worker that stalls, crashes, sends something invalid or reports a failure
stops the conversion with an error: a `normal` result is never silently a
partial one.
"""

import contextlib
import importlib.util
import threading
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import ClassVar

from sugo.core.constants import (
    DOCLING_IDLE_S,
    DOCLING_LOAD_TIMEOUT_S,
    DOCLING_PAGE_TIMEOUT_S,
    DOCLING_RECYCLE_DOCUMENTS,
)
from sugo.core.models import Page
from sugo.extractors.docling.protocol import (
    MAX_MESSAGE_BYTES,
    Opened,
    PageRead,
    Refused,
    parse_message,
)
from sugo.extractors.worker import ProtocolError, WorkerError, WorkerProcess, module_command
from sugo.i18n import gettext as _

WORKER_COMMAND: tuple[str, ...] = module_command("sugo.extractors.docling.worker")


class NormalLevelMissingError(RuntimeError):
    """The `normal` level was asked for, but Docling is not installed."""

    code: ClassVar[str] = "LEVEL_MISSING"


class NormalFailedError(RuntimeError):
    """Docling could not read the document, or its worker failed."""

    code: ClassVar[str] = "NORMAL_FAILED"


def docling_installed() -> bool:
    """Whether the `normal` extra is installed, without importing it."""
    return importlib.util.find_spec("docling") is not None


def extract_docling(
    data: bytes,
    *,
    kind: str,
    page_count: int,
    artifacts: Path,
    worker: Sequence[str] = WORKER_COMMAND,
    load_timeout: float = DOCLING_LOAD_TIMEOUT_S,
    page_timeout: float = DOCLING_PAGE_TIMEOUT_S,
) -> list[Page]:
    """The pages of a document as Docling reads them, in order.

    Uses the warm worker inside ``warm_docling()``; otherwise a worker of its own.

    Args:
        data: The file's bytes.
        kind: ``pdf``.
        page_count: Pages the document has, for the time limit.
        artifacts: The folder holding Docling's models (ADR-071 §2).

    Raises:
        NormalLevelMissingError: If the worker cannot import Docling.
        NormalFailedError: If Docling or its worker failed.
    """
    shared = _shared_worker() if tuple(worker) == WORKER_COMMAND else None
    if shared is not None:
        return shared.read(data, kind=kind, page_count=page_count, artifacts=artifacts)
    one_off = DoclingWorker(
        worker=worker, load_timeout=load_timeout, page_timeout=page_timeout, idle_s=None
    )
    try:
        return one_off.read(data, kind=kind, page_count=page_count, artifacts=artifacts)
    finally:
        one_off.close()


class DoclingWorker:
    """Docling's worker process, kept loaded for several documents (ADR-072).

    One document at a time; thread-safe. The process is replaced after any
    failure and after ``recycle_after`` documents, and stopped after
    ``idle_s`` seconds without a document (None: never).
    """

    def __init__(
        self,
        *,
        worker: Sequence[str] = WORKER_COMMAND,
        load_timeout: float = DOCLING_LOAD_TIMEOUT_S,
        page_timeout: float = DOCLING_PAGE_TIMEOUT_S,
        recycle_after: int = DOCLING_RECYCLE_DOCUMENTS,
        idle_s: float | None = DOCLING_IDLE_S,
    ) -> None:
        self._command = tuple(worker)
        self._load_timeout = load_timeout
        self._page_timeout = page_timeout
        self._recycle_after = recycle_after
        self._idle_s = idle_s
        self._lock = threading.Lock()
        self._process: WorkerProcess | None = None
        self._artifacts: Path | None = None
        self._documents = 0
        self._timer: threading.Timer | None = None
        # Bumped by every read: an idle timer armed before a read stops nothing.
        self._generation = 0
        # Processes started so far, for tests and diagnostics.
        self.started = 0

    def read(self, data: bytes, *, kind: str, page_count: int, artifacts: Path) -> list[Page]:
        """The pages of one document, read by the warm worker.

        Raises:
            NormalLevelMissingError: If the worker cannot import Docling.
            NormalFailedError: If Docling or its worker failed; the worker is replaced.
        """
        with self._lock:
            self._generation += 1
            self._cancel_timer()
            if (
                self._process is None
                or not self._process.alive()
                or self._artifacts != artifacts
                or self._documents >= self._recycle_after
            ):
                self._stop()
                self._start(kind, artifacts)
            process = self._process
            if process is None:
                raise NormalFailedError(_failed())
            try:
                pages = self._read(process, data, page_count)
            except BaseException:
                # Never reused after a failure (ADR-072 §2).
                self._stop()
                raise
            self._documents += 1
            self._arm_timer()
            return pages

    def close(self) -> None:
        """Stop the worker, if any."""
        with self._lock:
            self._generation += 1
            self._cancel_timer()
            self._stop()

    def _start(self, kind: str, artifacts: Path) -> None:
        self._process = WorkerProcess(
            [*self._command, kind, str(artifacts)], None, max_frame_bytes=MAX_MESSAGE_BYTES
        )
        self._artifacts = artifacts
        self._documents = 0
        self.started += 1

    def _stop(self) -> None:
        if self._process is not None:
            self._process.close()
        self._process = None

    def _read(self, process: WorkerProcess, data: bytes, page_count: int) -> list[Page]:
        # Docling reads the whole file before sending the first page; a fresh
        # worker also loads itself first.
        first_wait = self._page_timeout * max(page_count, 1)
        if self._documents == 0:
            first_wait += self._load_timeout
        pages: list[Page] = []
        process.send(data)
        try:
            message = parse_message(process.frame(first_wait))
            if isinstance(message, Refused):
                if message.code == "LEVEL_MISSING":
                    raise NormalLevelMissingError(_missing())
                raise NormalFailedError(_failed())
            if not isinstance(message, Opened):
                raise NormalFailedError(_failed())
            for _index in range(message.pages):
                page = parse_message(process.frame(self._page_timeout))
                if not isinstance(page, PageRead) or page.page.index != len(pages):
                    raise NormalFailedError(_failed())
                pages.append(page.page)
        except (WorkerError, ProtocolError, OSError):
            raise NormalFailedError(_failed()) from None
        return pages

    def _arm_timer(self) -> None:
        if self._idle_s is None:
            return
        generation = self._generation
        self._timer = threading.Timer(self._idle_s, self._stop_if_idle, args=(generation,))
        self._timer.daemon = True
        self._timer.start()

    def _cancel_timer(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
        self._timer = None

    def _stop_if_idle(self, generation: int) -> None:
        with self._lock:
            if generation == self._generation:
                self._stop()


# One warm worker per Sugo process, while at least one warm_docling() block is open.
_shared_lock = threading.Lock()
_shared: DoclingWorker | None = None
_shared_users = 0


@contextlib.contextmanager
def warm_docling() -> Iterator[None]:
    """Keep one Docling worker loaded between documents while the block runs (ADR-072).

    Costs nothing until a document is read at `normal`. Nested and concurrent
    blocks share the worker; it stops when the last block ends.
    """
    global _shared, _shared_users
    with _shared_lock:
        if _shared is None:
            _shared = DoclingWorker()
        _shared_users += 1
    try:
        yield
    finally:
        with _shared_lock:
            _shared_users -= 1
            ending = _shared if _shared_users == 0 else None
            if ending is not None:
                _shared = None
        if ending is not None:
            ending.close()


def _shared_worker() -> DoclingWorker | None:
    with _shared_lock:
        return _shared


def _missing() -> str:
    return _("The normal level is not installed.")


def _failed() -> str:
    return _("Docling could not read this document.")
