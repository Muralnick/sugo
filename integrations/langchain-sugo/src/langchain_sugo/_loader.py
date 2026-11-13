"""``SugoLoader``: files in, LangChain documents out, one per Sugo chunk (ADR-068).

It uses only the public ``sugo`` API (ADR-067) and opens no connection.
"""

import logging
import os
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import sugo
from langchain_core.document_loaders import BaseLoader
from langchain_core.documents import Document

_log = logging.getLogger(__name__)

Mode = Literal["chunks", "document"]
OnError = Literal["raise", "skip"]
OnSecret = Literal["skip", "include", "raise"]
Cache = Literal["ephemeral", "user"]
_MODES = ("chunks", "document")
_ON_ERROR = ("raise", "skip")
_ON_SECRET = ("skip", "include", "raise")
# The MCP server's code for the same refusal (ADR-053).
_CONTENT_EXCLUDED = "CONTENT_EXCLUDED"
_HEADING_SEPARATOR = " > "

FilePath = str | os.PathLike[str]


@dataclass(frozen=True)
class Skipped:
    """A file the loader left out, and the code saying why."""

    path: str
    code: str


class SugoLoader(BaseLoader):
    """Load files through Sugo: compact Markdown, chunked by headings and pages.

    Args:
        file_path: One file or a list of files: PDF, DOCX, XLSX, PPTX, PNG,
            JPEG, WEBP or XML. Use LangChain's directory loaders for folders.
        mode: "chunks" (default) gives one document per Sugo chunk, with the
            chunk id as the document id; "document" gives one per file.
        max_tokens: Chunk size in tokens; defaults to Sugo's configured size.
        on_error: "raise" (default) stops at a file Sugo refuses; "skip"
            leaves it out and records it in ``skipped``.
        on_secret: What to do with a file Sugo flags as holding credentials:
            "skip" (default) leaves it out and records it in ``skipped``,
            "include" loads it as converted (credential blocks Sugo finds in
            XML are removed; a private key written in the text stays),
            "raise" stops with ``sugo.SugoError`` code CONTENT_EXCLUDED.
        cache: "ephemeral" (default) leaves no document text on disk;
            "user" uses Sugo's persistent page cache, faster on reloads.
    """

    def __init__(
        self,
        file_path: FilePath | Sequence[FilePath],
        *,
        mode: Mode = "chunks",
        max_tokens: int | None = None,
        on_error: OnError = "raise",
        on_secret: OnSecret = "skip",
        cache: Cache = "ephemeral",
    ) -> None:
        if mode not in _MODES:
            raise ValueError(f"mode must be one of {_MODES}, not {mode!r}")
        if on_error not in _ON_ERROR:
            raise ValueError(f"on_error must be one of {_ON_ERROR}, not {on_error!r}")
        if on_secret not in _ON_SECRET:
            raise ValueError(f"on_secret must be one of {_ON_SECRET}, not {on_secret!r}")
        if max_tokens is not None and mode != "chunks":
            raise ValueError('max_tokens needs mode="chunks"')
        self.file_paths: tuple[FilePath, ...]
        if isinstance(file_path, str | os.PathLike):
            self.file_paths = (file_path,)
        else:
            self.file_paths = tuple(file_path)
        self.mode = mode
        self.max_tokens = max_tokens
        self.on_error = on_error
        self.on_secret = on_secret
        self.cache = cache
        # Files left out by the last load, with why; for the caller's own code.
        self.skipped: list[Skipped] = []

    def lazy_load(self) -> Iterator[Document]:
        """Convert each file in turn and yield its documents."""
        self.skipped = []
        for file_path in self.file_paths:
            result = self._convert(file_path)
            if result is None:
                continue
            if result.has_credentials and self.on_secret != "include":
                if self.on_secret == "raise":
                    raise sugo.SugoError(
                        _CONTENT_EXCLUDED,
                        "This file holds credentials; Sugo does not load it.",
                        'Pass on_secret="include" to load it anyway.',
                    )
                self._skip(file_path, _CONTENT_EXCLUDED)
                continue
            if self.mode == "document":
                yield _whole(result)
            else:
                yield from (_chunk(result, chunk) for chunk in result.chunks)

    def _convert(self, file_path: FilePath) -> sugo.Result | None:
        try:
            return sugo.convert(
                file_path,
                chunks=self.mode == "chunks",
                max_tokens=self.max_tokens,
                cache=self.cache,
            )
        except sugo.SugoError as error:
            if self.on_error == "raise":
                raise
            self._skip(file_path, error.code)
        except OSError:
            if self.on_error == "raise":
                raise
            self._skip(file_path, "FILE_UNREADABLE")
        return None

    def _skip(self, file_path: FilePath, code: str) -> None:
        # The log never names the file (Sugo principle 11); ``skipped`` does.
        _log.warning("a file was left out: %s", code)
        self.skipped.append(Skipped(path=Path(file_path).as_posix(), code=code))


def _base_metadata(result: sugo.Result) -> dict[str, str | int | bool]:
    return {
        "source": result.source or "",
        "document_id": result.document_id,
        "source_sha256": result.source_sha256,
        "sugo_version": result.sugo_version,
        "config_hash": result.config_hash,
        "partial": result.partial,
    }


def _whole(result: sugo.Result) -> Document:
    metadata = _base_metadata(result)
    metadata.update(page_start=1, page_end=result.pages, tokens=result.tokens)
    return Document(id=result.document_id, page_content=result.markdown, metadata=metadata)


def _chunk(result: sugo.Result, chunk: sugo.Chunk) -> Document:
    metadata = _base_metadata(result)
    metadata.update(
        chunk_id=chunk.id,
        page_start=min(chunk.pages, default=0),
        page_end=max(chunk.pages, default=0),
        heading_path=_HEADING_SEPARATOR.join(chunk.heading_path),
        tokens=chunk.tokens,
    )
    return Document(id=chunk.id, page_content=chunk.text, metadata=metadata)
