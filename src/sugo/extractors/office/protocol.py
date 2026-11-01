"""Messages between Sugo and the Office and XML worker process (ADR-054).

Frames as for the PDF worker (``sugo.extractors.worker``), each one JSON
validated against the strict models below; pages travel as IR pages, which
the IR models validate again on receipt. Pickle is never used.
"""

from typing import IO, Annotated, Literal

from pydantic import Field, TypeAdapter

from sugo.core.models import NonEmptyStr, Page, _Model
from sugo.extractors import worker as frames
from sugo.extractors.worker import ProtocolError

# More pages than any file the reader accepts can produce.
_MAX_PAGES = 100_000

PageIndex = Annotated[int, Field(ge=0, lt=_MAX_PAGES)]
# Longer than any part name a ZIP entry in a package can reasonably have.
_MAX_PART_NAME = 1024


class Opened(_Model):
    """The file passed every check; it has this many pages."""

    kind: Literal["opened"] = "opened"
    pages: Annotated[int, Field(ge=1, le=_MAX_PAGES)]


class Refused(_Model):
    """The worker refused the file; ``code`` is a stable error code."""

    kind: Literal["refused"] = "refused"
    code: Literal[
        "XML_INVALID", "XML_TOO_LARGE", "OFFICE_INVALID", "OFFICE_TOO_LARGE", "OFFICE_UNSUPPORTED"
    ]
    message: NonEmptyStr


class ImageRef(_Model):
    """A picture marked not converted on a page, and the package part that holds it.

    Sugo's process reads the part with OCR (ADR-054); the worker never loads
    the image stack.
    """

    block: NonEmptyStr
    part: Annotated[str, Field(min_length=1, max_length=_MAX_PART_NAME)]


class PageRead(_Model):
    """One page, laid out, with the pictures on it."""

    kind: Literal["page"] = "page"
    page: Page
    images: tuple[ImageRef, ...] = ()


class PageFailed(_Model):
    """Reading this page raised an error; it is reported, never dropped."""

    kind: Literal["page_failed"] = "page_failed"
    index: PageIndex


Message = Opened | Refused | PageRead | PageFailed
_MESSAGE: TypeAdapter[Message] = TypeAdapter(Annotated[Message, Field(discriminator="kind")])


def write_message(stream: IO[bytes], message: Message) -> None:
    """Write a message as a JSON frame."""
    frames.write_frame(stream, message.model_dump_json().encode())


def parse_message(payload: bytes) -> Message:
    """Validate a JSON frame as a message.

    Raises:
        ProtocolError: If the frame is not a valid message.
    """
    try:
        return _MESSAGE.validate_json(payload)
    except ValueError as error:
        # Pydantic's message may quote the payload, which holds document text.
        raise ProtocolError("invalid message from the Office worker") from error
