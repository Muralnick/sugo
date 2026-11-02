"""Read a native or scanned PDF into IR pages, one at a time (ADR-043).

MuPDF never runs in Sugo's own process. The file is checked here first
(size, ``%PDF`` signature, Brotli and indirect stream filters, see
``sugo.extractors.pymupdf.guard``), then handed to a worker process that
parses it and streams back plain data, validated before use
(``sugo.extractors.pymupdf.protocol``).

Each page has a time limit. A page that stalls or crashes the worker is
marked illegible, never dropped, and a fresh worker continues from the next
page; a document that keeps crashing it is refused (ARCHITECTURE §4).

Native pages become blocks through ``sugo.extractors.pymupdf.layout``.
Scanned pages are read with the image OCR pipeline; their invisible text
layer, if any, is kept as a hidden block instead of being trusted.

Pages are yielded in order as they are read, so memory does not grow with
the length of the document (ADR-006).
"""

import contextlib
import hashlib
import queue
import subprocess
import sys
import threading
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import ClassVar

import numpy as np

from sugo.core.constants import (
    MAX_PDF_FILE_BYTES,
    PDF_MAX_WORKER_RESTARTS,
    PDF_OPEN_TIMEOUT_S,
    PDF_PAGE_TIMEOUT_S,
)
from sugo.core.models import Block, BlockFlag, BlockType, Page, PageOrigin
from sugo.extractors.image.extract import extract_image
from sugo.extractors.image.loader import LoadedImage
from sugo.extractors.image.ocr_engine import OcrEngine, bundled_models
from sugo.extractors.pymupdf.guard import raw_problem
from sugo.extractors.pymupdf.layout import ENGINE_NAME, build_blocks, hidden_block
from sugo.extractors.pymupdf.protocol import (
    Message,
    NativePage,
    Opened,
    PageBox,
    PageFailed,
    ProtocolError,
    Refused,
    ScanPage,
    parse_message,
    read_frame,
)

# "-I": isolated mode, so the environment and the current directory cannot
# change which code the worker runs.
WORKER_COMMAND: tuple[str, ...] = (sys.executable, "-I", "-m", "sugo.extractors.pymupdf.worker")
# The PDF signature may follow a few bytes of junk, which readers tolerate.
PDF_SIGNATURE = b"%PDF-"
PDF_SIGNATURE_WINDOW = 1024


class PdfError(ValueError):
    """The file is not a PDF Sugo can read."""

    code: ClassVar[str] = "PDF_INVALID"


class PdfEncryptedError(PdfError):
    """The PDF needs a password to open."""

    code: ClassVar[str] = "PDF_ENCRYPTED"


class PdfTooLargeError(PdfError):
    """The file or its page count exceeds the safety limits."""

    code: ClassVar[str] = "PDF_TOO_LARGE"


class PdfUnsupportedError(PdfError):
    """The PDF uses a feature Sugo refuses for safety (Brotli, indirect filters)."""

    code: ClassVar[str] = "PDF_UNSUPPORTED"


class PdfExtractionError(PdfError):
    """The worker kept failing on this document."""

    code: ClassVar[str] = "PDF_EXTRACTION_FAILED"


_REFUSALS: dict[str, type[PdfError]] = {
    "PDF_INVALID": PdfError,
    "PDF_ENCRYPTED": PdfEncryptedError,
    "PDF_TOO_LARGE": PdfTooLargeError,
    "PDF_UNSUPPORTED": PdfUnsupportedError,
}


def read_pdf_file(path: Path) -> bytes:
    """Read a PDF file, refusing it early if it is too large.

    Raises:
        PdfTooLargeError: If the file exceeds ``MAX_PDF_FILE_BYTES``.
        OSError: If the file cannot be read.
    """
    with path.open("rb") as file:
        # One byte more than the limit tells "too large" apart from "exactly the limit".
        data = file.read(MAX_PDF_FILE_BYTES + 1)
    if len(data) > MAX_PDF_FILE_BYTES:
        raise PdfTooLargeError(f"PDF file exceeds {MAX_PDF_FILE_BYTES} bytes")
    return data


def default_ocr_engine() -> OcrEngine:
    """The bundled OCR engine, loaded only when a scanned page needs it."""
    return OcrEngine(*bundled_models())


