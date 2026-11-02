"""Find running headers, footers and page numbers repeated across a document.

A running header is text printed in the same band of many pages: a title, a
chapter name, "Confidential", "Page 3 of 10". Seen on one page it looks like
any other paragraph; only the whole document shows that it repeats. So the
analyzer observes every page once (pass 2, ADR-006) and keeps a few bytes per
edge block, never the text itself, and the cleaners then decide page by page
with the statistics it returns (ADR-044).

Two texts are the same running header when they match after normalisation,
with digit runs masked: "Page 3 of 10" and "Page 4 of 10" share the pattern
"page # of #". Masked numbers must then either stay the same on every page
("10") or follow the page index ("3", "4"); a heading that merely recurs
("Section 3", "Section 7") does neither, and stays.

Only text a reader can see counts. Removed and flagged blocks are ignored:
otherwise hidden copies of a clause on every page could make its one visible
copy look like a repeated footer, and get it removed (THREAT_MODEL C).
"""

import hashlib
import json
import re
import unicodedata
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import ClassVar

from sugo.core.constants import (
    MAX_EDGE_BLOCKS_PER_BAND,
    MAX_EDGE_TEXT_CHARS,
    PAGE_EDGE_BAND,
    PAGE_NUMBER_MAX_CHARS,
    PAGE_NUMBER_MAX_DIGITS,
    REPEAT_MIN_DENSITY,
    REPEAT_MIN_PAGES,
    SUBSTANTIVE_MIN_CHARS,
    SUBSTANTIVE_MIN_WORDS,
)
from sugo.core.models import Block, BlockType, Page

# Text blocks that can be running headers. Tables, code, chat messages and
# captions repeating at a page edge are content, never page furniture; so are
# headings: a chapter title or "Part II" at the top of a page must survive
# even when the running header repeats its words. Running headers are set
# smaller than headings, so the extractors type them as paragraphs.
_EDGE_TYPES = frozenset(
    {
        BlockType.PARAGRAPH,
        BlockType.LIST_ITEM,
        BlockType.HEADER,
        BlockType.FOOTER,
        BlockType.PAGE_NUMBER,
    }
)

_DIGITS = re.compile(r"\d+")
_WORD = re.compile(r"\w+")
# The whole text is one page number: "7", "- 7 -" (any dash), "[vii]",
# "Page 7 of 90", "p. 7", "Pagina 7 di 90", "Seite 7/90". Matched on short
# normalised text only, and without nested repetition, so it cannot
# backtrack badly.
_PAGE_NUMBER = re.compile(
    r"[-\u2013\u2014|\[(\s]*"
    r"(?:(?:page|pag|pg|p|pagina|página|pàgina|seite|s)\.?\s*)?"
    r"(?P<number>\d+|[ivxlcdm]+)"
    r"(?:\s*(?:/|of|di|de|von|sur)\s*\d+)?"
    r"[-\u2013\u2014|\])\s]*"
)
_ROMAN = re.compile(r"m{0,3}(?:cm|cd|d?c{0,3})(?:xc|xl|l?x{0,3})(?:ix|iv|v?i{0,3})")
_ROMAN_VALUES = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000}


class Band(StrEnum):
    """Edge of the page where a block sits."""

    TOP = "top"
    BOTTOM = "bottom"


class NumberSystem(StrEnum):
    """How a page number is written; front matter often uses roman numerals."""

    ARABIC = "arabic"
    ROMAN = "roman"


@dataclass(frozen=True)
class EdgeText:
    """What the analyzer and the cleaners read from one block at a page edge."""

    block_id: str
    band: Band
    # Digest of the normalised text with digit runs masked: the same for every
    # copy of a running header, and constant in size whatever the text.
    pattern: bytes
    # The masked digit runs, in order: short ones as integers, long ones as a
    # digest, so statistics never hold document text.
    numbers: tuple[int | bytes, ...]
    # Long enough to be a clause rather than boilerplate.
    substantive: bool
    # Set when the whole text is a page number.
    page_number: tuple[NumberSystem, int] | None


@dataclass(frozen=True)
class NumberRule:
    """What one masked number is on every copy of a repeated pattern."""

    # Set when the number follows the page: it is the page index plus this.
    offset: int | None = None
    # Otherwise the number itself, the same on every copy.
    constant: int | bytes | None = None


