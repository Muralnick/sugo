"""Convert one file into compact Markdown: the multi-pass pipeline (ADR-006, ADR-046).

Pass 1 extracts every page into the page store, which is the page cache:
pages already there from an earlier run are not extracted again, so an
interrupted job resumes and OCR is never redone. Pass 2 lets the analyzer
observe every page. Pass 3 cleans each page with the document-wide
statistics, caches the result and renders it. Only one page is in memory at
a time, whatever the document's length.

The input is routed by its content, never by its file name: PDFs to the
isolated PDF extractor (ADR-043), PNG, JPEG and WEBP to the image pipeline.
Without a persistent cache the job uses a private temporary one, deleted at
the end. Pages the cache could not store are kept in memory instead, so a
full disk slows nothing down and loses nothing.
"""

import hashlib
import logging
from collections import Counter
from collections.abc import Callable, Generator, Mapping
from dataclasses import dataclass
from enum import StrEnum
from importlib.metadata import version
from pathlib import Path
from types import MappingProxyType
from typing import ClassVar, Protocol

from sugo.analyzers.edges import EdgeAnalyzer, EdgeStats
from sugo.cleaners.headers_footers import HeaderFooterCleaner
from sugo.cleaners.hidden_text import HiddenTextCleaner
from sugo.cleaners.page_numbers import PageNumberCleaner
from sugo.cleaners.ui_chrome import UiChromeCleaner
from sugo.core.constants import MAX_IMAGE_FILE_BYTES, MAX_PDF_FILE_BYTES
from sugo.core.decisions import Decision, apply_decisions
from sugo.core.models import Page
from sugo.extractors.image.extract import extract_page
from sugo.extractors.image.loader import UnsupportedImageError, detect_format
from sugo.extractors.image.ocr_engine import OcrEngine
from sugo.extractors.pymupdf.extract import (
    PDF_SIGNATURE,
    PDF_SIGNATURE_WINDOW,
    default_ocr_engine,
    extract_pdf,
    is_failed_page,
)
from sugo.serializers.markdown import render
from sugo.storage.page_cache import CacheLevel, PageCache, extraction_key, output_key

_log = logging.getLogger(__name__)

# The largest file any extractor accepts; each one applies its own limit.
_MAX_INPUT_BYTES = max(MAX_PDF_FILE_BYTES, MAX_IMAGE_FILE_BYTES)


class Cleaner(Protocol):
    """What the pipeline needs from a cleaner (ARCHITECTURE §4)."""

    name: ClassVar[str]

    def propose(self, page: Page, stats: EdgeStats) -> list[Decision]:
        """Return the removals this cleaner proposes for the page."""
        ...


# Order matters: hidden text goes first, so it never counts as content; page
# numbers before running headers, which leave page-number text to them.
CLEANERS: tuple[Cleaner, ...] = (
    HiddenTextCleaner(),
    UiChromeCleaner(),
    PageNumberCleaner(),
    HeaderFooterCleaner(),
)
# Part of the output cache key: another cleaner set gives other pages.
_CLEANING = ",".join(cleaner.name for cleaner in CLEANERS)


class InputKind(StrEnum):
    """Which extractor reads the input."""

    PDF = "pdf"
    IMAGE = "image"


class InputUnsupportedError(ValueError):
    """The input is neither a PDF nor a supported image."""

    code: ClassVar[str] = "INPUT_UNSUPPORTED"


@dataclass(frozen=True)
class Conversion:
    """The result of converting one file."""

    markdown: str
    kind: InputKind
    source_sha256: str
    pages: int
    # Blocks removed, per cleaner name, so the user can see what went and why.
    removed: Mapping[str, int]


def convert_file(
    path: Path,
    *,
    cache: PageCache | None = None,
    ocr: Callable[[], OcrEngine] = default_ocr_engine,
) -> Conversion:
    """Read a file and convert it.

    Raises:
        InputUnsupportedError: If the file is neither a PDF nor a supported image.
        OSError: If the file cannot be read.
        sugo.extractors.pymupdf.extract.PdfError: If a PDF is refused.
        sugo.extractors.image.loader.ImageLoadError: If an image is refused.
    """
    with path.open("rb") as file:
        # One byte more than the limit lets the extractor report "too large".
        data = file.read(_MAX_INPUT_BYTES + 1)
    return convert(data, cache=cache, ocr=ocr)


def convert(
    data: bytes,
    *,
    cache: PageCache | None = None,
    ocr: Callable[[], OcrEngine] = default_ocr_engine,
) -> Conversion:
    """Convert a document's bytes into Markdown.

    Args:
        data: The file's content.
        cache: The page cache; None uses a private temporary one for this job.
        ocr: Called at most once, when a page needs OCR, to get the engine.

    Raises:
        InputUnsupportedError: If the data is neither a PDF nor a supported image.
        sugo.extractors.pymupdf.extract.PdfError: If a PDF is refused.
        sugo.extractors.image.loader.ImageLoadError: If an image is refused.
    """
    kind = detect_kind(data)
    if cache is None:
        with PageCache.ephemeral() as job_cache:
            return _Job(data, kind, job_cache, ocr).run()
    return _Job(data, kind, cache, ocr).run()