def extract_pdf(
    data: bytes,
    *,
    ocr: Callable[[], OcrEngine] = default_ocr_engine,
    worker: Sequence[str] = WORKER_COMMAND,
    open_timeout: float = PDF_OPEN_TIMEOUT_S,
    page_timeout: float = PDF_PAGE_TIMEOUT_S,
    start: int = 0,
    skip: Callable[[int], bool] | None = None,
) -> Iterator[Page]:
    """Yield the pages of a PDF in order, from page ``start``.

    Args:
        data: The PDF file's bytes.
        start: First page to read, to resume a job whose earlier pages are
            cached. The whole document is still checked before any page.
        skip: Called with each page index from ``start``; pages it accepts
            (already cached) are received from the worker but neither laid
            out nor read with OCR, and not yielded.
        ocr: Called at most once, at the first scanned page, to get an OCR engine.
        worker: Command that starts the worker; tests replace it.
        open_timeout: Seconds allowed to open and check the document.
        page_timeout: Seconds allowed for each page.

    Raises:
        PdfError: If the file is not a readable PDF; subclasses say why.
    """
    if len(data) > MAX_PDF_FILE_BYTES:
        raise PdfTooLargeError(f"PDF file exceeds {MAX_PDF_FILE_BYTES} bytes")
    if PDF_SIGNATURE not in data[:PDF_SIGNATURE_WINDOW]:
        raise PdfError("not a PDF file")
    problem = raw_problem(data)
    if problem is not None:
        raise PdfUnsupportedError(problem)
    if start < 0:
        raise ValueError("start must not be negative")
    return _pages(data, _LazyOcr(ocr), worker, open_timeout, page_timeout, start, skip)


def is_failed_page(page: Page) -> bool:
    """Whether a page is the illegible placeholder for one the worker could not read.

    Such a page may read fine on a retry (a timeout on a busy machine), so
    callers should not cache it.
    """
    return page.origin is PageOrigin.NATIVE and page.blocks == (_FAILED_BLOCK,)


def _pages(
    data: bytes,
    ocr: "_LazyOcr",
    command: Sequence[str],
    open_timeout: float,
    page_timeout: float,
    start: int,
    skip: Callable[[int], bool] | None,
) -> Iterator[Page]:
    boxes: tuple[PageBox, ...] | None = None
    first = start
    restarts = 0
    while boxes is None or first < len(boxes):
        # Only the first worker checks every stream: a restarted one reads the
        # same bytes. Tied to the first start, not to page 0, so resuming a
        # job from a later page is checked just the same.
        with _Worker(command, data, first, check_streams=boxes is None) as worker:
            try:
                boxes = _open(worker, open_timeout, boxes).pages
            except _WorkerError:
                raise PdfExtractionError("the PDF worker failed to open the document") from None
            try:
                for index in range(first, len(boxes)):
                    if skip is not None and skip(index):
                        _skip_page(worker, index, page_timeout)
                    else:
                        yield _page(worker, index, boxes[index], ocr, page_timeout)
                    first = index + 1
            except _WorkerError:
                restarts += 1
                if restarts > PDF_MAX_WORKER_RESTARTS:
                    raise PdfExtractionError(
                        "the PDF keeps crashing or stalling the PDF worker"
                    ) from None
                failed = first
            else:
                continue
        # Outside the "with": the stalled worker is gone before the page is
        # reported. A page the caller already has is not replaced by a failure.
        if skip is None or not skip(failed):
            yield _failed_page(failed, boxes[failed])
        first = failed + 1


def _open(worker: "_Worker", timeout: float, known: tuple[PageBox, ...] | None) -> Opened:
    message = worker.message(timeout)
    if isinstance(message, Refused):
        raise _REFUSALS[message.code](message.message)
    if not isinstance(message, Opened) or (known is not None and message.pages != known):
        raise _WorkerError
    return message


def _skip_page(worker: "_Worker", index: int, timeout: float) -> None:
    """Receive a page the caller already has, checking it as strictly as any other."""
    message = worker.message(timeout)
    if not isinstance(message, NativePage | ScanPage | PageFailed) or message.index != index:
        raise _WorkerError
    if isinstance(message, ScanPage) and len(worker.frame(timeout)) != message.pixel_bytes:
        raise _WorkerError


def _page(worker: "_Worker", index: int, box: PageBox, ocr: "_LazyOcr", timeout: float) -> Page:
    message = worker.message(timeout)
    if not isinstance(message, NativePage | ScanPage | PageFailed) or message.index != index:
        raise _WorkerError
    if isinstance(message, PageFailed):
        return _failed_page(index, box)
    if isinstance(message, NativePage):
        try:
            blocks = build_blocks(message.lines)
        except (ValueError, IndexError):
            # Validated data that still breaks the layout came from a broken worker.
            raise _WorkerError from None
        return _page_of(index, box, PageOrigin.NATIVE, blocks)
    pixels = worker.frame(timeout)
    if len(pixels) != message.pixel_bytes:
        raise _WorkerError
    array = np.frombuffer(pixels, dtype=np.uint8).reshape(
        message.pixel_height, message.pixel_width, 3
    )
    image = LoadedImage(pixels=array, format=None, sha256=hashlib.sha256(pixels).hexdigest())
    blocks = extract_image(image, ocr.engine(), index=index, document_page=True).blocks
    if message.hidden_lines:
        blocks = (*blocks, hidden_block(message.hidden_lines, len(blocks)))
    return _page_of(index, box, PageOrigin.OCR, blocks)


