"""Split cleaned pages into chunks along the document's sections (ADR-047).

Blocks are added in reading order, page after page, and grouped into chunks
of at most ``max_tokens`` o200k_base tokens:

- a heading closes the chunk before it, unless that chunk holds only
  headings that the new one does not close: "# Part I" followed by
  "## Chapter 1" and its text stay together;
- a heading always travels with the text after it, never alone: when the
  first block of a section does not fit beside its headings, that block is
  split so its first piece does;
- a block that does not fit closes the chunk and starts the next one;
- a table is never split, even past the limit (ARCHITECTURE §4): half a
  table cannot be read;
- a longer paragraph is split after sentence ends or line breaks, code after
  line breaks, then between words, and only as a last resort inside a word.
  Pieces keep the text exactly, spaces and line breaks included, except at
  their two ends. After the first piece of a list item, the rest reads as
  plain text, so one bullet never turns into several.

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

# Where a paragraph may be cut: after a sentence end and the spaces after
# it ("3.14" is not one), after CJK sentence punctuation (ideographic full
# stop, fullwidth ! and ?, written without a space), or after a line break.
# The match stays with the text before it.
_SENTENCE_BREAK = re.compile(r"[.!?;:]+\s+|[\u3002\uff01\uff1f]+\s*|\n+")
# Where a run of text may be cut between words: after its spaces.
_WORD_BREAK = re.compile(r"\s+")
# Below this many tokens from the limit, the open chunk is counted exactly.
_ESTIMATE_MARGIN = 16
# Headings may take at most this share of the limit before the text that
# follows them; beyond it they form a chunk of their own.
_HEADINGS_MAX_SHARE = 0.5


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
        # Levels of the headings in the open chunk, while it holds nothing else.
        self._open_levels: list[int] | None = []
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
            yield from self._add_heading(block, page_number, tokens)
            return
        headings_only = bool(self._open) and self._open_levels is not None
        if block.type is BlockType.TABLE:
            # Whole, with its section's headings if any, even past the limit.
            if self._open and not headings_only and not self._fits(block, tokens):
                yield from self._close()
            self._append(block, page_number, tokens)
            self._open_levels = None
            return
        if headings_only and self._fits(block, tokens):
            self._append(block, page_number, tokens)
            self._open_levels = None
            return
        if headings_only or tokens > self._max:
            yield from self._add_in_pieces(block, page_number, headings_only)
            return
        if self._open and not self._fits(block, tokens):
            yield from self._close()
        self._append(block, page_number, tokens)
        self._open_levels = None

    def _add_heading(self, block: Block, page_number: int, tokens: int) -> Iterator[Chunk]:
        level = block.heading_level or 1
        # A heading at the level of one already in the chunk, or above it,
        # ends that heading's (empty) section: it closes the chunk, so the
        # chunk's heading path always names every heading it contains.
        if self._open_levels is None or any(seen >= level for seen in self._open_levels):
            yield from self._close()
        levels = self._open_levels if self._open_levels is not None else []
        while self._headings and self._headings[-1][0] >= level:
            self._headings.pop()
        title = " ".join(block.text.split())
        if title:
            self._headings.append((level, title))
        self._append(block, page_number, tokens)
        levels.append(level)
        self._open_levels = levels

    def _add_in_pieces(
        self, block: Block, page_number: int, headings_only: bool
    ) -> Iterator[Chunk]:
        """Split a block too big for the room left, keeping a section's headings with it."""
        room = self._max
        if headings_only:
            headings = count_tokens(render(b for b, _ in self._open))
            if headings + 1 <= self._max * _HEADINGS_MAX_SHARE:
                room = self._max - headings - 1
            else:
                yield from self._close()
                headings_only = False
        elif self._open:
            yield from self._close()
        for index, piece in enumerate(_pieces(block, self._max, first_max=room)):
            if index == 0 and headings_only:
                self._open.append((piece, page_number))
            else:
                self._open = [(piece, page_number)]
            self._open_levels = None
            yield from self._close()

    def _fits(self, block: Block, tokens: int) -> bool:
        """Whether the block fits in the open chunk; exact near the limit."""
        estimate = self._estimate + 1 + tokens
        if estimate <= self._max - _ESTIMATE_MARGIN:
            return True
        return count_tokens(render([*(b for b, _ in self._open), block])) <= self._max

    def _append(self, block: Block, page_number: int, tokens: int) -> None:
        # Blocks are joined by a line break, one token, and o200k_base never
        # merges tokens across a line break, so the sum is a close estimate.
        self._estimate = tokens if not self._open else self._estimate + 1 + tokens
        self._open.append((block, page_number))

    def _close(self) -> Iterator[Chunk]:
        blocks, self._open, self._open_levels = self._open, [], []
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


