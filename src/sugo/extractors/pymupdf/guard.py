"""Refuse PDFs that would reach MuPDF's Brotli decoder (CVE-2026-111497, ADR-043).

MuPDF below 1.28.6 has an out-of-bounds write in its bundled Brotli decoder,
reached by any stream or inline image compressed with ``/BrotliDecode``.
Brotli is a recent addition to PDF and almost never used, so such files are
refused until a PyMuPDF release ships the fix; then this module goes away.

Three layers, so MuPDF never decodes Brotli data:

1. ``raw_problem`` runs in Sugo on the file bytes, before MuPDF sees them. Stream
   dictionaries are never compressed (a stream cannot sit inside an object
   stream), so a filter naming Brotli is visible in the raw bytes, unless it
   is an indirect reference whose name hides in compressed data: those are
   refused too, as no real PDF writer produces them. This layer must be
   complete for object streams and cross-reference streams, which MuPDF
   decodes while opening the file, before the worker can check anything.
2. The worker reads every stream's ``/Filter`` and ``/F`` (MuPDF accepts the
   abbreviation) through MuPDF's object API, following references, before it
   decodes any stream itself.
3. The worker then runs ``scan`` on every decoded stream, where inline images
   name their own filter, and on each page's content streams joined together,
   as MuPDF joins them: an inline image may start in one and end in the next.
   Every stream, because a dictionary's ``/Subtype`` is written by the
   attacker: a page's content can claim to be an image and is still
   interpreted as content.

This module never imports MuPDF, so the first layer runs without it.

The scan reads names as MuPDF does: a name runs to the next delimiter, and
only then are its ``#xx`` escapes undone, so ``/Br#6ftliDecode`` is Brotli
while ``/A#28`` is the name ``A(``, not a name followed by a string. MuPDF
also accepts the abbreviation ``/Br``, which is short enough to occur by
chance in compressed data; it only counts as a filter name after a filter key
(``/Filter`` or ``/F``), alone or in an array. The full name is long enough to
count anywhere. Arrays and dictionaries are read token by token: comments,
strings (nested parentheses included) and whitespace cannot hide a ``]`` or a
name. The work is capped; a scan that reaches the cap is incomplete, and the
document is refused.
"""

import re
from dataclasses import dataclass

BROTLI_REFUSAL = "the PDF uses Brotli compression, refused until MuPDF fixes CVE-2026-111497"
UNCHECKED_REFUSAL = "the PDF's compression filters cannot be checked"

_BROTLI_NAMES = frozenset({b"Br", b"BrotliDecode"})
_NAME_ESCAPE = re.compile(rb"#([0-9A-Fa-f]{2})")
_DELIMITER = rb"\s\x00/\[\]<>(){}%"
_NAME_END = rb"(?=[" + _DELIMITER + rb"]|\Z)"


def _spelled(word: bytes) -> bytes:
    """A pattern for ``word`` with any of its letters written as a ``#xx`` escape."""
    letters = []
    for letter in word.decode():
        code = f"{ord(letter):02x}"
        letters.append(f"(?:{letter}|#{code[0]}[{code[1]}{code[1].upper()}])")
    return "".join(letters).encode()


# A filter key, or the full Brotli name, long enough to count anywhere.
_KEY = re.compile(
    b"/(?:"
    + _spelled(b"BrotliDecode")
    + b"|"
    + _spelled(b"F")
    + b"(?:"
    + _spelled(b"ilter")
    + b")?"
    + _NAME_END
    + b")"
)
# Possessive and atomic quantifiers throughout: no pattern can backtrack.
_SPACE = re.compile(rb"(?:[\s\x00]|%[^\r\n]*+)*+")
_NAME = re.compile(rb"/([^" + _DELIMITER + rb"]*+)")
# "5 0 R": MuPDF's lexer accepts a sign before each number.
_GAP = rb"(?:[\s\x00]|%[^\r\n]*+[\r\n])"
_REF = re.compile(rb"[+\-]?(\d++)" + _GAP + rb"++[+\-]?\d++" + _GAP + rb"*+R" + _NAME_END)
_INTEGER = re.compile(rb"[+\-]?\d+")
_TOKEN = re.compile(
    rb"[\s\x00]++|%[^\r\n]*+|<<|>>|<[^>]*+>?|[^" + _DELIMITER + rb"]++|[\[\](){}>/]"
)
_STRING_PART = re.compile(rb"[^()\\]++|\\.?|[()]", re.DOTALL)
_STREAM = re.compile(rb"stream(?:\r\n|[\r\n])")
# Bytes the scans of one input may read beyond each key, in total, beyond the
# input's own length.
_SCAN_BUDGET_SLACK = 64 * 1024


