"""``sugo.convert``: one file in, Markdown and chunks out (ADR-067).

Heavy modules (the pipeline, the OCR engine, the workers) are imported on
the first call, so ``import sugo`` stays cheap.
"""

import logging
import os
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Literal

from sugo.core.chunks import Chunk
from sugo.core.constants import CHUNK_MAX_TOKENS_LIMIT, CHUNK_MIN_TOKENS

if TYPE_CHECKING:
    from sugo.config.settings import Settings
    from sugo.storage.page_cache import PageCache

_log = logging.getLogger(__name__)

CacheMode = Literal["ephemeral", "user"]
Level = Literal["lite"]
_CACHE_MODES = ("ephemeral", "user")
_LEVELS = ("lite",)


class SugoError(Exception):
    """A failure the user can act on, with the same stable code as the CLI and MCP.

    Match on ``code``, never on ``message``: the message is translated.
    """

    def __init__(
        self,
        code: str,
        message: str,
        hint: str | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint
        self.details: Mapping[str, Any] = MappingProxyType(dict(details or {}))

    def __repr__(self) -> str:
        return f"SugoError(code={self.code!r}, message={self.message!r})"


@dataclass(frozen=True, kw_only=True)
class Result:
    """What one conversion produced, with the facts the CLI's JSON output gives."""

    markdown: str
    # Empty unless ``chunks=True``.
    chunks: tuple[Chunk, ...]
    # The name as given, or the path as given; None for bytes without a name.
    source: str | None
    source_sha256: str
    # "d_" and 32 hex digits, the id every chunk of this document carries (ADR-047).
    document_id: str
    # "pdf", "image", "docx", "xlsx", "pptx" or "xml".
    kind: str
    pages: int
    # Pages, counted from 1, that could not be read: their content is missing.
    failed_pages: tuple[int, ...]
    # Blocks removed and texts edited, per cleaner name.
    removed: Mapping[str, int]
    edited: Mapping[str, int]
    # Blocks flagged as holding credentials, removed or not (ADR-053).
    secret_blocks: int
    # True when the text holds a PEM or OpenPGP private key header (ADR-053).
    holds_private_key: bool
    # o200k_base tokens of ``markdown`` (ADR-003).
    tokens: int
    sugo_version: str
    config_hash: str
    # The receipt as JSON, as ``sugo convert --receipt`` writes it; None unless asked for.
    receipt: Mapping[str, Any] | None

    @property
    def partial(self) -> bool:
        """True when some pages could not be read (exit code 3 in the CLI)."""
        return bool(self.failed_pages)

    @property
    def has_credentials(self) -> bool:
        """True when the file holds credentials: what the MCP server never sends."""
        return self.secret_blocks > 0 or self.holds_private_key


def convert(
    source: str | os.PathLike[str] | bytes,
    *,
    name: str | None = None,
    chunks: bool = False,
    max_tokens: int | None = None,
    receipt: bool = False,
    cache: CacheMode = "ephemeral",
    level: Level = "lite",
) -> Result:
    """Convert one file into compact Markdown, and into chunks if asked.

    Args:
        source: A path to one file, or the file's bytes. Never a folder or a URL.
        name: The document's name, which gives it its identity (ADR-047);
            defaults to the path as given, or None for bytes.
        chunks: Also split the Markdown into chunks for retrieval.
        max_tokens: Chunk size in tokens; defaults to the configured size.
            Only with ``chunks=True``.
        receipt: Also build a receipt of every removal and edit (ADR-056).
        cache: "ephemeral" uses a temporary page cache deleted after the call,
            so no document text stays on disk; "user" uses the user's
            persistent page cache, like the CLI, which is faster on repeated loads.
        level: The engine level; only "lite" exists in this version.

    Raises:
        SugoError: If Sugo refuses the file or the settings are not valid.
        OSError: If the path cannot be read.
        TypeError: If ``source`` is neither a path nor bytes.
        ValueError: If an argument is out of range.
    """
    _check_arguments(source, chunks=chunks, max_tokens=max_tokens, cache=cache, level=level)
    try:
        return _convert(
            source, name=name, chunks=chunks, max_tokens=max_tokens, receipt=receipt, cache=cache
        )
    except (SugoError, OSError):
        raise
    except Exception as error:
        failure = _as_sugo_error(error)
        if failure is None:
            raise
        raise failure from error


def _check_arguments(
    source: object, *, chunks: bool, max_tokens: int | None, cache: str, level: str
) -> None:
    if not isinstance(source, str | os.PathLike | bytes):
        raise TypeError(f"source must be a path or bytes, not {type(source).__name__}")
    if level not in _LEVELS:
        raise ValueError(f"level must be one of {_LEVELS}, not {level!r}")
    if cache not in _CACHE_MODES:
        raise ValueError(f"cache must be one of {_CACHE_MODES}, not {cache!r}")
    if max_tokens is not None:
        if not chunks:
            raise ValueError("max_tokens needs chunks=True")
        if not CHUNK_MIN_TOKENS <= max_tokens <= CHUNK_MAX_TOKENS_LIMIT:
            raise ValueError(
                f"max_tokens must be between {CHUNK_MIN_TOKENS} and {CHUNK_MAX_TOKENS_LIMIT}"
            )


def _convert(
    source: str | os.PathLike[str] | bytes,
    *,
    name: str | None,
    chunks: bool,
    max_tokens: int | None,
    receipt: bool,
    cache: CacheMode,
) -> Result:
    from sugo.chunkers.sections import document_id
    from sugo.core import pipeline
    from sugo.core.credentials import holds_private_key
    from sugo.metrics.tokenizer import count_tokens

    settings = _settings()
    if isinstance(source, bytes):
        data = source
    else:
        path = Path(source)
        data = pipeline.read_input(path)
        name = path.as_posix() if name is None else name
    with _page_cache(cache) as page_cache:
        conversion = pipeline.convert(
            data,
            cache=page_cache,
            source=name,
            max_chunk_tokens=(max_tokens or settings.chunking.max_tokens) if chunks else None,
            languages=settings.languages,
            strip_tracking_urls=settings.cleaning.strip_tracking_urls,
            receipt=receipt,
        )
    return Result(
        markdown=conversion.markdown,
        chunks=conversion.chunks,
        source=conversion.source,
        source_sha256=conversion.source_sha256,
        document_id=document_id(conversion.source, conversion.source_sha256),
        kind=conversion.kind.value,
        pages=conversion.pages,
        failed_pages=conversion.failed_pages,
        removed=MappingProxyType(dict(conversion.removed)),
        edited=MappingProxyType(dict(conversion.edited)),
        secret_blocks=conversion.secret_blocks,
        # Headings too: a chunk repeats them, and the Markdown may write
        # them differently.
        holds_private_key=holds_private_key(
            conversion.markdown,
            *(text for chunk in conversion.chunks for text in (chunk.text, *chunk.heading_path)),
        ),
        tokens=count_tokens(conversion.markdown),
        sugo_version=conversion.sugo_version,
        config_hash=conversion.config_hash,
        receipt=None
        if conversion.receipt is None
        else MappingProxyType(conversion.receipt.model_dump(mode="json")),
    )


def _settings() -> "Settings":
    """The settings the CLI would use here (ADR-051); warnings go to the log.

    The warnings name configuration files, whose paths show the user's
    folders: only their number is logged by default (principle 11), the
    text at DEBUG, and ``sugo doctor`` shows them in full.
    """
    from sugo.config.settings import load

    loaded = load()
    if loaded.warnings:
        _log.warning("%d settings warnings; run: sugo doctor", len(loaded.warnings))
    for warning in loaded.warnings:
        _log.debug("settings warning: %s", warning)
    return loaded.settings


@contextmanager
def _page_cache(mode: CacheMode) -> Iterator["PageCache | None"]:
    """The user's page cache for "user"; None, a temporary one per call, otherwise."""
    if mode == "ephemeral":
        yield None
        return
    from sugo.storage.page_cache import CacheUnavailableError, PageCache
    from sugo.storage.paths import StorageDirError

    try:
        page_cache = PageCache.default()
    except (CacheUnavailableError, StorageDirError, OSError):
        _log.warning("the page cache is unavailable; using a temporary one")
        yield None
        return
    with page_cache:
        yield page_cache


def _as_sugo_error(error: Exception) -> SugoError | None:
    """The public error for an exception Sugo raises on purpose, else None."""
    from sugo.ports.errors import from_exception

    failure = from_exception(error)
    if failure is None:
        return None
    return SugoError(failure.code, failure.message, failure.hint, failure.details)