def _pieces(block: Block, max_tokens: int, *, first_max: int) -> Iterator[Block]:
    """Split one long block into blocks that each render within the limit."""
    code = block.type is BlockType.CODE
    texts = _split(block.text, block, max_tokens, first_max=first_max, lines_only=code)
    for index, text in enumerate(texts):
        # The rest of a list item is plain text: a second bullet would be a
        # second item. Chat messages keep their speaker on every piece.
        continued = index > 0 and block.type is BlockType.LIST_ITEM
        yield _with_text(block, text, index, as_paragraph=continued)


def _split(
    text: str, block: Block, max_tokens: int, *, first_max: int, lines_only: bool
) -> list[str]:
    pieces: list[str] = []
    current = ""
    # Sum of each unit rendered alone: never below the real count, since a
    # unit alone pays its own prefix and escapes; counted exactly near the limit.
    estimate = 0
    for unit in _units(text, lines_only):
        limit = first_max if not pieces else max_tokens
        current += unit
        estimate += _cost(unit, block, len(pieces))
        if estimate <= limit - _ESTIMATE_MARGIN:
            continue
        estimate = _cost(current, block, len(pieces))
        if estimate <= limit:
            continue
        previous = current[: len(current) - len(unit)]
        if previous.strip():
            pieces.append(previous)
            current = unit
            limit = max_tokens
            estimate = _cost(current, block, len(pieces))
        while estimate > limit:
            # One unit alone is too long: cut it until the head fits.
            head, current = _cut(current, limit, block, len(pieces))
            pieces.append(head)
            limit = max_tokens
            estimate = _cost(current, block, len(pieces))
    if current.strip():
        pieces.append(current)
    edges = "\n" if lines_only else None
    return [piece.strip(edges) for piece in pieces if piece.strip()]


def _units(text: str, lines_only: bool) -> Iterator[str]:
    """Consecutive slices of ``text`` ending at a break; they join back to it exactly."""
    if lines_only:
        yield from text.splitlines(keepends=True)
        return
    start = 0
    for match in _SENTENCE_BREAK.finditer(text):
        if match.end() > start:
            yield text[start : match.end()]
            start = match.end()
    if start < len(text):
        yield text[start:]


def _cut(text: str, max_tokens: int, block: Block, index: int) -> tuple[str, str]:
    """Split ``text`` into a head within the limit and the rest; the head is never empty."""
    breaks = [match.end() for match in _WORD_BREAK.finditer(text) if match.end() < len(text)]
    # The last word break whose head fits, found by bisection: a longer head
    # never costs fewer tokens.
    low, high = 0, len(breaks)
    while low < high:
        middle = (low + high) // 2
        if _cost(text[: breaks[middle]], block, index) <= max_tokens:
            low = middle + 1
        else:
            high = middle
    if low:
        cut = breaks[low - 1]
        return text[:cut], text[cut:]
    # No word fits whole (a URL, an encoded blob): cut inside it, by halving.
    cut = len(text)
    while cut > 1 and _cost(text[:cut], block, index) > max_tokens:
        cut //= 2
    return text[:cut], text[cut:]


def _cost(text: str, block: Block, index: int) -> int:
    continued = index > 0 and block.type is BlockType.LIST_ITEM
    return count_tokens(render([_with_text(block, text, index, as_paragraph=continued)]))


def _with_text(block: Block, text: str, index: int, *, as_paragraph: bool = False) -> Block:
    # Only blocks with text are split: an illegible block has none.
    fields = {**block.model_dump(), "id": f"{block.id}#{index}", "text": text}
    if as_paragraph:
        fields["type"] = BlockType.PARAGRAPH
    return Block.model_validate(fields)


def _hex(*parts: str | int) -> str:
    encoded = json.dumps(parts, ensure_ascii=False).encode()
    return hashlib.sha256(encoded).hexdigest()[:OUTPUT_ID_HEX_DIGITS]