@dataclass(frozen=True)
class FilterScan:
    """What a scan found, and whether it finished.

    ``stream_references`` are objects given as a stream's filter by
    reference: after ``/Filter``, or after ``/F`` in a dictionary a stream
    follows. ``other_references`` come after ``/F`` elsewhere, where a file
    specification is the usual meaning, or in decoded data.
    """

    brotli: bool
    stream_references: frozenset[int]
    other_references: frozenset[int]
    complete: bool

    @property
    def references(self) -> frozenset[int]:
        return self.stream_references | self.other_references


def raw_problem(data: bytes) -> str | None:
    """Why the raw PDF bytes must be refused, or None if they may be parsed.

    A reference after ``/F`` outside a stream dictionary is allowed: it is how
    file specifications are written, and MuPDF never reads it as a filter.
    """
    found = scan(data)
    if found.brotli:
        return BROTLI_REFUSAL
    if found.stream_references:
        return "the PDF names a stream filter indirectly, which Sugo cannot check safely"
    if not found.complete:
        return UNCHECKED_REFUSAL
    return None


def scan(data: bytes) -> FilterScan:
    """Find every filter named in PDF bytes, raw or decoded."""
    budget = [len(data) * 4 + _SCAN_BUDGET_SLACK]
    brotli = False
    stream_references: set[int] = set()
    other_references: set[int] = set()
    position = 0
    while (key := _KEY.search(data, position)) is not None:
        position = key.end()
        name = _unescape(key[0])
        if name == b"/BrotliDecode":
            brotli = True
            continue
        found: set[int] = set()
        value = _SPACE.match(data, position).end()  # type: ignore[union-attr]  # matches empty
        end = value
        if (filter_name := _NAME.match(data, value)) is not None:
            brotli |= _unescape(filter_name[1]) in _BROTLI_NAMES
        elif (reference := _REF.match(data, value)) is not None:
            found.add(int(reference[1]))
            end = reference.end()
        elif data[value : value + 1] == b"[":
            names, found, end = _array(data, value + 1, budget)
            brotli |= not names.isdisjoint(_BROTLI_NAMES)
        if found:
            in_stream = name == b"/Filter" or _ends_in_stream(data, end, budget)
            (stream_references if in_stream else other_references).update(found)
        if budget[0] < 0:
            break
    return FilterScan(
        brotli, frozenset(stream_references), frozenset(other_references), budget[0] >= 0
    )


def _array(data: bytes, position: int, budget: list[int]) -> tuple[set[bytes], set[int], int]:
    """Names and references in the array starting at ``position``, nested arrays
    included, and where the array ends."""
    names: set[bytes] = set()
    references: set[int] = set()
    words: list[bytes] = []  # bare words since the last name or bracket, to spot "5 0 R"
    depth = 1
    start = position
    while depth and (token := _next_token(data, position, start, budget)) is not None:
        text = token[0]
        position = token.end()
        if text == b"(":
            position = _string_end(data, position)
        elif text == b"[":
            depth += 1
        elif text == b"]":
            depth -= 1
        elif text == b"/":
            name = _NAME.match(data, token.start())
            assert name is not None  # noqa: S101  (a "/" always starts a name)
            names.add(_unescape(name[1]))
            position = name.end()
            words.clear()
        elif text[0] in b" \t\r\n\f\x00%":
            continue
        elif text == b"R":
            match words[-2:]:
                case [number, generation] if _INTEGER.fullmatch(number) and _INTEGER.fullmatch(
                    generation
                ):
                    references.add(int(number))
            words.clear()
        else:
            words.append(text)
    budget[0] -= position - start
    return names, references, position


def _ends_in_stream(data: bytes, position: int, budget: list[int]) -> bool:
    """Whether the dictionary around ``position`` is followed by a stream.

    An unfinished dictionary counts as one: the scan cannot tell otherwise.
    """
    depth = 1
    start = position
    while depth and (token := _next_token(data, position, start, budget)) is not None:
        position = token.end()
        if token[0] == b"(":
            position = _string_end(data, position)
        elif token[0] == b"<<":
            depth += 1
        elif token[0] == b">>":
            depth -= 1
        elif token[0] == b"/":
            position = _NAME.match(data, token.start()).end()  # type: ignore[union-attr]
    budget[0] -= position - start
    if depth:
        return True
    after = _SPACE.match(data, position).end()  # type: ignore[union-attr]  # matches empty
    return _STREAM.match(data, after) is not None


def _next_token(
    data: bytes, position: int, start: int, budget: list[int]
) -> re.Match[bytes] | None:
    """The token at ``position``, or None at the end of the data or of the budget."""
    if position >= len(data) or budget[0] < position - start:
        return None
    return _TOKEN.match(data, position)


def _string_end(data: bytes, position: int) -> int:
    """Where the literal string opened just before ``position`` ends."""
    depth = 1
    while depth and (part := _STRING_PART.match(data, position)) is not None:
        position = part.end()
        if part[0] == b"(":
            depth += 1
        elif part[0] == b")":
            depth -= 1
    return position


def _unescape(name: bytes) -> bytes:
    return _NAME_ESCAPE.sub(lambda match: bytes.fromhex(match[1].decode()), name)
