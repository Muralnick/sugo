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
from sugo.extractors.office.docx_reader import lay_out_docx
from sugo.extractors.office.package import LaidOut
from sugo.extractors.office.pptx_reader import lay_out_pptx
from sugo.extractors.office.protocol import (
    ImageRef,
    Message,
    Opened,
    PageFailed,
    PageRead,
    Refused,
    write_message,
)
from sugo.extractors.office.xlsx_reader import lay_out_xlsx
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

    Every check that can refuse the file runs before the first page: a
    document is laid out whole, since page breaks, numbering and notes depend
    on everything before them; a workbook's sheets are scanned, then each is
    laid out when its page is sent, and a presentation's slides are listed,
    then each is laid out the same way. A page whose parts turn out broken then
    is reported as failed, never dropped.
    """
    if kind not in _READERS:
        raise ValueError(f"unknown kind {kind!r}")
    try:
        count, page = _READERS[kind](data)
    except Refusal as refusal:
        yield _refused(refusal)
        return
    yield Opened(pages=count)
    for index in range(first_page, count):
        try:
            laid_out, images = page(index)
            refs = tuple(
                ImageRef(block=block, part=image.part, crop=image.crop, height=image.height)
                for block, image in images.items()
            )
            yield PageRead(page=laid_out, images=refs)
        except Refusal:
            yield PageFailed(index=index)


def _laid_out(pages: list[LaidOut]) -> tuple[int, Callable[[int], LaidOut]]:
    return len(pages), pages.__getitem__


_READERS: dict[str, Callable[[bytes], tuple[int, Callable[[int], LaidOut]]]] = {
    "xml": lambda data: _laid_out([(lay_out(parse(data)), {})]),
    "docx": lambda data: _laid_out(lay_out_docx(data)),
    "xlsx": lay_out_xlsx,
    "pptx": lay_out_pptx,
}


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
