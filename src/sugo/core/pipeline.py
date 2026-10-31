"""Convert one file into compact Markdown: the multi-pass pipeline (ADR-006, ADR-046).

Pass 1 extracts every page into the page store, which is the page cache:
pages already there from an earlier run are not extracted again, so an
interrupted job resumes and OCR is never redone. Pass 2 lets the analyzer
observe every page. Pass 3 cleans each page with the document-wide
statistics, caches the result and renders it. Only one page is in memory at
a time, whatever the document's length.

The input is routed by its content, never by its file name: PDFs to the
isolated PDF extractor (ADR-043), PNG, JPEG and WEBP to the image pipeline,
XML to the isolated Office and XML reader (ADR-054).
Without a persistent cache the job uses a private temporary one, deleted at
the end. Extracted pages the cache could not store are kept in memory
instead, so a full disk loses nothing; memory then grows with the document.
"""

import hashlib
import json
import logging
from collections import Counter
from collections.abc import Callable, Generator, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from importlib.metadata import version
from pathlib import Path
from types import MappingProxyType
from typing import ClassVar, Protocol, TypeVar

from sugo.analyzers.edges import EdgeAnalyzer, EdgeStats
from sugo.analyzers.lexicon import Lexicon, LexiconAnalyzer
from sugo.chunkers.sections import SectionChunker
from sugo.cleaners.headers_footers import HeaderFooterCleaner
from sugo.cleaners.hidden_text import HiddenTextCleaner
from sugo.cleaners.page_numbers import PageNumberCleaner
from sugo.cleaners.text_normalization import TextNormalizationCleaner
from sugo.cleaners.tracking_urls import TrackingUrlCleaner
from sugo.cleaners.ui_chrome import UiChromeCleaner
from sugo.core.chunks import Chunk
from sugo.core.constants import (
    CHUNK_MIN_TOKENS,
    MAX_IMAGE_FILE_BYTES,
    MAX_PDF_FILE_BYTES,
    MAX_XML_FILE_BYTES,
)
from sugo.core.decisions import InvalidDecisionError, Proposal, apply_decisions
from sugo.core.models import BlockFlag, Page
from sugo.extractors.image.extract import extract_page
from sugo.extractors.image.loader import UnsupportedImageError, detect_format
from sugo.extractors.image.ocr_engine import OcrEngine
from sugo.extractors.office import extract as office
from sugo.extractors.pymupdf.extract import (
    PDF_SIGNATURE,
    PDF_SIGNATURE_WINDOW,
    default_ocr_engine,
    extract_pdf,
    is_failed_page,
)
from sugo.i18n import gettext as _
from sugo.metrics.tokenizer import count_tokens
from sugo.serializers.markdown import render
from sugo.storage.page_cache import (
    CacheLevel,
    CacheUnavailableError,
    PageCache,
    extraction_key,
    output_key,
)
from sugo.storage.paths import StorageDirError

_log = logging.getLogger(__name__)

# The largest file any extractor accepts; each one applies its own limit.
_MAX_INPUT_BYTES = max(MAX_PDF_FILE_BYTES, MAX_IMAGE_FILE_BYTES, MAX_XML_FILE_BYTES)


_Stats = TypeVar("_Stats", contravariant=True)


class Cleaner(Protocol[_Stats]):
    """What the pipeline needs from a cleaner (ARCHITECTURE §4)."""

    name: ClassVar[str]

    def propose(self, page: Page, stats: _Stats) -> Sequence[Proposal]:
        """Return the removals and edits this cleaner proposes for the page."""
        ...


# Order matters: hidden text goes first, so it never counts as content; page
# numbers before running headers, which leave page-number text to them.
CLEANERS: tuple[Cleaner[EdgeStats], ...] = (
    HiddenTextCleaner(),
    UiChromeCleaner(),
    PageNumberCleaner(),
    HeaderFooterCleaner(),
)