def detect_kind(data: bytes) -> InputKind:
    """Route the input by its content (magic bytes), never by its name.

    Raises:
        InputUnsupportedError: If the data is neither a PDF nor a supported image.
    """
    if PDF_SIGNATURE in data[:PDF_SIGNATURE_WINDOW]:
        return InputKind.PDF
    try:
        detect_format(data)
    except UnsupportedImageError:
        raise InputUnsupportedError(
            "not a supported input: PDF, PNG, JPEG or WEBP expected"
        ) from None
    return InputKind.IMAGE


class _Job:
    """One conversion: the three passes over one document."""

    def __init__(
        self, data: bytes, kind: InputKind, cache: PageCache, ocr: Callable[[], OcrEngine]
    ) -> None:
        self._data = data
        self._kind = kind
        self._cache = cache
        self._ocr = _OnceOcr(ocr)
        self._sha256 = hashlib.sha256(data).hexdigest()
        self._engine = _engine_identity(kind)
        # Pages the cache could not store, by level and index.
        self._spilled: dict[tuple[CacheLevel, int], Page] = {}

    def run(self) -> Conversion:
        count = self._extract()
        analyzer = EdgeAnalyzer()
        for index in range(count):
            analyzer.observe(self._extracted(index))
        stats = analyzer.finalize()
        removed: Counter[str] = Counter()
        parts: list[str] = []
        for index in range(count):
            page = self._cleaned(index, stats)
            removed.update(block.removed_by for block in page.blocks if block.removed_by)
            text = render(page.blocks)
            if text:
                parts.append(text)
        return Conversion(
            # Pages follow each other like paragraphs (ADR-046).
            markdown="\n\n".join(parts),
            kind=self._kind,
            source_sha256=self._sha256,
            pages=count,
            removed=MappingProxyType(dict(sorted(removed.items()))),
        )

    def _extract(self) -> int:
        """Pass 1: put every page in the page store; return the page count."""
        if self._kind is InputKind.IMAGE:
            if self._cache.get(CacheLevel.EXTRACTION, self._key(0)) is None:
                self._store(CacheLevel.EXTRACTION, extract_page(self._data, self._ocr()))
            return 1
        # Pages cached by an earlier run of this job are not read again.
        start = 0
        while self._cache.get(CacheLevel.EXTRACTION, self._key(start)) is not None:
            start += 1
        count = start
        for page in extract_pdf(self._data, ocr=self._ocr, start=start):
            # A page the worker could not read may read fine next time.
            self._store(CacheLevel.EXTRACTION, page, cache=not is_failed_page(page))
            count = page.index + 1
        return count

    def _extracted(self, index: int) -> Page:
        return self._load(CacheLevel.EXTRACTION, self._key(index), index)

    def _cleaned(self, index: int, stats: EdgeStats) -> Page:
        """Pass 3: one page cleaned with the document's statistics, from the cache if there."""
        key = output_key(extraction=self._key(index), cleaning=_CLEANING)
        cached = self._cache.get(CacheLevel.OUTPUT, key)
        if cached is not None:
            return cached
        page = self._extracted(index)
        for cleaner in CLEANERS:
            page = apply_decisions(page, cleaner.propose(page, stats), cleaner=cleaner.name)
        self._store(CacheLevel.OUTPUT, page)
        return page

    def _key(self, index: int) -> bytes:
        return extraction_key(source_sha256=self._sha256, page_index=index, engine=self._engine)

    def _store(self, level: CacheLevel, page: Page, *, cache: bool = True) -> None:
        if level is CacheLevel.EXTRACTION:
            key = self._key(page.index)
        else:
            key = output_key(extraction=self._key(page.index), cleaning=_CLEANING)
        if not (cache and self._cache.put(level, key, page)):
            self._spilled[(level, page.index)] = page

    def _load(self, level: CacheLevel, key: bytes, index: int) -> Page:
        spilled = self._spilled.get((level, index))
        if spilled is not None:
            return spilled
        page = self._cache.get(level, key)
        if page is None:
            # Stored moments ago, yet gone: another process cleared the cache
            # or the entry was damaged. Read this page again.
            _log.warning("page missing from the page store; extracting it again")
            page = self._reextract(index)
        return page

    def _reextract(self, index: int) -> Page:
        if self._kind is InputKind.IMAGE:
            return extract_page(self._data, self._ocr())
        pages = extract_pdf(self._data, ocr=self._ocr, start=index)
        try:
            return next(pages)
        finally:
            # Stops the worker instead of letting it read the remaining pages.
            if isinstance(pages, Generator):
                pages.close()


class _OnceOcr:
    """Loads the OCR engine at the first page that needs it, then reuses it."""

    def __init__(self, factory: Callable[[], OcrEngine]) -> None:
        self._factory = factory
        self._engine: OcrEngine | None = None

    def __call__(self) -> OcrEngine:
        if self._engine is None:
            self._engine = self._factory()
        return self._engine


def _engine_identity(kind: InputKind) -> str:
    # Library versions change what the engines produce; Sugo's own code and
    # model hashes are already part of every key (ADR-045).
    libraries = ["rapidocr", "onnxruntime", "pillow"]
    if kind is InputKind.PDF:
        libraries.insert(0, "pymupdf")
    return f"{kind.value}:" + ";".join(f"{name}={version(name)}" for name in libraries)
