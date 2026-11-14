"""Docling worker: reads one file with Docling in its own process (ADR-071).

Started by ``sugo.extractors.docling.extract`` as
``python -I -m sugo.extractors.docling.worker KIND ARTIFACTS``; reads the
file from stdin and writes frames (``sugo.extractors.docling.protocol``) to
a private copy of stdout. Docling parses untrusted files with native code
and loads PyTorch models: running it here keeps a crash, a hang or a memory
blow-up out of Sugo, and the time limits real.

Before Docling is imported, every way it could reach the network is shut:
Hugging Face and transformers run offline, the models come from Sugo's own
folder (``artifacts_path``), and remote services and external plugins stay
off. Its OCR is off too: scanned pages are Sugo's (ADR-071 §3).
"""

import io
import os
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from sugo.core.constants import (
    DOCLING_THREADS,
    DOCLING_WORKER_MEMORY_BYTES,
    MAX_PDF_FILE_BYTES,
)
from sugo.extractors.docling.mapping import to_pages
from sugo.extractors.docling.protocol import Message, Opened, PageRead, Refused, write_message
from sugo.extractors.worker import limit_resources, private_stdout

# Set before Docling, transformers or huggingface_hub is imported.
_OFFLINE_ENVIRONMENT = {
    "HF_HUB_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
    "HF_HUB_DISABLE_TELEMETRY": "1",
    "DO_NOT_TRACK": "1",
    "OMP_NUM_THREADS": str(DOCLING_THREADS),
}
KINDS = ("pdf",)


def main() -> None:
    """Entry point of the worker process."""
    os.environ.update(_OFFLINE_ENVIRONMENT)
    limit_resources(DOCLING_WORKER_MEMORY_BYTES)
    kind, artifacts = sys.argv[1], Path(sys.argv[2])
    data = sys.stdin.buffer.read(MAX_PDF_FILE_BYTES + 1)
    with private_stdout() as out:
        for message in run(data, kind, artifacts):
            write_message(out, message)


def run(data: bytes, kind: str, artifacts: Path) -> Iterator[Message]:
    """Convert the file with Docling and yield its pages as IR."""
    if kind not in KINDS:
        raise ValueError(f"unknown kind {kind!r}")
    try:
        document = _convert(data, kind, artifacts)
    except ImportError:
        yield Refused(code="LEVEL_MISSING", message="Docling is not installed")
        return
    except Exception as error:  # noqa: BLE001 - any Docling failure is reported, never its text
        yield Refused(code="NORMAL_FAILED", message=f"Docling failed: {type(error).__name__}")
        return
    pages = document.get("pages")
    count = len(pages) if isinstance(pages, dict) and pages else 1
    yield Opened(pages=count)
    for page in to_pages(document, page_count=count):
        yield PageRead(page=page)


def _convert(data: bytes, kind: str, artifacts: Path) -> dict[str, Any]:
    """Docling's JSON export of the file."""
    import torch
    from docling.datamodel.base_models import DocumentStream, InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions, TableFormerMode
    from docling.document_converter import DocumentConverter, PdfFormatOption

    torch.set_num_threads(DOCLING_THREADS)
    options = PdfPipelineOptions(artifacts_path=artifacts)
    options.do_ocr = False
    options.do_table_structure = True
    options.table_structure_options.mode = TableFormerMode.ACCURATE
    options.enable_remote_services = False
    options.allow_external_plugins = False
    options.generate_page_images = False
    options.generate_picture_images = False
    converter = DocumentConverter(
        allowed_formats=[InputFormat.PDF],
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)},
    )
    stream = DocumentStream(name=f"input.{kind}", stream=io.BytesIO(data))
    result = converter.convert(stream, raises_on_error=True)
    exported: dict[str, Any] = result.document.export_to_dict()
    return exported


if __name__ == "__main__":
    main()
