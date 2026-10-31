"""Read XML, Word documents and Excel workbooks into IR pages through the isolated worker (ADR-054).

The file is recognised by its content, checked for size here, then parsed by
a worker process (``sugo.extractors.office.worker``) that streams back pages
as plain data, validated before use. Opening has a time limit, each page
another. A page that stalls or crashes the worker is marked illegible, never
dropped, and a fresh worker continues from the next page; a file that keeps
crashing it is refused.
"""

import codecs
import re
from collections.abc import Iterator, Sequence
from typing import ClassVar

from sugo import i18n
from sugo.core.constants import (
    MAX_OFFICE_FILE_BYTES,
    MAX_XML_FILE_BYTES,
    OFFICE_MAX_MESSAGE_BYTES,
    OFFICE_MAX_WORKER_RESTARTS,
    OFFICE_OPEN_TIMEOUT_S,
    OFFICE_PAGE_TIMEOUT_S,
    XML_SNIFF_BYTES,
)
from sugo.core.models import Block, BlockFlag, BlockType, Page, PageOrigin
from sugo.extractors.office import docx_reader, xlsx_reader, xml_reader
from sugo.extractors.office.package import OLE_SIGNATURE, excel_workbook, word_document
from sugo.extractors.office.protocol import (
    Message,
    Opened,
    PageFailed,
    PageRead,
    Refused,
    parse_message,
)
from sugo.extractors.worker import ProtocolError, WorkerError, WorkerProcess, module_command
from sugo.i18n import gettext as _

WORKER_COMMAND: tuple[str, ...] = module_command("sugo.extractors.office.worker")

# A processing instruction ("<?xml", "<?xml-stylesheet"), a comment or an
# element: a name starts with a letter or "_" (XML 1.0).
_XML_START = re.compile(r"<(?:\?[^\W\d]|!--|[^\W\d.\-])")
_HTML_DOCTYPE = re.compile(r"<!doctype\s+html", re.IGNORECASE)
_BOMS = (
    (codecs.BOM_UTF8, "utf-8"),
    (codecs.BOM_UTF16_LE, "utf-16-le"),
    (codecs.BOM_UTF16_BE, "utf-16-be"),
)


_ENGINES = {
    "xml": xml_reader.ENGINE_NAME,
    "docx": docx_reader.ENGINE_NAME,
    "xlsx": xlsx_reader.ENGINE_NAME,
}


class OfficeError(ValueError):
    """The file is not an Office document Sugo can read."""

    code: ClassVar[str] = "OFFICE_INVALID"


class OfficeTooLargeError(OfficeError):
    """The file exceeds the size or archive limits."""

    code: ClassVar[str] = "OFFICE_TOO_LARGE"


class OfficeUnsupportedError(OfficeError):
    """A legacy or password-protected Office file."""

    code: ClassVar[str] = "OFFICE_UNSUPPORTED"


class OfficeExtractionError(OfficeError):
    """The worker kept failing on this file."""

    code: ClassVar[str] = "OFFICE_EXTRACTION_FAILED"


class XmlError(OfficeError):
    """The file is not XML Sugo can read."""

    code: ClassVar[str] = "XML_INVALID"


class XmlTooLargeError(XmlError):
    """The file exceeds the size, depth or element limits."""

    code: ClassVar[str] = "XML_TOO_LARGE"


_REFUSALS: dict[str, type[OfficeError]] = {
    "XML_INVALID": XmlError,
    "XML_TOO_LARGE": XmlTooLargeError,
    "OFFICE_INVALID": OfficeError,
    "OFFICE_TOO_LARGE": OfficeTooLargeError,
    "OFFICE_UNSUPPORTED": OfficeUnsupportedError,
}


def is_docx(data: bytes) -> bool:
    """Whether the data is a Word document (DOCX, DOTX, DOCM, DOTM), by its content."""
    return word_document(data)


def is_xlsx(data: bytes) -> bool:
    """Whether the data is an Excel workbook (XLSX, XLTX, XLSM, XLTM), by its content."""
    return excel_workbook(data)


def check_legacy(data: bytes) -> None:
    """Refuse a compound file: a legacy Office file, or any password-protected one.

    Raises:
        OfficeUnsupportedError: If the data is a compound (OLE) file.
    """
    if data.startswith(OLE_SIGNATURE):
        raise OfficeUnsupportedError(
            _("legacy or password-protected Office files are not supported")
        )


def looks_like_xml(data: bytes) -> bool:
    """Whether the data starts like an XML document, after a byte order mark and white space.

    An HTML page with its doctype is not taken for XML.
    """
    head = data[:XML_SNIFF_BYTES]
    encoding = "utf-8"
    for bom, name in _BOMS:
        if head.startswith(bom):
            head, encoding = head[len(bom) :], name
            break
    # Cut characters at the end of the window are dropped, not refused.
    text = head.decode(encoding, errors="ignore").lstrip()
    return bool(_XML_START.match(text)) and not _HTML_DOCTYPE.match(text)


