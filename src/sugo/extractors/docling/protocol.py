"""Messages between Sugo and the Docling worker process (ADR-071).

Frames as for the other workers (``sugo.extractors.worker``), each one JSON
validated against the strict models below; pages travel as IR pages, which
the IR models validate again on receipt. Pickle is never used.
"""

from typing import IO, Annotated, Literal

from pydantic import Field, TypeAdapter

from sugo.core.models import NonEmptyStr, Page, _Model
from sugo.extractors import worker as frames
from sugo.extractors.worker import ProtocolError

# More pages than any file Sugo accepts can produce.
MAX_PAGES = 100_000
# A page of IR as JSON; far above a dense page with large tables.
MAX_MESSAGE_BYTES = 64 * 1024 * 1024


class Opened(_Model):
    """Docling read the file; this many pages follow."""

    kind: Literal["opened"] = "opened"
    pages: Annotated[int, Field(ge=1, le=MAX_PAGES)]


class Refused(_Model):
    """The worker could not read the file; ``code`` says why, ``message`` in English."""

    kind: Literal["refused"] = "refused"
    code: Literal["LEVEL_MISSING", "NORMAL_FAILED"]
    message: NonEmptyStr


class PageRead(_Model):
    """One page, laid out by Docling."""

    kind: Literal["page"] = "page"
    page: Page


Message = Opened | Refused | PageRead
_MESSAGE: TypeAdapter[Message] = TypeAdapter(Annotated[Message, Field(discriminator="kind")])


def write_message(stream: IO[bytes], message: Message) -> None:
    """Write a message as a JSON frame."""
    frames.write_frame(stream, message.model_dump_json().encode())


def parse_message(payload: bytes) -> Message:
    """Validate a frame from the worker.

    Raises:
        ProtocolError: If it is not a valid message.
    """
    try:
        return _MESSAGE.validate_json(payload)
    except ValueError as error:
        # The validation details could quote the document; the type only.
        raise ProtocolError(f"invalid message: {type(error).__name__}") from None
