"""PDF worker: runs MuPDF in its own process and streams pages as messages (ADR-043).

Started by ``sugo.extractors.pymupdf.extract`` as
``python -I -m sugo.extractors.pymupdf.worker FIRST_PAGE``; reads the PDF bytes
from stdin and writes frames (``sugo.extractors.pymupdf.protocol``) to stdout.
Its stderr is discarded by the parent: MuPDF warnings can quote the document.
Frames go to a private copy of stdout, and file descriptor 1 itself to the
null device, so nothing MuPDF prints can corrupt or forge a frame.

Before parsing anything the worker limits itself: no core dumps (they would
write document text to disk, ADR-031) and, on Linux and macOS, a cap on its
address space, so a hostile file cannot exhaust the machine's memory.

Checks before any page is interpreted:

- the document opens, is not password protected, and has a sane page count;
- no content stream uses Brotli for an inline image. MuPDF below 1.28.6 has
  an out-of-bounds write in its Brotli decoder (CVE-2026-111497); stream
  dictionaries were checked by the parent before this process started.

Each page is either native, with every text line marked visible or hidden, or
a scan, rendered for OCR. Text is hidden when a reader cannot see it on the
rendered page: drawn invisible or clipped away, smaller than
``PDF_MIN_VISIBLE_FONT_SIZE``, outside the page, or the same colour as what
is drawn around it (white on white, text under an opaque shape).
"""

import contextlib
import math
import os
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from typing import IO, Any

import numpy as np
import numpy.typing as npt
import pymupdf

from sugo.core.constants import (
    MAX_PDF_FILE_BYTES,
    MAX_PDF_PAGES,
    PDF_MIN_TEXT_CONTRAST,
    PDF_MIN_VISIBLE_FONT_SIZE,
    PDF_OCR_DPI,
    PDF_OCR_MAX_PIXELS,
    PDF_SCAN_MAX_VISIBLE_CHARS,
    PDF_SCAN_MIN_IMAGE_COVERAGE,
    PDF_VISIBILITY_DPI,
    PDF_WORKER_MEMORY_BYTES,
)
from sugo.core.models import BBox
from sugo.extractors.pymupdf.guard import BROTLI_REFUSAL, names_brotli
from sugo.extractors.pymupdf.protocol import (
    Message,
    NativeLine,
    NativePage,
    Opened,
    PageBox,
    PageFailed,
    Refused,
    Rotation,
    ScanPage,
    write_frame,
    write_message,
)

Pixels = npt.NDArray[np.uint8]

# MuPDF character flags (fz_stext_char flags) and font flags (span "flags").
_FILLED = 16
_STROKED = 32
_CLIPPED = 64
_FONT_MONOSPACED = 8
_FONT_BOLD = 16
# Points per inch: PDF user space is 1/72 inch.
_POINTS_PER_INCH = 72
_LETTER = PageBox(width=612.0, height=792.0, rotation=0)
_ROTATIONS: dict[int, Rotation] = {0: 0, 90: 90, 180: 180, 270: 270}
_TEXT_FLAGS = pymupdf.TEXT_PRESERVE_WHITESPACE | pymupdf.TEXT_PRESERVE_LIGATURES


def main() -> None:
    """Entry point of the worker process."""
    _limit_resources()
    pymupdf.TOOLS.mupdf_display_errors(False)
    pymupdf.TOOLS.mupdf_display_warnings(False)
    first_page = int(sys.argv[1])
    data = sys.stdin.buffer.read(MAX_PDF_FILE_BYTES + 1)
    with _private_stdout() as out:
        write_all(out, run(data, first_page))


@contextlib.contextmanager
def _private_stdout() -> Iterator[IO[bytes]]:
    """A private copy of stdout for frames; file descriptor 1 goes to the null device.

    MuPDF's C code may print to stdout (it does on decoding errors). Nothing
    it prints can then corrupt or forge a frame.
    """
    sys.stdout.flush()
    out = os.fdopen(os.dup(1), "wb")
    null = os.open(os.devnull, os.O_WRONLY)
    os.dup2(null, 1)
    os.close(null)
    with out:
        yield out


