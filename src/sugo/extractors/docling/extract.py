"""Run Docling on a document in its worker process and collect its pages (ADR-071).

The worker is started per document. Its frames are validated twice: against
the protocol, then as IR pages. A worker that stalls, crashes, sends
something invalid or reports a failure stops the conversion with an error:
a `normal` result is never silently a partial one.
"""

import importlib.util
from collections.abc import Sequence
from pathlib import Path
from typing import ClassVar

from sugo.core.constants import DOCLING_LOAD_TIMEOUT_S, DOCLING_PAGE_TIMEOUT_S
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

    Args:
        data: The file's bytes.
        kind: ``pdf``.
        page_count: Pages the document has, for the time limit.
        artifacts: The folder holding Docling's models (ADR-071 §2).

    Raises:
        NormalLevelMissingError: If the worker cannot import Docling.
        NormalFailedError: If Docling or its worker failed.
    """
    # Docling reads the whole file before sending the first page.
    first_wait = load_timeout + page_timeout * max(page_count, 1)
    pages: list[Page] = []
    try:
        with WorkerProcess(
            [*worker, kind, str(artifacts)], data, max_frame_bytes=MAX_MESSAGE_BYTES
        ) as process:
            message = parse_message(process.frame(first_wait))
            if isinstance(message, Refused):
                if message.code == "LEVEL_MISSING":
                    raise NormalLevelMissingError(_missing())
                raise NormalFailedError(_failed())
            if not isinstance(message, Opened):
                raise NormalFailedError(_failed())
            for _index in range(message.pages):
                page = parse_message(process.frame(page_timeout))
                if not isinstance(page, PageRead) or page.page.index != len(pages):
                    raise NormalFailedError(_failed())
                pages.append(page.page)
    except (WorkerError, ProtocolError, OSError):
        raise NormalFailedError(_failed()) from None
    return pages


def _missing() -> str:
    return _("The normal level is not installed.")


def _failed() -> str:
    return _("Docling could not read this document.")
