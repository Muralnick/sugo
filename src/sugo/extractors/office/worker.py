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
from collections.abc import Iterator

from sugo.core.constants import MAX_XML_FILE_BYTES, OFFICE_WORKER_MEMORY_BYTES
from sugo.extractors.office.protocol import (
    Message,
    Opened,
    PageFailed,
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
    data = sys.stdin.buffer.read(MAX_XML_FILE_BYTES + 1)
    with private_stdout() as out:
        for message in run(data, kind, first_page):
            write_message(out, message)


def run(data: bytes, kind: str, first_page: int) -> Iterator[Message]:
    """Check and parse the file, then yield one message per page from ``first_page``."""
    if kind != "xml":
        raise ValueError(f"unknown kind {kind!r}")
    try:
        root = parse(data)
    except Refusal as refusal:
        if refusal.code == "XML_TOO_LARGE":
            yield Refused(code="XML_TOO_LARGE", message=refusal.message)
        else:
            yield Refused(code="XML_INVALID", message=refusal.message)
        return
    yield Opened(pages=1)
    if first_page == 0:
        try:
            yield PageRead(page=lay_out(root))
        # Whatever a malformed file makes the layout raise, only this page fails.
        except Exception:  # noqa: BLE001
            yield PageFailed(index=0)


if __name__ == "__main__":
    main()