def run(data: bytes, first_page: int) -> Iterator[tuple[Message, bytes | None]]:
    """Check the document, then yield one message per page from ``first_page``.

    A scan page comes with its RGB pixels; every other message with None.
    """
    try:
        document = pymupdf.open(stream=data, filetype="pdf")
    except (RuntimeError, ValueError):
        yield Refused(code="PDF_INVALID", message="the file is not a readable PDF"), None
        return
    with document:
        # A restarted worker reads the same bytes, already checked by the first.
        refusal = _check(document, streams=first_page == 0)
        if refusal is not None:
            yield refusal, None
            return
        yield Opened(pages=_boxes(document)), None
        for index in range(first_page, document.page_count):
            try:
                result = _read_page(document[index], index)
            # Whatever MuPDF or a malformed page raises, only this page fails.
            except Exception:  # noqa: BLE001
                result = PageFailed(index=index), None
            yield result


def _limit_resources() -> None:
    """Disable core dumps and cap the address space where the OS allows it."""
    try:
        import resource  # POSIX only
    except ImportError:  # Windows: isolation is weaker there (ADR-031).
        return
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    # macOS refuses RLIMIT_AS on some versions; the page timeout still applies.
    with contextlib.suppress(ValueError, OSError):
        resource.setrlimit(resource.RLIMIT_AS, (PDF_WORKER_MEMORY_BYTES, PDF_WORKER_MEMORY_BYTES))


def _check(document: pymupdf.Document, *, streams: bool) -> Refused | None:
    if document.needs_pass:
        return Refused(code="PDF_ENCRYPTED", message="the PDF is protected by a password")
    if document.page_count > MAX_PDF_PAGES:
        return Refused(code="PDF_TOO_LARGE", message=f"the PDF has more than {MAX_PDF_PAGES} pages")
    if streams:
        return _stream_problem(document)
    return None


def _stream_problem(document: pymupdf.Document) -> Refused | None:
    """Refuse a document with an inline image compressed with Brotli.

    Every stream is decoded and searched, images included: ``/Subtype`` is
    written by the attacker, and a page's content stream may claim to be an
    image. A stream that cannot be decoded cannot be checked, so the document
    is refused rather than parsed unchecked (temporary, ADR-043).
    """
    for xref in range(1, document.xref_length()):
        try:
            if not document.xref_is_stream(xref):
                continue
            decoded = document.xref_stream(xref) or b""
        except Exception:  # noqa: BLE001  (any MuPDF failure means "unchecked")
            return Refused(
                code="PDF_UNSUPPORTED",
                message="a stream of the PDF cannot be decoded, so it cannot be checked",
            )
        if names_brotli(decoded):
            return Refused(
                code="PDF_UNSUPPORTED",
                message=BROTLI_REFUSAL,
            )
    return None


def _boxes(document: pymupdf.Document) -> tuple[PageBox, ...]:
    """Every page's box. A page that fails to load gets the box of the page
    before it (US Letter for the first); reading it will fail and mark it."""
    boxes: list[PageBox] = []
    for index in range(document.page_count):
        try:
            boxes.append(_box(document[index]))
        except Exception:  # noqa: BLE001  (one broken page must not end the document)
            boxes.append(boxes[-1] if boxes else _LETTER)
    return tuple(boxes)


@dataclass(frozen=True)
class _Span:
    text: str
    bbox: tuple[float, float, float, float]
    font_size: float
    bold: bool
    monospace: bool
    hidden: bool


def _read_page(page: pymupdf.Page, index: int) -> tuple[Message, bytes | None]:
    rect = page.rect
    pixmap = page.get_pixmap(dpi=PDF_VISIBILITY_DPI, alpha=False, colorspace=pymupdf.csRGB)
    rendered = _pixels(pixmap)
    scale = PDF_VISIBILITY_DPI / _POINTS_PER_INCH
    text = page.get_text("dict", flags=_TEXT_FLAGS, clip=pymupdf.INFINITE_RECT())
    lines = [
        line
        for block in text["blocks"]
        if block["type"] == 0
        for raw_line in block["lines"]
        for line in _split_line(raw_line, rect, rendered, scale)
    ]
    visible_chars = sum(len("".join(line.text.split())) for line in lines if not line.hidden)
    if (
        _image_coverage(page, rect) >= PDF_SCAN_MIN_IMAGE_COVERAGE
        and visible_chars < PDF_SCAN_MAX_VISIBLE_CHARS
    ):
        return _scan(page, index, [line for line in lines if line.hidden])
    return NativePage(index=index, lines=tuple(lines)), None


