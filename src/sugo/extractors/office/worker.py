"""Office and XML worker: parses one file in its own process (ADR-054).

Started by ``sugo.extractors.office.extract`` as
``python -I -m sugo.extractors.office.worker KIND FIRST_PAGE``; reads the
file from stdin and writes frames (``sugo.extractors.office.protocol``) to a
private copy of stdout. The parser is pure Python, so it cannot be stopped
from inside one process: running it here is what makes the time limits real.
Before parsing, the worker disables core dumps and, on Linux and macOS, caps
its address space.
"""

import sys
from collections.abc import Callable, Iterator

from sugo.core.constants import (
    MAX_OFFICE_FILE_BYTES,
    MAX_XML_FILE_BYTES,
    OFFICE_WORKER_MEMORY_BYTES,
)
from sugo.core.models import Page
from sugo.extractors.office.docx_reader import read_docx
from sugo.extractors.office.protocol import (
    Message,
    Opened,
    PageRead,
    Refused,
    write_message,
)
from sugo.extractors.office.xml_reader import Refusal, lay_out, parse
from sugo.extractors.worker import limit_resources, private_stdout


def main() -> None:
    """Entry point of the worker process."""
    limit_resources(OFFICE_WORKER_MEMORY_BYTES)
    kind = sys.argv[1]
    first_page = int(sys.argv[2])
    data = sys.stdin.buffer.read(max(MAX_XML_FILE_BYTES, MAX_OFFICE_FILE_BYTES) + 1)
    with private_stdout() as out:
        for message in run(data, kind, first_page):
            write_message(out, message)


def run(data: bytes, kind: str, first_page: int) -> Iterator[Message]:
    """Check and parse the file, then yield one message per page from ``first_page``.

    The whole file is laid out before the first page: page breaks, numbering
    and notes depend on everything before them.
    """
    if kind not in _READERS:
        raise ValueError(f"unknown kind {kind!r}")
    try:
        pages = _READERS[kind](data)
    except Refusal as refusal:
        yield _refused(refusal)
        return
    yield Opened(pages=len(pages))
    for page in pages[first_page:]:
        yield PageRead(page=page)


def _read_xml(data: bytes) -> list[Page]:
    return [lay_out(parse(data))]


_READERS: dict[str, Callable[[bytes], list[Page]]] = {"xml": _read_xml, "docx": read_docx}


def _refused(refusal: Refusal) -> Refused:
    """The refusal message; an unknown code from a reader is a damaged file."""
    codes: dict[str, Refused] = {
        code: Refused(code=code, message=refusal.message)
        for code in (
            "XML_INVALID",
            "XML_TOO_LARGE",
            "OFFICE_INVALID",
            "OFFICE_TOO_LARGE",
            "OFFICE_UNSUPPORTED",
        )
    }
    return codes.get(refusal.code, Refused(code="OFFICE_INVALID", message=refusal.message))


if __name__ == "__main__":
    main()
