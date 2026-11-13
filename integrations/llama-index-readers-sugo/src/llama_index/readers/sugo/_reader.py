"""``SugoReader``: files in, LlamaIndex documents out, one per Sugo chunk (ADR-068).

It uses only the public ``sugo`` API (ADR-067) and opens no connection.
"""

import logging
import os
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from llama_index.core.readers.base import BaseReader
from llama_index.core.schema import Document

import sugo

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
# Ids, digests and counts help find and update a document, but mean nothing
# to an embedding model or an LLM: kept out of their text, they cost no tokens.
_HIDDEN_KEYS = (
    "document_id",
    "chunk_id",
    "source_sha256",
    "sugo_version",
    "config_hash",
    "tokens",
    "partial",
)

FilePath = str | os.PathLike[str]


@dataclass(frozen=True)
class Skipped:
    """A file the reader left out, and the code saying why."""

    path: str
    code: str


class SugoReader(BaseReader):
    """Read files through Sugo: compact Markdown, chunked by headings and pages.

    Use it directly, ``SugoReader().load_data("handbook.pdf")``, or as a
    ``file_extractor`` of ``SimpleDirectoryReader`` for the suffixes it reads.

    Args:
        mode: "chunks" (default) gives one document per Sugo chunk, with the
            chunk id as the document id; "document" gives one per file.
        max_tokens: Chunk size in tokens; defaults to Sugo's configured size.
        on_error: "raise" (default) stops at a file Sugo refuses; "skip"
            leaves it out and records it in ``skipped``.
        on_secret: What to do with a file Sugo flags as holding credentials:
            "skip" (default) leaves it out and records it in ``skipped``,
            "include" loads it (the credential blocks are already removed),
            "raise" stops with ``sugo.SugoError`` code CONTENT_EXCLUDED.
        cache: "ephemeral" (default) leaves no document text on disk;
            "user" uses Sugo's persistent page cache, faster on reloads.
    """

    def __init__(
        self,
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
        self.mode = mode
        self.max_tokens = max_tokens
        self.on_error = on_error
        self.on_secret = on_secret
        self.cache = cache
        # Files left out by the last load, with why; for the caller's own code.
        self.skipped: list[Skipped] = []

    def lazy_load_data(
        self,
        file: FilePath | Sequence[FilePath],
        extra_info: Mapping[str, Any] | None = None,
        fs: object | None = None,
    ) -> Iterator[Document]:
        """Convert each file in turn and yield its documents.

        Args:
            file: One file or a list of files: PDF, DOCX, XLSX, PPTX, PNG,
                JPEG, WEBP or XML.
            extra_info: Metadata added to every document, as
                ``SimpleDirectoryReader`` passes it; Sugo's own keys win.
            fs: Only the local file system: Sugo reads local files only.
        """
        if fs is not None:
            raise ValueError("Sugo reads local files only; fs is not supported")
        self.skipped = []
        files: tuple[FilePath, ...] = (
            (file,) if isinstance(file, str | os.PathLike) else tuple(file)
        )
        for file_path in files:
            result = self._convert(file_path)
            if result is None:
                continue
            if result.secret_blocks and self.on_secret != "include":
                if self.on_secret == "raise":
                    raise sugo.SugoError(
                        _CONTENT_EXCLUDED,
                        "This file holds credentials; Sugo does not load it.",
                        'Pass on_secret="include" to load it without the credential blocks.',
                    )
                self._skip(file_path, _CONTENT_EXCLUDED)
                continue
            extra = dict(extra_info or {})
            if self.mode == "document":
                yield _whole(result, extra)
            else:
                yield from (_chunk(result, chunk, extra) for chunk in result.chunks)

    def load_data(
        self,
        file: FilePath | Sequence[FilePath],
        extra_info: Mapping[str, Any] | None = None,
        fs: object | None = None,
    ) -> list[Document]:
        """Convert the files and return all their documents; see ``lazy_load_data``."""
        return list(self.lazy_load_data(file, extra_info=extra_info, fs=fs))

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


def _metadata(
    result: sugo.Result, extra: dict[str, Any], own: dict[str, str | int | bool]
) -> dict[str, Any]:
    metadata = dict(extra)
    metadata.update(
        source=result.source or "",
        document_id=result.document_id,
        source_sha256=result.source_sha256,
        sugo_version=result.sugo_version,
        config_hash=result.config_hash,
        partial=result.partial,
    )
    metadata.update(own)
    return metadata


def _document(doc_id: str, text: str, metadata: dict[str, Any]) -> Document:
    return Document(
        id_=doc_id,
        text=text,
        metadata=metadata,
        excluded_embed_metadata_keys=list(_HIDDEN_KEYS),
        excluded_llm_metadata_keys=list(_HIDDEN_KEYS),
    )


def _whole(result: sugo.Result, extra: dict[str, Any]) -> Document:
    own: dict[str, str | int | bool] = {
        "page_start": 1,
        "page_end": result.pages,
        "tokens": result.tokens,
    }
    return _document(result.document_id, result.markdown, _metadata(result, extra, own))


def _chunk(result: sugo.Result, chunk: sugo.Chunk, extra: dict[str, Any]) -> Document:
    own: dict[str, str | int | bool] = {
        "chunk_id": chunk.id,
        "page_start": min(chunk.pages, default=0),
        "page_end": max(chunk.pages, default=0),
        "heading_path": _HEADING_SEPARATOR.join(chunk.heading_path),
        "tokens": chunk.tokens,
    }
    return _document(chunk.id, chunk.text, _metadata(result, extra, own))