def _box(page: pymupdf.Page) -> PageBox:
    rect = page.rect
    return PageBox(width=rect.width, height=rect.height, rotation=_rotation(page))


def _rotation(page: pymupdf.Page) -> Rotation:
    """The page's rotation; MuPDF normalises /Rotate to a quarter turn."""
    return _ROTATIONS.get(int(page.rotation) % 360, 0)


def _pixels(pixmap: pymupdf.Pixmap) -> Pixels:
    """RGB pixels of a pixmap, height x width x 3; rows may be padded to ``stride``."""
    rows = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(pixmap.height, pixmap.stride)
    return rows[:, : pixmap.width * 3].reshape(pixmap.height, pixmap.width, 3)


def _split_line(
    line: dict[str, Any], rect: pymupdf.Rect, rendered: Pixels, scale: float
) -> list[NativeLine]:
    """Split a MuPDF line into runs of visible and hidden spans.

    A run's visibility is that of its first span with text. Spaces join the
    run they are in whatever their own visibility, but never decide it: a
    hidden space must not carry the hidden word after it into visible text.
    """
    runs: list[list[_Span]] = []
    hidden: list[bool | None] = []  # per run; None while it holds only spaces
    for raw in line["spans"]:
        span = _span(raw, rect, rendered, scale)
        blank = not span.text.strip()
        if runs and (blank or hidden[-1] is None or hidden[-1] == span.hidden):
            runs[-1].append(span)
            if hidden[-1] is None and not blank:
                hidden[-1] = span.hidden
        else:
            runs.append([span])
            hidden.append(None if blank else span.hidden)
    return [native for run in runs if (native := _native_line(run, rect)) is not None]


def _span(raw: dict[str, Any], rect: pymupdf.Rect, rendered: Pixels, scale: float) -> _Span:
    x0, y0, x1, y1 = (float(value) for value in raw["bbox"])
    bbox = (x0, y0, x1, y1)
    char_flags = int(raw.get("char_flags", _FILLED))
    invisible = (
        int(raw.get("alpha", 255)) == 0
        or not char_flags & (_FILLED | _STROKED)
        or bool(char_flags & _CLIPPED)
    )
    off_page = x1 <= rect.x0 or x0 >= rect.x1 or y1 <= rect.y0 or y0 >= rect.y1
    hidden = (
        invisible
        or off_page
        or float(raw["size"]) < PDF_MIN_VISIBLE_FONT_SIZE
        or not _contrasts(raw, bbox, rect, rendered, scale)
    )
    return _Span(
        text=str(raw["text"]),
        bbox=bbox,
        font_size=float(raw["size"]),
        bold=bool(int(raw["flags"]) & _FONT_BOLD),
        monospace=bool(int(raw["flags"]) & _FONT_MONOSPACED),
        hidden=hidden,
    )


def _contrasts(
    raw: dict[str, Any],
    bbox: tuple[float, float, float, float],
    rect: pymupdf.Rect,
    rendered: Pixels,
    scale: float,
) -> bool:
    """Whether the span's colour stands out from what the page shows around it.

    The background is the median colour of the span's box on the rendered
    page. Text the same colour as that background, or a box with nothing drawn
    in it at all (text under an opaque shape), cannot be seen.
    """
    left = max(0, int((bbox[0] - rect.x0) * scale))
    top = max(0, int((bbox[1] - rect.y0) * scale))
    right = min(rendered.shape[1], int(np.ceil((bbox[2] - rect.x0) * scale)))
    bottom = min(rendered.shape[0], int(np.ceil((bbox[3] - rect.y0) * scale)))
    if right <= left or bottom <= top:
        return True  # Too small to judge here; the font size rule covers it.
    region = rendered[top:bottom, left:right].reshape(-1, 3).astype(np.int16)
    background = np.median(region, axis=0)
    colour = int(raw["color"])
    text_rgb = np.array([(colour >> 16) & 0xFF, (colour >> 8) & 0xFF, colour & 0xFF])
    contrast = float(np.max(np.abs(text_rgb - background)))
    ink = float(np.max(np.abs(region - background)))
    return contrast >= PDF_MIN_TEXT_CONTRAST and ink >= PDF_MIN_TEXT_CONTRAST