# For callers that pass no languages; the ports pass the configured ones (ADR-051).
DEFAULT_LANGUAGES = ("en",)


class InputKind(StrEnum):
    """Which extractor reads the input."""

    PDF = "pdf"
    IMAGE = "image"
    XML = "xml"


class InputUnsupportedError(ValueError):
    """The input is neither a PDF, a supported image nor XML."""

    code: ClassVar[str] = "INPUT_UNSUPPORTED"


@dataclass(frozen=True)
class Conversion:
    """The result of converting one file."""

    markdown: str
    kind: InputKind
    # The source as given by the caller, e.g. "clients/agreement.pdf".
    source: str | None
    source_sha256: str
    pages: int
    # Page numbers, counted from 1, that could not be read: their content is
    # missing from the Markdown, so the conversion is only partly successful.
    failed_pages: tuple[int, ...]
    # Blocks removed, per cleaner name, so the user can see what went and why.
    removed: Mapping[str, int]
    # Empty unless chunks were asked for (``max_chunk_tokens``).
    chunks: tuple[Chunk, ...]
    sugo_version: str
    # Digest of the settings that change the output (cleaners, chunk size).
    config_hash: str
    # Tokens of the text before cleaning, the baseline of ADR-003; None
    # unless asked for (``count_raw_tokens``), as it renders every page twice.
    raw_tokens: int | None = None
    # Text edits, per cleaner name (ADR-050); each one is recorded on its block.
    edited: Mapping[str, int] = MappingProxyType({})
    # Blocks flagged as holding credentials, removed or not: the MCP server
    # never sends such a document to an agent (ADR-053).
    secret_blocks: int = 0


def convert_file(
    path: Path,
    *,
    cache: PageCache | None = None,
    ocr: Callable[[], OcrEngine] = default_ocr_engine,
    source: str | None = None,
    max_chunk_tokens: int | None = None,
    count_raw_tokens: bool = False,
    languages: tuple[str, ...] = DEFAULT_LANGUAGES,
    strip_tracking_urls: bool = True,
) -> Conversion:
    """Read a file and convert it; ``source`` defaults to the path as given.

    Raises:
        InputUnsupportedError: If the file is neither a PDF, a supported image nor XML.
        OSError: If the file cannot be read.
        sugo.extractors.pymupdf.extract.PdfError: If a PDF is refused.
        sugo.extractors.image.loader.ImageLoadError: If an image is refused.
        sugo.extractors.office.extract.XmlError: If an XML file is refused.
    """
    return convert(
        read_input(path),
        cache=cache,
        ocr=ocr,
        source=path.as_posix() if source is None else source,
        max_chunk_tokens=max_chunk_tokens,
        count_raw_tokens=count_raw_tokens,
        languages=languages,
        strip_tracking_urls=strip_tracking_urls,
    )


def read_input(path: Path) -> bytes:
    """Read a file to convert, stopping just past the largest size any extractor accepts.

    Raises:
        OSError: If the file cannot be read.
    """
    with path.open("rb") as file:
        # One byte more than the limit lets the extractor report "too large".
        return file.read(_MAX_INPUT_BYTES + 1)


