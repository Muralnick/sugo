"""Split cleaned pages into chunks along the document's sections (ADR-047).

Blocks are added in reading order, page after page, and grouped into chunks
of at most ``max_tokens`` o200k_base tokens:

- a heading closes the chunk before it, unless that chunk holds only
  headings: "# Part I" followed by "## Chapter 1" and its text stay together;
- a block that does not fit closes the chunk and starts the next one;
- a table is never split, even past the limit (ARCHITECTURE §4): half a
  table cannot be read;
- a longer paragraph or code block is split at sentence or line breaks, then
  between words, and only as a last resort inside a word.

Every chunk carries the headings above it and the pages it comes from, so
it can be traced back to its source (principle 5). Removed blocks are left
out, exactly as in the Markdown output; nothing else is dropped.
"""

import hashlib
import json
import re
from collections import Counter
from collections.abc import Iterator

from sugo.core.chunks import Chunk
from sugo.core.constants import CHUNK_MAX_TOKENS, CHUNK_MIN_TOKENS, OUTPUT_ID_HEX_DIGITS
from sugo.core.models import Block, BlockType, Page
from sugo.metrics.tokenizer import count_tokens
from sugo.serializers.markdown import render

# Sentence ends in Latin and CJK scripts (ideographic full stop, fullwidth
# exclamation and question marks), keeping the punctuation with the sentence.
_SENTENCE_END = re.compile(r"(?<=[.!?;:\u3002\uff01\uff1f])\s+|(?<=[\u3002\uff01\uff1f])")
# Below this many tokens from the limit, the open chunk is counted exactly.
_ESTIMATE_MARGIN = 16
_SPACE = re.compile(r"(?<=\s)(?=\S)")


def document_id(source: str | None, source_sha256: str) -> str:
    """The document's id: from its name when it has one, so editions share it."""
    basis = f"source:{source}" if source is not None else f"sha256:{source_sha256}"
    return "d_" + _hex(basis)


class SectionChunker:
    """Turns the cleaned pages of one document into chunks, streaming."""

    def __init__(
        self,
        *,
        source: str | None,
        source_sha256: str,
        sugo_version: str,
        config_hash: str,
        max_tokens: int = CHUNK_MAX_TOKENS,
    ) -> None:
        if max_tokens < CHUNK_MIN_TOKENS:
            raise ValueError(f"max_tokens must be at least {CHUNK_MIN_TOKENS}")
        self._max = max_tokens
        self._source = source
        self._source_sha256 = source_sha256
        self._sugo_version = sugo_version
        self._config_hash = config_hash
        self._document_id = document_id(source, source_sha256)
        # Blocks of the open chunk, each with its page number (from 1).
        self._open: list[tuple[Block, int]] = []
        # Tokens of the open chunk, estimated from its blocks (see _append).
        self._estimate = 0
        self._only_headings = True
        self._headings: list[tuple[int, str]] = []
        # Occurrences of each text so far: repeated text gets distinct ids.
        self._seen: Counter[str] = Counter()

    def add(self, page: Page) -> Iterator[Chunk]:
        """Add the next page; yield the chunks it completes."""
        for block in page.blocks:
            if block.removed:
                continue
            yield from self._add_block(block, page.index + 1)

    def finish(self) -> Iterator[Chunk]:
        """Yield the last chunk, once every page has been added."""
        yield from self._close()

    def _add_block(self, block: Block, page_number: int) -> Iterator[Chunk]:
        tokens = count_tokens(render([block]))
        if block.type is BlockType.HEADING:
            if not self._only_headings:
                yield from self._close()
            self._push_heading(block)
            self._append(block, page_number, tokens)
            return
        if tokens > self._max and block.type is not BlockType.TABLE:
            yield from self._close()
            for piece in _pieces(block, self._max):
                self._open = [(piece, page_number)]
                self._only_headings = False
                yield from self._close()
            return
        self._append(block, page_number, tokens)
        self._only_headings = False
        if self._estimate > self._max - _ESTIMATE_MARGIN and len(self._open) > 1:
            # Near the limit the estimate is replaced by an exact count.
            self._estimate = count_tokens(render(b for b, _ in self._open))
            if self._estimate > self._max:
                self._open.pop()
                yield from self._close()
                self._append(block, page_number, tokens)
                self._only_headings = False

    def _append(self, block: Block, page_number: int, tokens: int) -> None:
        # Blocks are joined by a line break, one token, and o200k_base never
        # merges tokens across a line break, so the sum is a close estimate.
        self._estimate = tokens if not self._open else self._estimate + 1 + tokens
        self._open.append((block, page_number))

    def _push_heading(self, block: Block) -> None:
        level = block.heading_level or 1
        while self._headings and self._headings[-1][0] >= level:
            self._headings.pop()
        title = " ".join(block.text.split())
        if title:
            self._headings.append((level, title))

    def _close(self) -> Iterator[Chunk]:
        blocks, self._open, self._only_headings = self._open, [], True
        self._estimate = 0
        text = render(block for block, _ in blocks)
        if not text:
            return
        occurrence = self._seen[text]
        self._seen[text] += 1
        yield Chunk(
            id="c_" + _hex(self._document_id, text, occurrence),
            document_id=self._document_id,
            text=text,
            tokens=count_tokens(text),
            heading_path=tuple(title for _, title in self._headings),
            pages=tuple(sorted({page for _, page in blocks})),
            source=self._source,
            source_sha256=self._source_sha256,
            sugo_version=self._sugo_version,
            config_hash=self._config_hash,
        )