def _native_line(run: list[_Span], rect: pymupdf.Rect) -> NativeLine | None:
    # Leading spaces stay: in code they are indentation (layout rebuilds it).
    text = "".join(span.text for span in run).rstrip()
    if not text.strip():
        return None
    styled = [span for span in run if span.text.strip()]
    # The size of the span holding most characters represents the line.
    main = max(styled, key=lambda span: len(span.text))
    return NativeLine(
        text=text,
        bbox=_normalise(run, rect),
        font_size=main.font_size,
        bold=all(span.bold for span in styled),
        monospace=all(span.monospace for span in styled),
        hidden=styled[0].hidden,
    )


def _normalise(run: list[_Span], rect: pymupdf.Rect) -> BBox | None:
    x0 = min(span.bbox[0] for span in run)
    y0 = min(span.bbox[1] for span in run)
    x1 = max(span.bbox[2] for span in run)
    y1 = max(span.bbox[3] for span in run)
    if x1 <= rect.x0 or x0 >= rect.x1 or y1 <= rect.y0 or y0 >= rect.y1:
        return None

    def clamp(value: float, start: float, size: float) -> float:
        return min(1.0, max(0.0, (value - start) / size))

    return BBox(
        x0=clamp(x0, rect.x0, rect.width),
        y0=clamp(y0, rect.y0, rect.height),
        x1=clamp(x1, rect.x0, rect.width),
        y1=clamp(y1, rect.y0, rect.height),
    )


def _image_coverage(page: pymupdf.Page, rect: pymupdf.Rect) -> float:
    """Share of the page covered by images, overlaps counted once per image."""
    area = rect.width * rect.height
    covered = sum(abs(pymupdf.Rect(info["bbox"]) & rect) for info in page.get_image_info())
    return min(1.0, covered / area) if area > 0 else 0.0


def _scan(page: pymupdf.Page, index: int, hidden: list[NativeLine]) -> tuple[Message, bytes | None]:
    pixmap = page.get_pixmap(
        dpi=_ocr_dpi(float(page.rect.width), float(page.rect.height)),
        alpha=False,
        colorspace=pymupdf.csRGB,
    )
    message = ScanPage(
        index=index,
        pixel_width=pixmap.width,
        pixel_height=pixmap.height,
        hidden_lines=tuple(hidden),
    )
    return message, _pixels(pixmap).tobytes()


def _ocr_dpi(page_width: float, page_height: float) -> int:
    """``PDF_OCR_DPI``, lowered for very large pages so the render fits the pixel limit.

    MuPDF rounds each side up, so one extra pixel per side is counted.
    """

    def pixels(dpi: int) -> int:
        zoom = dpi / _POINTS_PER_INCH
        return (math.ceil(page_width * zoom) + 1) * (math.ceil(page_height * zoom) + 1)

    dpi = PDF_OCR_DPI
    if pixels(dpi) > PDF_OCR_MAX_PIXELS:
        dpi = int(dpi * (PDF_OCR_MAX_PIXELS / pixels(dpi)) ** 0.5)
    while dpi > 1 and pixels(dpi) > PDF_OCR_MAX_PIXELS:
        dpi -= 1
    return max(1, dpi)


def write_all(out: IO[bytes], messages: Iterator[tuple[Message, bytes | None]]) -> None:
    """Write messages and their pixel frames to a stream."""
    for message, pixels in messages:
        write_message(out, message)
        if pixels is not None:
            write_frame(out, pixels)


if __name__ == "__main__":
    main()
