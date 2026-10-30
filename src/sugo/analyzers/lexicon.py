"""Remember which words a document uses, to resolve hyphens at line ends.

"infor-" at the end of a line and "mation" at the start of the next are one
word only if the document writes "information" somewhere else; "well-" and
"known" stay hyphenated if it writes "well-known". When the document says
neither, the hyphen stays (ADR-025: when in doubt, leave it). So the analyzer
observes every page once (pass 2, ADR-006) and the text normalisation cleaner
asks it about each line-break hyphen.

Words are kept as short hashes, never as text, like the edge statistics, and
their number is capped (``LEXICON_MAX_WORDS``) so a hostile document cannot
grow memory without bound.
"""

import hashlib
import re
from dataclasses import dataclass
from typing import ClassVar

from sugo.core.constants import LEXICON_MAX_WORDS
from sugo.core.models import BlockFlag, Page
from sugo.core.text import COMPOUND_HYPHENS, canonical, compound_key

# A word, or words joined by hyphens on the same line: "information", "well-known".
_WORD = re.compile(rf"[^\W\d_]+(?:[{COMPOUND_HYPHENS}][^\W\d_]+)*")
_HYPHENS = re.compile(f"[{COMPOUND_HYPHENS}]")


def _key(word: str) -> bytes:
    return hashlib.blake2b(compound_key(word).encode(), digest_size=8).digest()


@dataclass(frozen=True)
class Lexicon:
    """The words of a document, read by the text normalisation cleaner."""

    _words: frozenset[bytes]

    def __contains__(self, word: object) -> bool:
        return isinstance(word, str) and _key(word) in self._words

    def digest(self) -> str:
        """A digest of the lexicon, the same whatever order pages were observed in.

        Hyphen joins depend on the whole document, so it is part of the cache
        key of cleaned pages (ADR-046).
        """
        return hashlib.sha256(b"".join(sorted(self._words))).hexdigest()


class LexiconAnalyzer:
    """Observes every page of a document once, in any order, then returns its lexicon."""

    name: ClassVar[str] = "lexicon"

    def __init__(self) -> None:
        self._seen: set[int] = set()
        self._words: set[bytes] = set()

    def observe(self, page: Page) -> None:
        """Record the words of one page's visible text.

        Raises:
            ValueError: If a page with the same index was already observed.
        """
        if page.index in self._seen:
            raise ValueError(f"page {page.index} observed twice")
        self._seen.add(page.index)
        for block in page.blocks:
            # Hidden text must not vouch for a word the reader never sees.
            if block.removed or BlockFlag.HIDDEN in block.flags:
                continue
            # Composed first, so "e" + U+0301 stays inside its word.
            for match in _WORD.finditer(canonical(block.text)):
                word = match.group()
                # A compound vouches for its parts too: "information-theoretic"
                # for "information".
                parts = _HYPHENS.split(word)
                for found in (word, *parts) if len(parts) > 1 else (word,):
                    if len(self._words) >= LEXICON_MAX_WORDS:
                        return
                    self._words.add(_key(found))

    def finalize(self) -> Lexicon:
        """Return the lexicon.

        Below ``LEXICON_MAX_WORDS`` the result does not depend on the order
        pages were observed in; past it, the words of the first pages win.
        """
        return Lexicon(frozenset(self._words))