def extract_xml(
    data: bytes,
    *,
    worker: Sequence[str] = WORKER_COMMAND,
    open_timeout: float = OFFICE_OPEN_TIMEOUT_S,
    page_timeout: float = OFFICE_PAGE_TIMEOUT_S,
) -> Iterator[Page]:
    """Yield the pages of an XML file (one, in v0.1).

    Args:
        data: The file's bytes.
        worker: Command that starts the worker; tests replace it.
        open_timeout: Seconds allowed to parse and check the file.
        page_timeout: Seconds allowed for each page.

    Raises:
        XmlError: If the file is refused; subclasses say why.
    """
    if len(data) > MAX_XML_FILE_BYTES:
        raise XmlTooLargeError(_("XML file exceeds {limit} bytes").format(limit=MAX_XML_FILE_BYTES))
    return _pages(data, "xml", worker, open_timeout, page_timeout)


def extract_docx(
    data: bytes,
    *,
    worker: Sequence[str] = WORKER_COMMAND,
    open_timeout: float = OFFICE_OPEN_TIMEOUT_S,
    page_timeout: float = OFFICE_PAGE_TIMEOUT_S,
) -> Iterator[Page]:
    """Yield the pages of a Word document: parts split at page and section breaks.

    Raises:
        OfficeError: If the file is refused; subclasses say why.
    """
    if len(data) > MAX_OFFICE_FILE_BYTES:
        raise OfficeTooLargeError(
            _("Office file exceeds {limit} bytes").format(limit=MAX_OFFICE_FILE_BYTES)
        )
    return _pages(data, "docx", worker, open_timeout, page_timeout)


def extract_xlsx(
    data: bytes,
    *,
    worker: Sequence[str] = WORKER_COMMAND,
    open_timeout: float = OFFICE_OPEN_TIMEOUT_S,
    page_timeout: float = OFFICE_PAGE_TIMEOUT_S,
) -> Iterator[Page]:
    """Yield the pages of an Excel workbook: one per sheet, in workbook order.

    Raises:
        OfficeError: If the file is refused; subclasses say why.
    """
    if len(data) > MAX_OFFICE_FILE_BYTES:
        raise OfficeTooLargeError(
            _("Office file exceeds {limit} bytes").format(limit=MAX_OFFICE_FILE_BYTES)
        )
    return _pages(data, "xlsx", worker, open_timeout, page_timeout)


def is_failed_page(page: Page) -> bool:
    """Whether a page is the illegible placeholder for one the worker could not read.

    Such a page may read fine on a retry, so callers should not cache it.
    """
    return page.blocks == (_FAILED_BLOCK,)


def _pages(
    data: bytes, kind: str, command: Sequence[str], open_timeout: float, page_timeout: float
) -> Iterator[Page]:
    pages: int | None = None
    first = 0
    restarts = 0
    while pages is None or first < pages:
        with _Worker([*command, kind, str(first)], data) as worker:
            try:
                opened = _open(worker, open_timeout, pages)
            except WorkerError:
                raise OfficeExtractionError(
                    _("the document worker failed to open the file")
                ) from None
            pages = opened.pages
            try:
                for index in range(first, pages):
                    yield _page(worker, index, _ENGINES[kind], page_timeout)
                    first = index + 1
            except WorkerError:
                restarts += 1
                if restarts > OFFICE_MAX_WORKER_RESTARTS:
                    raise OfficeExtractionError(
                        _("the file keeps crashing or stalling the document worker")
                    ) from None
                failed = first
            else:
                continue
        # Outside the "with": the stalled worker is gone before the page is reported.
        yield _failed_page(failed)
        first = failed + 1


def _open(worker: "_Worker", timeout: float, known: int | None) -> Opened:
    message = worker.message(timeout)
    if isinstance(message, Refused):
        # The worker sends fixed English sentences, marked for translation
        # where it writes them; never used as format strings.
        raise _REFUSALS[message.code](i18n.gettext(message.message))
    if not isinstance(message, Opened) or (known is not None and message.pages != known):
        raise WorkerError
    return message


def _page(worker: "_Worker", index: int, engine: str, timeout: float) -> Page:
    message = worker.message(timeout)
    if isinstance(message, PageFailed) and message.index == index:
        return _failed_page(index)
    if not isinstance(message, PageRead) or message.page.index != index:
        raise WorkerError
    if any(block.origin_engine != engine for block in message.page.blocks):
        raise WorkerError
    return message.page


# The only block of a page the worker could not read. The readers never flag
# a paragraph illegible (only images and equations), so this block is never
# confused with real content.
_FAILED_BLOCK = Block(
    id="b0",
    type=BlockType.PARAGRAPH,
    reading_order=0,
    origin_engine="office-worker",
    flags=(BlockFlag.ILLEGIBLE,),
)


def _failed_page(index: int) -> Page:
    """A page the worker could not read: one illegible block, never a silent gap."""
    return Page(
        index=index, width=1.0, height=1.0, origin=PageOrigin.NATIVE, blocks=(_FAILED_BLOCK,)
    )


class _Worker(WorkerProcess):
    """The Office and XML worker reading one file."""

    def __init__(self, command: Sequence[str], data: bytes) -> None:
        super().__init__(command, data, max_frame_bytes=OFFICE_MAX_MESSAGE_BYTES)

    def message(self, timeout: float) -> Message:
        """The next frame, parsed as a message.

        Raises:
            WorkerError: On timeout, end of output, or an invalid message.
        """
        try:
            return parse_message(self.frame(timeout))
        except ProtocolError:
            raise WorkerError from None