@dataclass(frozen=True)
class RepeatedEdge:
    """A text pattern found at the same page edge on many pages."""

    pages: int
    first_page: int
    # Long enough to be a clause rather than boilerplate: its first copy stays.
    substantive: bool
    # One per masked number, in order.
    numbers: tuple[NumberRule, ...]

    def matches(self, text: EdgeText, page_index: int) -> bool:
        """Whether this copy has the numbers every other copy has."""
        if len(self.numbers) != len(text.numbers):
            return False
        return all(
            found == (rule.constant if rule.offset is None else page_index + rule.offset)
            for rule, found in zip(self.numbers, text.numbers, strict=True)
        )


@dataclass(frozen=True)
class EdgeStats:
    """Document-wide edge statistics, read by the header, footer and page number cleaners."""

    repeated: Mapping[tuple[Band, bytes], RepeatedEdge]
    # (band, number system, page number minus page index) of page number
    # sequences, so "1" on the first page and "2" on the second match.
    page_numbers: frozenset[tuple[Band, NumberSystem, int]]

    def digest(self) -> str:
        """A digest of these statistics, the same whatever order pages were observed in.

        Cleaned pages depend on the whole document, so it is part of their
        cache key (ADR-046): if any page reads differently, every page is
        cleaned again.
        """
        canonical = repr((sorted(self.repeated.items()), sorted(self.page_numbers)))
        return hashlib.sha256(canonical.encode()).hexdigest()

    def repeated_edge(self, text: EdgeText, page_index: int) -> RepeatedEdge | None:
        """Return the running header or footer this text is a copy of, if any."""
        repeated = self.repeated.get((text.band, text.pattern))
        if repeated is None or not repeated.matches(text, page_index):
            return None
        return repeated

    def is_page_number(self, text: EdgeText, page_index: int) -> bool:
        """Whether this text is the page's number in a sequence running through the document."""
        if text.page_number is None:
            return False
        system, value = text.page_number
        return (text.band, system, value - page_index) in self.page_numbers


class EdgeAnalyzer:
    """Observes every page of a document once, in any order, then returns its edge statistics."""

    name: ClassVar[str] = "edges"

    def __init__(self) -> None:
        self._seen: set[int] = set()
        # (band, pattern) -> page index -> numbers of its first copy on that page.
        self._texts: defaultdict[tuple[Band, bytes], dict[int, tuple[int | bytes, ...]]] = (
            defaultdict(dict)
        )
        # Substantive or not is a property of the pattern, the same on every copy.
        self._substantive: dict[tuple[Band, bytes], bool] = {}
        self._numbers: defaultdict[tuple[Band, NumberSystem, int], set[int]] = defaultdict(set)

    def observe(self, page: Page) -> None:
        """Record the edge text of one page.

        Raises:
            ValueError: If a page with the same index was already observed.
        """
        if page.index in self._seen:
            raise ValueError(f"page {page.index} observed twice")
        self._seen.add(page.index)
        for text in edge_texts(page):
            if text.page_number is not None:
                system, value = text.page_number
                self._numbers[(text.band, system, value - page.index)].add(page.index)
            else:
                key = (text.band, text.pattern)
                self._texts[key].setdefault(page.index, text.numbers)
                self._substantive[key] = text.substantive

    def finalize(self) -> EdgeStats:
        """Return the statistics; the result does not depend on the order pages were observed."""
        repeated: dict[tuple[Band, bytes], RepeatedEdge] = {}
        for key, copies in self._texts.items():
            edge = _repeated_edge(copies, substantive=self._substantive[key])
            if edge is not None:
                repeated[key] = edge
        page_numbers = frozenset(key for key, pages in self._numbers.items() if _repeats(pages))
        return EdgeStats(repeated=MappingProxyType(repeated), page_numbers=page_numbers)


def edge_texts(page: Page) -> list[EdgeText]:
    """Return the text blocks inside the top and bottom bands of a page, nearest the edge first.

    Removed blocks are skipped, and so are flagged ones: hidden, illegible,
    uncertain or suspicious text must neither count as a repeat nor be
    removed as one.
    """
    top: list[tuple[float, str, Block]] = []
    bottom: list[tuple[float, str, Block]] = []
    for block in page.blocks:
        if block.removed or block.flags or block.type not in _EDGE_TYPES:
            continue
        # Longer text is a paragraph, never page furniture.
        if block.bbox is None or not block.text.strip() or len(block.text) > MAX_EDGE_TEXT_CHARS:
            continue
        if block.bbox.y1 <= PAGE_EDGE_BAND:
            top.append((block.bbox.y0, block.id, block))
        elif block.bbox.y0 >= 1.0 - PAGE_EDGE_BAND:
            bottom.append((-block.bbox.y1, block.id, block))
    return [
        _edge_text(block, band)
        for band, candidates in ((Band.TOP, top), (Band.BOTTOM, bottom))
        for _, _, block in sorted(candidates)[:MAX_EDGE_BLOCKS_PER_BAND]
    ]


