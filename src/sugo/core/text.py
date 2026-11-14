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

# Full-width ASCII letters and digits, written as their ASCII form (ADR-069).
FULL_WIDTH_ALNUM = "\uff10-\uff19\uff21-\uff3a\uff41-\uff5a"
# Half-width Katakana and its middle dot, written full width, each with the
# half-width sound marks after it. A lone sound mark is not one: written full
# width it would combine with the character before it, a letter the reader
# never saw ("か" + a lone mark is not "が").
HALF_WIDTH_KATAKANA = "(?:[\uff65-\uff9d][\uff9e\uff9f]*)+"
# Only these two mappings, never full NFKC: it would turn a full-width comma
# into "," and "m²" into "m2". A half-width sound mark becomes a combining
# mark, which NFC composes with the Katakana before it: "ｶﾞ" -> "ガ".
_WIDTH_ALNUM = {
    code: code - 0xFEE0
    for first, last in ((0xFF10, 0xFF19), (0xFF21, 0xFF3A), (0xFF41, 0xFF5A))
    for code in range(first, last + 1)
}
_HALF_KATAKANA = re.compile(HALF_WIDTH_KATAKANA)

# Characters between which Japanese and Chinese put no space (ADR-069): Han
# ideographs, Kana, CJK punctuation and symbols, full-width forms. Full-width
# letters and digits count: they are only written inside CJK text, and a PDF
# can break a line inside a full-width number. Hangul is not here: Korean
# separates words with spaces.
# U+3000, the ideographic space, is whitespace, not a character to join.
CJK_CHARS = (
    "\u3001-\u303f"  # CJK symbols and punctuation
    "\u3040-\u30ff"  # Hiragana and Katakana, with the prolonged sound mark
    "\u3190-\u319f\u31c0-\u31ef"  # Kanbun, CJK strokes
    "\u31f0-\u31ff"  # Katakana phonetic extensions
    "\u3200-\u33ff"  # Enclosed CJK letters, CJK compatibility
    "\u3400-\u4dbf\u4e00-\u9fff"  # Han, extension A and unified
    "\uf900-\ufaff"  # Han compatibility ideographs
    "\ufe30-\ufe4f"  # CJK compatibility forms
    "\uff01-\uff64"  # Full-width forms
    "\uff65-\uff9f"  # Half-width Katakana
    "\uffe0-\uffee"  # Full-width signs
    "\U00020000-\U0003134f"  # Han, extensions B to H and compatibility supplement
)
_CJK = re.compile(f"[{CJK_CHARS}]")
# Half-width sound marks. A line that starts with one is never joined to the
# line before: joined to a half-width Katakana, it would compose with it into
# a letter the reader never saw.
HALF_WIDTH_SOUND_MARKS = "\uff9e\uff9f"


def is_cjk(char: str) -> bool:
    """A character that Japanese and Chinese write without spaces around it."""
    return _CJK.fullmatch(char) is not None


def joins_cjk_lines(before: str, after: str) -> bool:
    """Whether a line break between these two characters may go (ADR-069)."""
    return is_cjk(before) and is_cjk(after) and after not in HALF_WIDTH_SOUND_MARKS


def is_letter(char: str) -> bool:
    """A letter, or a combining mark on one: "é" may be stored as "e" + U+0301."""
    return char.isalpha() or unicodedata.category(char).startswith("M")


def canonical(text: str) -> str:
    """The text as a reader sees it, spacing kept: invisible characters dropped,
    the seven typographic ligatures expanded, full-width letters and digits and
    half-width Katakana in their usual width, accents composed (NFC)."""
    # Expanded before composing: "ﬁ" followed by an accent composes as "fí".
    # Width is mapped here too, so a reader sees a full-width "A" and
    # an ASCII "A" as the same letter (ADR-069).
    expanded = "".join(LIGATURES.get(char, char) for char in text.translate(INVISIBLE))
    expanded = _HALF_KATAKANA.sub(
        lambda run: unicodedata.normalize("NFKC", run.group()), expanded.translate(_WIDTH_ALNUM)
    )
    return unicodedata.normalize("NFC", expanded)


def visible(text: str) -> str:
    """The characters a reader sees, ignoring spacing and equivalent forms.

    Two texts with the same ``visible`` differ only in whitespace, invisible
    characters, ligatures, character width (the two mappings of ADR-069) and
    Unicode composition.
    """
    return "".join(char for char in canonical(text) if not char.isspace())


def compound_key(word: str) -> str:
    """A word in the form the lexicon compares: composed, case-folded, plain hyphens."""
    folded = canonical(word).casefold()
    return re.sub(f"[{COMPOUND_HYPHENS}]", "-", folded)
