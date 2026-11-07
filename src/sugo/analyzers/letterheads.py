"""Find letterheads repeated on scanned pages, where OCR makes every copy different (ADR-064).

A scanned letterhead is the same picture on every page, but the OCR reads
its logo captions with different errors on each page and the layout groups
them into different blocks. Exact matching (ADR-044) never sees a repeat.

So, for pages read with OCR only, each text block in the top band
that is set clearly smaller than the page's body text (logo captions are
small print; body text that repeats in part must never be removed as a
whole) is cut into character trigrams, and the analyzer asks how much of a block is
found in the same band of nearby pages. A block whose trigrams are mostly
there on enough pages (ADR-044's repetition rules) is a letterhead copy.
Comparing with the whole band, not with single blocks, makes the grouping
of the captions irrelevant.

Trigrams are hashed with a key derived from the document into bit positions
of a fixed-size bitset: statistics never hold document text (principle 11),
memory does not grow with the length of a block, and the same document
always gives the same result (principle 6). Only the decisions, as page and
block ids, leave the analyzer.

The first copy always stays: a similar match is weaker evidence than an
exact one, and nothing a letterhead says is lost.
"""

import hashlib
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass

from sugo.core.constants import (
    LETTERHEAD_MAX_SIZE_RATIO,
    LETTERHEAD_MIN_CONTAINMENT,
    LETTERHEAD_MIN_TRIGRAMS,
    LETTERHEAD_SKETCH_BITS,
    LETTERHEAD_WINDOW_PAGES,
    MAX_EDGE_BLOCKS_PER_BAND,
    MAX_EDGE_TEXT_CHARS,
    OCR_EDGE_BAND,
    REPEAT_MIN_DENSITY,
    REPEAT_MIN_PAGES,
)
from sugo.core.models import Block, BlockType, Page, PageOrigin

_TOP = "top"
_TYPES = frozenset({BlockType.PARAGRAPH, BlockType.LIST_ITEM, BlockType.HEADER, BlockType.FOOTER})


@dataclass(frozen=True)
class Letterhead:
    """A block found again, with OCR differences, in the same band of other pages."""

    pages: int
    first_page: int


@dataclass(frozen=True)
class _Candidate:
    page: int
    band: str
    block_id: str
    bits: int


class LetterheadCollector:
    """Collects the edge bands of OCR pages, then finds the letterhead copies among them."""

    def __init__(self, key: bytes) -> None:
        # BLAKE2b keys are at most 64 bytes: any key is first reduced to 32.
        self._key = hashlib.blake2b(key, digest_size=32).digest()
        self._bands: dict[tuple[int, str], int] = {}
        self._candidates: list[_Candidate] = []

    def observe(self, page: Page) -> None:
        """Record the edge bands of one page; pages not read with OCR are skipped."""
        if page.origin is not PageOrigin.OCR:
            return
        typical = _typical_size(page)
        for band, blocks in _edge_blocks(page).items():
            union = 0
            for block in blocks:
                bits, count = self._sketch(block.text)
                union |= bits
                small = (
                    typical is not None
                    and block.style is not None
                    and block.style.font_size is not None
                    and block.style.font_size <= LETTERHEAD_MAX_SIZE_RATIO * typical
                )
                if small and count >= LETTERHEAD_MIN_TRIGRAMS:
                    self._candidates.append(_Candidate(page.index, band, block.id, bits))
            if union:
                self._bands[(page.index, band)] = union

    def finalize(self) -> dict[tuple[int, str], Letterhead]:
        """Return the letterhead copies to remove, by (page index, block id); first copies stay."""
        found: dict[tuple[int, str], Letterhead] = {}
        for candidate in sorted(self._candidates, key=lambda c: (c.page, c.band, c.block_id)):
            pages = {candidate.page}
            size = candidate.bits.bit_count()
            for other in range(
                candidate.page - LETTERHEAD_WINDOW_PAGES,
                candidate.page + LETTERHEAD_WINDOW_PAGES + 1,
            ):
                band = self._bands.get((other, candidate.band))
                if other == candidate.page or band is None:
                    continue
                if (candidate.bits & band).bit_count() >= LETTERHEAD_MIN_CONTAINMENT * size:
                    pages.add(other)
            first = min(pages)
            if _repeats(pages) and candidate.page != first:
                found[(candidate.page, candidate.block_id)] = Letterhead(len(pages), first)
        return found

    def _sketch(self, text: str) -> tuple[int, int]:
        """The keyed trigram bitset of a text, and how many distinct trigrams it has."""
        normalised = "".join(
            "0" if char.isdigit() else char
            for char in " ".join(unicodedata.normalize("NFKC", text).casefold().split())
        )
        trigrams = {normalised[i : i + 3] for i in range(len(normalised) - 2)}
        bits = 0
        for trigram in trigrams:
            digest = hashlib.blake2b(trigram.encode(), key=self._key, digest_size=4).digest()
            bits |= 1 << (int.from_bytes(digest) % LETTERHEAD_SKETCH_BITS)
        return bits, len(trigrams)


def _edge_blocks(page: Page) -> Mapping[str, list[Block]]:
    """Unflagged text blocks wholly inside the top OCR band, nearest the edge first.

    Only the top: letterheads are printed there, while the bottom of a page
    holds footnotes and signatures, small print that differs by a word or
    two from page to page and must not be matched by similarity (measured
    2026-11-07, benchmarks/letterheads.py). The bottom keeps ADR-044's exact
    matching.
    """
    top: list[tuple[float, str, Block]] = []
    for block in page.blocks:
        if (
            block.type not in _TYPES
            or block.bbox is None
            or block.removed
            or block.flags
            or not block.text.strip()
            or len(block.text) > MAX_EDGE_TEXT_CHARS
        ):
            continue
        if block.bbox.y1 <= OCR_EDGE_BAND:
            top.append((block.bbox.y0, block.id, block))
    return {_TOP: [block for *_, block in sorted(top)[:MAX_EDGE_BLOCKS_PER_BAND]]}


def _typical_size(page: Page) -> float | None:
    """The median font size of the page's text, weighted by characters."""
    sizes = sorted(
        (block.style.font_size, len(block.text.strip()))
        for block in page.blocks
        if block.style is not None
        and block.style.font_size is not None
        and not block.flags
        and block.text.strip()
    )
    total = sum(weight for _, weight in sizes)
    seen = 0
    for size, weight in sizes:
        seen += weight
        if 2 * seen >= total:
            return size
    return None


def _repeats(pages: set[int]) -> bool:
    if len(pages) < REPEAT_MIN_PAGES:
        return False
    return len(pages) >= REPEAT_MIN_DENSITY * (max(pages) - min(pages) + 1)