def _edge_text(block: Block, band: Band) -> EdgeText:
    text = " ".join(unicodedata.normalize("NFKC", block.text).casefold().split())
    # The text between digit runs, encoded unambiguously: masking with a
    # character such as "#" would let "ref # 1" and "ref 1 1" share a
    # pattern with a different count of numbers.
    between = json.dumps(_DIGITS.split(text), ensure_ascii=False)
    return EdgeText(
        block_id=block.id,
        band=band,
        pattern=hashlib.blake2b(between.encode(), digest_size=16).digest(),
        numbers=tuple(_number(digits) for digits in _DIGITS.findall(text)),
        substantive=_substantive(text),
        page_number=_page_number(text),
    )


def _number(digits: str) -> int | bytes:
    value = _as_int(digits)
    return hashlib.blake2b(digits.encode(), digest_size=8).digest() if value is None else value


def _substantive(text: str) -> bool:
    # Chinese and Japanese are written without spaces, so each wide character
    # counts as a word; other scripts without spaces (Thai, Khmer) and text
    # spaced with blank-looking letters are caught by their length.
    words = sum(
        sum(unicodedata.east_asian_width(char) in "WF" for char in run) or 1
        for run in _WORD.findall(text)
    )
    visible = sum(not char.isspace() for char in text)
    return words >= SUBSTANTIVE_MIN_WORDS or visible >= SUBSTANTIVE_MIN_CHARS


def _page_number(text: str) -> tuple[NumberSystem, int] | None:
    if len(text) > PAGE_NUMBER_MAX_CHARS:
        return None
    match = _PAGE_NUMBER.fullmatch(text)
    if match is None:
        return None
    number = match["number"]
    if number[0].isdigit():
        value = _as_int(number)
        return None if value is None else (NumberSystem.ARABIC, value)
    if not _ROMAN.fullmatch(number):
        return None
    return NumberSystem.ROMAN, _roman_value(number)


def _roman_value(numeral: str) -> int:
    values = [_ROMAN_VALUES[char] for char in numeral]
    # A smaller numeral before a larger one is subtracted: "iv" is 4.
    return sum(
        -value if index + 1 < len(values) and value < values[index + 1] else value
        for index, value in enumerate(values)
    )


def _as_int(digits: str) -> int | None:
    # Long runs are never page numbers; skipping them also avoids converting
    # huge digit strings, which Python refuses beyond a few thousand digits.
    return int(digits) if len(digits) <= PAGE_NUMBER_MAX_DIGITS else None


def _repeats(pages: set[int] | Mapping[int, object]) -> bool:
    if len(pages) < REPEAT_MIN_PAGES:
        return False
    span = max(pages) - min(pages) + 1
    return len(pages) >= REPEAT_MIN_DENSITY * span


def _repeated_edge(
    copies: Mapping[int, tuple[int | bytes, ...]], *, substantive: bool
) -> RepeatedEdge | None:
    if not _repeats(copies):
        return None
    rules: list[NumberRule] = []
    # The pattern fixes the count of digit runs, so every copy has as many.
    for slot in zip(*copies.values(), strict=True):
        if len(set(slot)) == 1:
            rules.append(NumberRule(constant=slot[0]))
            continue
        # A substantive copy is removed only when it is identical to the one
        # kept: numbers that change with the page could carry content.
        if substantive:
            return None
        offsets = set()
        for value, page in zip(slot, copies, strict=True):
            if not isinstance(value, int):
                return None  # Too long to be a page-based number.
            offsets.add(value - page)
        if len(offsets) != 1:
            return None
        rules.append(NumberRule(offset=offsets.pop()))
    return RepeatedEdge(
        pages=len(copies),
        first_page=min(copies),
        substantive=substantive,
        numbers=tuple(rules),
    )