def _pieces(block: Block, max_tokens: int) -> Iterator[Block]:
    """Split one long block into blocks that each render within the limit."""
    lines_first = block.type is BlockType.CODE
    for index, text in enumerate(_split(block.text, max_tokens, block, lines_first)):
        yield _with_text(block, text, index)


def _split(text: str, max_tokens: int, block: Block, lines_first: bool) -> list[str]:
    pieces: list[str] = []
    current = ""
    # Sum of each unit rendered alone: never below the real count, since a
    # unit alone pays its own prefix and escapes; counted exactly near the limit.
    estimate = 0
    for unit in _units(text, lines_first):
        current += unit
        estimate += _cost(unit, block)
        if estimate <= max_tokens - _ESTIMATE_MARGIN:
            continue
        estimate = _cost(current, block)
        if estimate <= max_tokens:
            continue
        previous = current[: len(current) - len(unit)]
        if previous.strip():
            pieces.append(previous)
            current = unit
            estimate = _cost(current, block)
        while estimate > max_tokens:
            # One unit alone is too long: cut it in half until it fits.
            head, current = _halve(current, max_tokens, block)
            pieces.append(head)
            estimate = _cost(current, block)
    if current.strip():
        pieces.append(current)
    return [
        piece.strip("\n") if lines_first else piece.strip() for piece in pieces if piece.strip()
    ]


def _units(text: str, lines_first: bool) -> Iterator[str]:
    """Sentences (or lines, for code), then words, each keeping its trailing space."""
    if lines_first:
        yield from text.splitlines(keepends=True)
        return
    parts = [part for part in _SENTENCE_END.split(text) if part]
    for index, part in enumerate(parts):
        # The split removed the space after each sentence; it comes back.
        yield part + " " if index < len(parts) - 1 else part


def _halve(text: str, max_tokens: int, block: Block) -> tuple[str, str]:
    words = _SPACE.split(text)
    if len(words) > 1:
        cut = len(words) // 2
        while cut > 1 and _cost("".join(words[:cut]), block) > max_tokens:
            cut //= 2
        return "".join(words[:cut]), "".join(words[cut:])
    # A single "word" longer than the limit (an encoded blob, a URL).
    cut = len(text) // 2
    while cut > 1 and _cost(text[:cut], block) > max_tokens:
        cut //= 2
    return text[:cut], text[cut:]


def _cost(text: str, block: Block) -> int:
    return count_tokens(render([_with_text(block, text, 0)]))


def _with_text(block: Block, text: str, index: int) -> Block:
    # Only blocks with text are split: an illegible block has none.
    return Block.model_validate({**block.model_dump(), "id": f"{block.id}#{index}", "text": text})


def _hex(*parts: str | int) -> str:
    encoded = json.dumps(parts, ensure_ascii=False).encode()
    return hashlib.sha256(encoded).hexdigest()[:OUTPUT_ID_HEX_DIGITS]