# The only block of a page the worker could not read. Native layout never
# flags a block illegible, so this block is never confused with real text.
_FAILED_BLOCK = Block(
    id="b0",
    type=BlockType.PARAGRAPH,
    reading_order=0,
    origin_engine=ENGINE_NAME,
    flags=(BlockFlag.ILLEGIBLE,),
)


def _failed_page(index: int, box: PageBox) -> Page:
    """A page the worker could not read: one illegible block, never a silent gap."""
    return _page_of(index, box, PageOrigin.NATIVE, (_FAILED_BLOCK,))


def _page_of(index: int, box: PageBox, origin: PageOrigin, blocks: tuple[Block, ...]) -> Page:
    return Page(
        index=index,
        width=box.width,
        height=box.height,
        rotation=box.rotation,
        origin=origin,
        blocks=blocks,
    )


class _LazyOcr:
    """Loads the OCR engine at the first scanned page, then reuses it."""

    def __init__(self, factory: Callable[[], OcrEngine]) -> None:
        self._factory = factory
        self._engine: OcrEngine | None = None

    def engine(self) -> OcrEngine:
        if self._engine is None:
            self._engine = self._factory()
        return self._engine


class _WorkerError(Exception):
    """The worker stalled, crashed or sent something invalid."""


_END = object()
# Frames read ahead of the caller: enough to overlap the worker's parsing with
# Sugo's own work; more would let a scanned book pile up in memory.
_READ_AHEAD = 2
_JOIN_POLL_S = 0.05


class _Worker:
    """A worker process reading one document from a given page.

    Two threads move the bytes, so a stalled worker can never block Sugo: one
    writes the PDF to the worker's stdin, the other reads frames from its
    stdout into a queue that the caller waits on with a timeout.
    """

    def __init__(
        self, command: Sequence[str], data: bytes, first_page: int, *, check_streams: bool
    ) -> None:
        # No shell: the command is a fixed list of arguments.
        self._process = subprocess.Popen(  # noqa: S603
            [*command, str(first_page), "check" if check_streams else "trust"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        self._frames: queue.Queue[bytes | object] = queue.Queue(maxsize=_READ_AHEAD)
        self._writer = threading.Thread(target=self._write, args=(data,), daemon=True)
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._writer.start()
        self._reader.start()

    def __enter__(self) -> "_Worker":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def frame(self, timeout: float) -> bytes:
        """The next frame.

        Raises:
            _WorkerError: On timeout, end of output or a malformed frame.
        """
        try:
            item = self._frames.get(timeout=timeout)
        except queue.Empty:
            raise _WorkerError from None
        if not isinstance(item, bytes):
            raise _WorkerError
        return item

    def message(self, timeout: float) -> Message:
        """The next frame, parsed as a message.

        Raises:
            _WorkerError: As ``frame``, or if the frame is not a valid message.
        """
        try:
            return parse_message(self.frame(timeout))
        except ProtocolError:
            raise _WorkerError from None

    def close(self) -> None:
        """Stop the worker if it still runs and wait for both threads."""
        if self._process.poll() is None:
            self._process.kill()
        self._process.wait()
        self._writer.join()
        # The reader may wait for room in the queue; make room until it ends.
        while self._reader.is_alive():
            with contextlib.suppress(queue.Empty):
                self._frames.get_nowait()
            self._reader.join(timeout=_JOIN_POLL_S)
        for stream in (self._process.stdin, self._process.stdout):
            if stream is not None:
                stream.close()

    def _write(self, data: bytes) -> None:
        stdin = self._process.stdin
        if stdin is None:
            return
        try:
            stdin.write(data)
            stdin.close()
        except OSError:
            pass  # The worker exited early; its output tells the reason.

    def _read(self) -> None:
        stdout = self._process.stdout
        try:
            while stdout is not None and (frame := read_frame(stdout)) is not None:
                self._frames.put(frame)
        except (ProtocolError, OSError, ValueError):
            pass  # Reported to the caller as the end of the frames.
        self._frames.put(_END)
