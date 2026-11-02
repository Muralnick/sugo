"""Character rules shared by the core's edit checks, the lexicon and the text cleaners.

A text cleaner proposes an edit and the core checks it (ADR-050). Both must
agree, character by character, on what a letter is, which characters are
invisible and what a line-break hyphen looks like; otherwise a cleaner keeps
proposing edits the core refuses. So every one of them is defined here, once.
"""

import re
import unicodedata

from sugo.core.constants import INVISIBLE_CHARS, LIGATURES, LINE_BREAK_HYPHENS

# Deletes the characters that never print.
INVISIBLE = {ord(char): None for char in INVISIBLE_CHARS}

# Hyphens that join a compound on one line: "well-known".
COMPOUND_HYPHENS = LINE_BREAK_HYPHENS.replace("\u00ad", "")

# A hyphen at the end of a line, with the line break and any spaces around
# it; extra soft hyphens before it are typesetting noise. It starts only at
# the beginning of a run of soft hyphens and never gives characters back, so
# a long run without a line break costs linear time, not quadratic.
HYPHEN_BREAK = r"(?<!\u00ad)(?:\u00ad++|\u00ad*+[" + COMPOUND_HYPHENS + r"])[ \t]*+\n[ \t]*"

# Apostrophes after which an elided word attaches to the next one.
APOSTROPHES = "'\u2019"


def is_letter(char: str) -> bool:
    """A letter, or a combining mark on one: "é" may be stored as "e" + U+0301."""
    return char.isalpha() or unicodedata.category(char).startswith("M")


def canonical(text: str) -> str:
    """The text as a reader sees it, spacing kept: invisible characters dropped,
    the seven typographic ligatures expanded, accents composed (NFC)."""
    # Expanded before composing: "ﬁ" followed by an accent composes as "fí".
    expanded = "".join(LIGATURES.get(char, char) for char in text.translate(INVISIBLE))
    return unicodedata.normalize("NFC", expanded)


def visible(text: str) -> str:
    """The characters a reader sees, ignoring spacing and equivalent forms.

    Two texts with the same ``visible`` differ only in whitespace, invisible
    characters, ligatures and Unicode composition.
    """
    return "".join(char for char in canonical(text) if not char.isspace())


def compound_key(word: str) -> str:
    """A word in the form the lexicon compares: composed, case-folded, plain hyphens."""
    folded = canonical(word).casefold()
    return re.sub(f"[{COMPOUND_HYPHENS}]", "-", folded)