def convert(
    data: bytes,
    *,
    cache: PageCache | None = None,
    ocr: Callable[[], OcrEngine] = default_ocr_engine,
    source: str | None = None,
    max_chunk_tokens: int | None = None,
    count_raw_tokens: bool = False,
    languages: tuple[str, ...] = DEFAULT_LANGUAGES,
    strip_tracking_urls: bool = True,
) -> Conversion:
    """Convert a document's bytes into Markdown, and into chunks if asked.

    Args:
        data: The file's content.
        cache: The page cache; None uses a private temporary one for this job.
        ocr: Called at most once, when a page needs OCR, to get the engine.
        source: Name of the document, e.g. its path as the user gave it. It
            gives the document its id, kept across new editions (ADR-047).
        max_chunk_tokens: Chunk size in tokens; None makes no chunks.
        count_raw_tokens: Also count the tokens of the uncleaned text.
        languages: Languages whose text rules apply (ADR-025); others get
            only the universal rules.
        strip_tracking_urls: Delete tracking parameters from URLs.

    Raises:
        ValueError: If a language has no pack, or ``max_chunk_tokens`` is too small.
        InputUnsupportedError: If the data is neither a PDF, a supported image nor XML.
        sugo.extractors.pymupdf.extract.PdfError: If a PDF is refused.
        sugo.extractors.image.loader.ImageLoadError: If an image is refused.
        sugo.extractors.office.extract.XmlError: If an XML file is refused.
    """
    kind = detect_kind(data)
    if max_chunk_tokens is not None and max_chunk_tokens < CHUNK_MIN_TOKENS:
        raise ValueError(f"max_chunk_tokens must be at least {CHUNK_MIN_TOKENS}")
    options = _Options(
        source=source,
        max_chunk_tokens=max_chunk_tokens,
        count_raw_tokens=count_raw_tokens,
        text_cleaners=_text_cleaners(languages, strip_tracking_urls=strip_tracking_urls),
        languages=tuple(sorted(set(languages))),
    )
    if cache is not None:
        return _Job(data, kind, cache, ocr, options).run()
    try:
        job_cache = PageCache.ephemeral()
    except (CacheUnavailableError, StorageDirError, OSError):
        # No room even for a temporary store: the job still runs, with its
        # pages in memory.
        _log.warning("no temporary page store; pages kept in memory")
        return _Job(data, kind, None, ocr, options).run()
    with job_cache:
        return _Job(data, kind, job_cache, ocr, options).run()


def detect_kind(data: bytes) -> InputKind:
    """Route the input by its content (magic bytes), never by its name.

    Raises:
        InputUnsupportedError: If the data is neither a PDF, a supported image nor XML.
    """
    if PDF_SIGNATURE in data[:PDF_SIGNATURE_WINDOW]:
        return InputKind.PDF
    try:
        detect_format(data)
    except UnsupportedImageError:
        if office.looks_like_xml(data):
            return InputKind.XML
        raise InputUnsupportedError(
            _("not a supported input: PDF, PNG, JPEG, WEBP or XML expected")
        ) from None
    return InputKind.IMAGE


def _text_cleaners(
    languages: tuple[str, ...], *, strip_tracking_urls: bool
) -> tuple[Cleaner[Lexicon], ...]:
    """The cleaners that edit text, after the ones that remove blocks (ADR-050).

    Raises:
        ValueError: If a language has no pack.
    """
    cleaners: list[Cleaner[Lexicon]] = [TextNormalizationCleaner(languages)]
    if strip_tracking_urls:
        cleaners.append(TrackingUrlCleaner())
    return tuple(cleaners)


@dataclass(frozen=True)
class _Options:
    source: str | None
    max_chunk_tokens: int | None
    # Not part of the config hash: it measures the output, never changes it.
    count_raw_tokens: bool
    text_cleaners: tuple[Cleaner[Lexicon], ...]
    languages: tuple[str, ...]

    def cleaning(self) -> str:
        """The settings that change cleaned pages, part of their cache key."""
        names = [cleaner.name for cleaner in CLEANERS]
        names += [cleaner.name for cleaner in self.text_cleaners]
        return f"{','.join(names)};languages={','.join(self.languages)}"

    def config_hash(self) -> str:
        settings = {"cleaners": self.cleaning(), "max_chunk_tokens": self.max_chunk_tokens}
        return hashlib.sha256(json.dumps(settings, sort_keys=True).encode()).hexdigest()


