"""Messages between Sugo and the PDF worker process (ADR-043).

The worker parses untrusted PDFs with MuPDF, a C library, so it must be
assumed compromised by a hostile file. Everything it sends is therefore data,
never code:

- each message is a frame: a 4-byte big-endian length, then that many bytes;
- a frame holds JSON validated against the strict models below, or, right
  after a ``ScanPage``, the raw RGB pixels it announced, nothing else;
- frames larger than ``PDF_MAX_MESSAGE_BYTES`` are refused before reading.

Pickle is never used: unpickling data from a compromised process would run
its code inside Sugo.
"""

import struct
from typing import IO, Annotated, Literal

from pydantic import Field, TypeAdapter

from sugo.core.constants import MAX_PDF_PAGES, PDF_MAX_MESSAGE_BYTES, PDF_OCR_MAX_PIXELS
from sugo.core.models import BBox, NonEmptyStr, _Model

_LENGTH = struct.Struct(">I")
_RGB_CHANNELS = 3

PageIndex = Annotated[int, Field(ge=0, lt=MAX_PDF_PAGES)]
Points = Annotated[float, Field(gt=0)]
Rotation = Literal[0, 90, 180, 270]


class ProtocolError(RuntimeError):
    """The worker sent something that is not a valid message."""


class NativeLine(_Model):
    """A run of text on one line with one visibility and similar style.

    Leading spaces are kept, for code indentation; trailing ones are not.
    """

    text: NonEmptyStr
    # None for text entirely outside the page, which has no position on it.
    bbox: BBox | None
    font_size: Points
    bold: bool
    monospace: bool
    hidden: bool


class PageBox(_Model):
    """Size and rotation of a page, known before any page is read."""

    width: Points
    height: Points
    rotation: Rotation


class Opened(_Model):
    """The document passed every check and can be read.

    Every page's box comes first, so a page that crashes the worker can still
    be reported with its real size.
    """

    kind: Literal["opened"] = "opened"
    pages: Annotated[tuple[PageBox, ...], Field(max_length=MAX_PDF_PAGES)]


class Refused(_Model):
    """The worker refused the document; ``code`` is a stable error code."""

    kind: Literal["refused"] = "refused"
    code: Literal["PDF_INVALID", "PDF_ENCRYPTED", "PDF_TOO_LARGE", "PDF_UNSUPPORTED"]
    message: NonEmptyStr


class NativePage(_Model):
    """A page with a usable text layer."""

    kind: Literal["native"] = "native"
    index: PageIndex
    lines: tuple[NativeLine, ...]


class ScanPage(_Model):
    """A page to read with OCR; a frame of raw RGB pixels follows.

    ``hidden_lines`` is the page's own text layer, kept but flagged: Sugo reads
    what is visible instead of trusting an invisible layer (ADR-043).
    """

    kind: Literal["scan"] = "scan"
    index: PageIndex
    pixel_width: Annotated[int, Field(ge=1)]
    pixel_height: Annotated[int, Field(ge=1)]
    hidden_lines: tuple[NativeLine, ...]

    @property
    def pixel_bytes(self) -> int:
        """Size of the pixel frame that follows."""
        return self.pixel_width * self.pixel_height * _RGB_CHANNELS


class PageFailed(_Model):
    """MuPDF raised an error on this page; it is reported, never dropped."""

    kind: Literal["page_failed"] = "page_failed"
    index: PageIndex


Message = Opened | Refused | NativePage | ScanPage | PageFailed
_MESSAGE: TypeAdapter[Message] = TypeAdapter(Annotated[Message, Field(discriminator="kind")])


def write_frame(stream: IO[bytes], payload: bytes) -> None:
    """Write one frame and flush it."""
    stream.write(_LENGTH.pack(len(payload)))
    stream.write(payload)
    stream.flush()


def write_message(stream: IO[bytes], message: Message) -> None:
    """Write a message as a JSON frame."""
    write_frame(stream, message.model_dump_json().encode())


def read_frame(stream: IO[bytes]) -> bytes | None:
    """Read one frame, or None at a clean end of stream.

    Raises:
        ProtocolError: If the frame is too large or cut short.
    """
    header = stream.read(_LENGTH.size)
    if not header:
        return None
    if len(header) != _LENGTH.size:
        raise ProtocolError("truncated frame header")
    (length,) = _LENGTH.unpack(header)
    if length > PDF_MAX_MESSAGE_BYTES:
        raise ProtocolError(f"frame of {length} bytes exceeds the limit")
    payload = stream.read(length)
    if len(payload) != length:
        raise ProtocolError("truncated frame")
    return payload


def parse_message(payload: bytes) -> Message:
    """Validate a JSON frame as a message.

    Raises:
        ProtocolError: If the frame is not a valid message.
    """
    try:
        message = _MESSAGE.validate_json(payload)
    except ValueError as error:
        # Pydantic's message may quote the payload, which holds document text.
        raise ProtocolError("invalid message from the PDF worker") from error
    if isinstance(message, ScanPage) and (
        message.pixel_width * message.pixel_height > PDF_OCR_MAX_PIXELS
    ):
        raise ProtocolError("scanned page exceeds the pixel limit")
    return message
