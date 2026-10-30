"""Normalise text that costs tokens without saying anything (ADR-050).

PDFs and OCR leave text that reads the same but tokenizes worse: ligatures
("ﬁ"), no-break and fixed-width spaces, zero-width characters, soft hyphens,
runs of spaces, trailing spaces, accents stored as two characters, words cut
by a hyphen at the end of a line, and in Italian and French a stray space
after an elision ("dell' albero"). This cleaner proposes one edit per such
spot; the core checks that each edit is of the kind it claims and applies it,
keeping the original on the block (principle 3).

Every rule keeps the letters, digits and signs a reader sees, with one
exception the core checks separately: a line-break hyphen inside a word.
"infor-" + "mation" becomes "information" only if the document writes
"information" elsewhere; "well-" + "known" becomes "well-known" if it writes
that; otherwise the hyphen stays (ADR-025: when in doubt, leave it). A soft
hyphen is always a word break, so it always joins.

Code, tables and formulas are left alone: their spacing can matter.
"""

import re
import unicodedata
from typing import ClassVar

from sugo.analyzers.lexicon import Lexicon
from sugo.core.constants import INVISIBLE_CHARS, LIGATURES, MAX_EDITS_PER_BLOCK, SPECIAL_SPACES
from sugo.core.decisions import EditDecision, within_limits
from sugo.core.models import BlockType, EditKind, Page
from sugo.core.text import APOSTROPHES, HYPHEN_BREAK, is_letter
from sugo.languages.packs import elisions

# Block types whose text is prose.
TEXT_TYPES = frozenset(
    {
        BlockType.HEADING,
        BlockType.PARAGRAPH,
        BlockType.LIST_ITEM,
        BlockType.CHAT_MESSAGE,
        BlockType.CAPTION,
        BlockType.FOOTNOTE,
    }
)

REASON_HYPHEN = "word split by a hyphen at the end of a line"
REASON_COMPOUND = "hyphenated word split at the end of a line"
REASON_SPACES = "spacing normalised"
REASON_INVISIBLE = "invisible character"
REASON_LIGATURE = "typographic ligature"
REASON_COMPOSED = "accented letter stored as two characters"
REASON_ELISION = "space after an elision"

_LETTER = r"[^\W\d_]"
_SPACE = f"[ {SPECIAL_SPACES}]"
# One pass over the text; alternatives never overlap, earlier ones win.
_RULES = re.compile(
    "|".join(
        (
            f"(?P<hyphen>{HYPHEN_BREAK})",
            rf"(?P<elision>(?<=[{APOSTROPHES}]){_SPACE}+(?={_LETTER}))",
            rf"(?P<trailing>(?<=\S){_SPACE}+(?=\n|\Z))",
            rf"(?P<spaces>(?<=\S)(?:{_SPACE}{{2,}}|[{SPECIAL_SPACES}]))",
            f"(?P<invisible>[{INVISIBLE_CHARS}])",
            f"(?P<ligature>[{''.join(LIGATURES)}])",
            r"(?P<composed>.[\u0300-\u036f]+)",
        )
    )
)
# Longer "words" are not words; capping the scan keeps it linear on hostile text.
_MAX_WORD = 64


class TextNormalizationCleaner:
    """Proposes normalisation edits for the prose of a page."""

    name: ClassVar[str] = "text_normalization"

    def __init__(self, languages: tuple[str, ...] = ("en",)) -> None:
        """
        Raises:
            ValueError: If a language has no pack.
        """
        self._elisions = elisions(languages)

    def propose(self, page: Page, stats: Lexicon) -> list[EditDecision]:
        """Return one edit per spot to normalise in the page's prose."""
        return within_limits(
            self._block_edits(block.id, block.text, stats)
            for block in page.blocks
            if not block.removed and block.type in TEXT_TYPES
        )

    def _block_edits(self, block_id: str, text: str, stats: Lexicon) -> list[EditDecision]:
        decisions: list[EditDecision] = []
        for match in _RULES.finditer(text):
            edit = self._edit(text, match, stats)
            if edit is not None:
                replacement, kind, reason = edit
                decisions.append(
                    EditDecision(
                        block_id=block_id,
                        start=match.start(),
                        end=match.end(),
                        replacement=replacement,
                        kind=kind,
                        reason=reason,
                    )
                )
                if len(decisions) > MAX_EDITS_PER_BLOCK:
                    # Left as it is anyway (within_limits): stop early.
                    break
        return decisions

    def _edit(
        self, text: str, match: re.Match[str], lexicon: Lexicon
    ) -> tuple[str, EditKind, str] | None:
        rule, found = match.lastgroup, match.group()
        if rule == "hyphen":
            return _hyphen(text, match, lexicon)
        if rule == "elision":
            apostrophe = match.start() - 1
            before = _word_before(text, apostrophe)
            if before is None or before.casefold() not in self._elisions:
                return None
            # "'all' keyword" and "rock 'n' roll" close a quote: no elision.
            opening = apostrophe - len(before) - 1
            if opening >= 0 and text[opening] in APOSTROPHES:
                return None
            return "", EditKind.NORMALIZE, REASON_ELISION
        if rule == "trailing":
            return "", EditKind.NORMALIZE, REASON_SPACES
        if rule == "spaces":
            return " ", EditKind.NORMALIZE, REASON_SPACES
        if rule == "invisible":
            return "", EditKind.NORMALIZE, REASON_INVISIBLE
        if rule == "ligature":
            return LIGATURES[found], EditKind.NORMALIZE, REASON_LIGATURE
        composed = unicodedata.normalize("NFC", found)
        return None if composed == found else (composed, EditKind.NORMALIZE, REASON_COMPOSED)


def _hyphen(text: str, match: re.Match[str], lexicon: Lexicon) -> tuple[str, EditKind, str] | None:
    """Join a word split at a line end, keep a compound's hyphen, or leave it."""
    head = _word_before(text, match.start())
    tail = _word_after(text, match.end())
    if head is None or tail is None:
        # Not inside a word: "2024-\n2025", "x²-\n", a dash at a line end.
        return None
    # The last hyphen before the line break; soft hyphens may come before it.
    hyphen = match.group().rstrip(" \t\n")[-1]
    if hyphen == "\u00ad":
        # A soft hyphen marks where a word may break: always one word.
        return "", EditKind.HYPHEN_JOIN, REASON_HYPHEN
    if head + tail in lexicon:
        return "", EditKind.HYPHEN_JOIN, REASON_HYPHEN
    if f"{head}-{tail}" in lexicon:
        return hyphen, EditKind.NORMALIZE, REASON_COMPOUND
    return None


def _word_before(text: str, end: int) -> str | None:
    """The whole word ending at ``end``, or None if there is none or it is too long."""
    start = end
    while start > 0 and end - start <= _MAX_WORD and is_letter(text[start - 1]):
        start -= 1
    if start == end or end - start > _MAX_WORD:
        return None
    return text[start:end]


def _word_after(text: str, start: int) -> str | None:
    """The whole word starting at ``start``, or None if there is none or it is too long."""
    end = start
    while end < len(text) and end - start <= _MAX_WORD and is_letter(text[end]):
        end += 1
    if end == start or end - start > _MAX_WORD:
        return None
    return text[start:end]