class _Job:
    """One conversion: the passes over one document (the fourth, chunking, if asked)."""

    def __init__(
        self,
        data: bytes,
        kind: InputKind,
        cache: PageCache | None,
        ocr: Callable[[], OcrEngine],
        options: _Options,
    ) -> None:
        self._data = data
        self._options = options
        self._kind = kind
        self._cache = cache
        self._ocr = _OnceOcr(ocr)
        self._sha256 = hashlib.sha256(data).hexdigest()
        self._engine = _engine_identity(kind)
        # Extracted pages the cache could not or must not store, by index.
        self._spilled: dict[int, Page] = {}
        # Pages the PDF worker could not read in this run.
        self._failed: set[int] = set()

    def run(self) -> Conversion:
        count = self._extract()
        edges, words = EdgeAnalyzer(), LexiconAnalyzer()
        for index in range(count):
            page = self._extracted(index)
            edges.observe(page)
            words.observe(page)
        stats, lexicon = edges.finalize(), words.finalize()
        # A cleaned page depends on every page of the document, through the
        # statistics: if any page reads differently, all are cleaned again.
        cleaning = f"{self._options.cleaning()};{stats.digest()};{lexicon.digest()}"
        sugo_version = version("sugo")
        config_hash = self._options.config_hash()
        chunker = (
            None
            if self._options.max_chunk_tokens is None
            else SectionChunker(
                source=self._options.source,
                source_sha256=self._sha256,
                sugo_version=sugo_version,
                config_hash=config_hash,
                max_tokens=self._options.max_chunk_tokens,
            )
        )
        removed: Counter[str] = Counter()
        edited: Counter[str] = Counter()
        secret_blocks = 0
        parts: list[str] = []
        raw_parts: list[str] | None = [] if self._options.count_raw_tokens else None
        chunks: list[Chunk] = []
        for index in range(count):
            if raw_parts is not None:
                raw_text = render(self._extracted(index).blocks)
                if raw_text:
                    raw_parts.append(raw_text)
            page = self._cleaned(index, stats, lexicon, cleaning)
            removed.update(block.removed_by for block in page.blocks if block.removed_by)
            edited.update(edit.edited_by for block in page.blocks for edit in block.edits)
            secret_blocks += sum(BlockFlag.SECRET in block.flags for block in page.blocks)
            text = render(page.blocks)
            if text:
                parts.append(text)
            if chunker is not None:
                # Pass 4 runs alongside pass 3, so pages are read only once.
                chunks.extend(chunker.add(page))
        if chunker is not None:
            chunks.extend(chunker.finish())
        return Conversion(
            # Pages follow each other like paragraphs (ADR-046).
            markdown="\n\n".join(parts),
            kind=self._kind,
            source=self._options.source,
            source_sha256=self._sha256,
            pages=count,
            failed_pages=tuple(index + 1 for index in sorted(self._failed)),
            removed=MappingProxyType(dict(sorted(removed.items()))),
            chunks=tuple(chunks),
            sugo_version=sugo_version,
            config_hash=config_hash,
            # Joined like the Markdown, so both counts measure the same layout.
            raw_tokens=None if raw_parts is None else count_tokens("\n\n".join(raw_parts)),
            edited=MappingProxyType(dict(sorted(edited.items()))),
            secret_blocks=secret_blocks,
        )

    def _extract(self) -> int:
        """Pass 1: put every page in the page store; return the page count."""
        if self._kind is InputKind.IMAGE:
            if self._get(CacheLevel.EXTRACTION, self._key(0)) is None:
                self._keep(extract_page(self._data, self._ocr()))
            return 1
        if self._kind is InputKind.XML:
            if self._get(CacheLevel.EXTRACTION, self._key(0)) is None:
                for page in office.extract_xml(self._data):
                    self._keep(page)
            return 1
        # Pages cached by an earlier run are neither laid out nor read with
        # OCR again: the extractor starts at the first missing one and skips
        # the cached ones after it.
        start = 0
        while self._get(CacheLevel.EXTRACTION, self._key(start)) is not None:
            start += 1
        count = start

        def cached(index: int) -> bool:
            nonlocal count
            count = max(count, index + 1)
            return self._get(CacheLevel.EXTRACTION, self._key(index)) is not None

        for page in extract_pdf(self._data, ocr=self._ocr, start=start, skip=cached):
            self._keep(page)
            count = max(count, page.index + 1)
        return count

    def _keep(self, page: Page) -> None:
        """Store an extracted page, or keep it in memory if it cannot or must not be cached."""
        if self._is_failed(page):
            # A page the worker could not read may read fine next time.
            self._failed.add(page.index)
            self._spilled[page.index] = page
        elif not self._put(CacheLevel.EXTRACTION, self._key(page.index), page):
            self._spilled[page.index] = page

    def _extracted(self, index: int) -> Page:
        spilled = self._spilled.get(index)
        if spilled is not None:
            return spilled
        page = self._get(CacheLevel.EXTRACTION, self._key(index))
        if page is None:
            # Stored moments ago, yet gone: another process cleared the cache
            # or the entry was damaged. Read this page again, once.
            _log.warning("page missing from the page store; extracting it again")
            page = self._reextract(index)
            if self._is_failed(page):
                self._failed.add(index)
            # Kept in memory: a cache that just lost it may lose it again.
            self._spilled[index] = page
        return page

    def _cleaned(self, index: int, stats: EdgeStats, lexicon: Lexicon, cleaning: str) -> Page:
        """Pass 3: one page cleaned with the document's statistics, from the cache if there."""
        key = output_key(extraction=self._key(index), cleaning=cleaning)
        # A failed page is never cached, nor what was cleaned from it.
        failed = index in self._failed
        if not failed:
            cached = self._get(CacheLevel.OUTPUT, key)
            if cached is not None:
                return cached
        page = self._extracted(index)
        for cleaner in CLEANERS:
            page = _cleaned_by(page, cleaner, stats)
        for text_cleaner in self._options.text_cleaners:
            page = _cleaned_by(page, text_cleaner, lexicon)
        if not failed:
            # Not kept in memory if refused: pass 3 never reads it back.
            self._put(CacheLevel.OUTPUT, key, page)
        return page

    def _is_failed(self, page: Page) -> bool:
        if self._kind is InputKind.PDF:
            return is_failed_page(page)
        return self._kind is InputKind.XML and office.is_failed_page(page)

    def _key(self, index: int) -> bytes:
        return extraction_key(source_sha256=self._sha256, page_index=index, engine=self._engine)

    def _get(self, level: CacheLevel, key: bytes) -> Page | None:
        return None if self._cache is None else self._cache.get(level, key)

    def _put(self, level: CacheLevel, key: bytes, page: Page) -> bool:
        return self._cache is not None and self._cache.put(level, key, page)

    def _reextract(self, index: int) -> Page:
        if self._kind is InputKind.IMAGE:
            return extract_page(self._data, self._ocr())
        pages = (
            office.extract_xml(self._data)
            if self._kind is InputKind.XML
            else extract_pdf(self._data, ocr=self._ocr, start=index)
        )
        try:
            return next(pages)
        finally:
            # Stops the worker instead of letting it read the remaining pages.
            if isinstance(pages, Generator):
                pages.close()


def _cleaned_by[S](page: Page, cleaner: Cleaner[S], stats: S) -> Page:
    """One cleaner's decisions applied; if the core refuses them, the page as it was.

    A refused proposal is a bug in the cleaner, not in the document: the
    page goes on without that cleaner's changes, and the warning names the
    cleaner only (principle 11).
    """
    try:
        return apply_decisions(page, cleaner.propose(page, stats), cleaner=cleaner.name)
    except InvalidDecisionError as error:
        _log.warning("cleaner %s skipped on a page: %s", error.cleaner, error)
        return page


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
    if kind is InputKind.XML:
        return f"{kind.value}:defusedxml={version('defusedxml')}"
    libraries = ["rapidocr", "onnxruntime", "pillow"]
    if kind is InputKind.PDF:
        libraries.insert(0, "pymupdf")
    return f"{kind.value}:" + ";".join(f"{name}={version(name)}" for name in libraries)
