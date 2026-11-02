"""Refuse PDFs that would reach MuPDF's Brotli decoder (CVE-2026-111497, ADR-043).

MuPDF below 1.28.6 has an out-of-bounds write in its bundled Brotli decoder,
reached by any stream or inline image compressed with ``/BrotliDecode``.
Brotli is a recent addition to PDF and almost never used, so such files are
refused until a PyMuPDF release ships the fix; then this module goes away.

Brotli is refused wherever its name appears, not only where a parser would
read it as a filter: matching MuPDF's parser exactly proved fragile (security
reviews of 2026-11-02 found one gap after another), while a whole name
``/Br`` or ``/BrotliDecode`` has no other use. Three layers:

1. ``raw_problem`` runs in Sugo on the file bytes, before MuPDF sees them: any
   Brotli name refuses the file. MuPDF decodes object streams and
   cross-reference streams while opening the file, before the worker can
   check anything, so a filter written as anything but a name or an array of
   names (a reference, whose name could hide in compressed data) is refused
   too: after ``/Filter`` anywhere, after ``/F`` in a stream's dictionary.
2. Before decoding any stream, the worker asks MuPDF for every object, as
   MuPDF itself parsed and prints it: any Brotli name refuses the file. This
   covers every filter given by reference, whatever its spelling.
3. The worker then decodes every stream. Every stream MuPDF may run as
   content (anything but an image, and whatever a page, a Type 3 glyph, a
   pattern, an appearance or a soft mask uses, whatever it claims to be) is
   refused for any Brotli name, and so is each page's content joined as
   MuPDF joins it. In an image's pixels the abbreviation occurs by chance, so
   there only a name given to a filter key counts (``scan``).

This module never imports MuPDF, so the first layer runs without it.

Names are read as MuPDF reads them, up to the next delimiter, and then their
``#xx`` escapes are undone: ``/Br#6ftliDecode`` is Brotli, while ``/A#28`` is
the name ``A(``. Arrays and dictionaries are read token by token: comments,
strings (nested parentheses included) and whitespace cannot hide a ``]``.
The work is capped; a scan that reaches the cap is incomplete, and the
document is refused.
"""

import re
from dataclasses import dataclass

from sugo.i18n import N_

# Marked, not translated: the worker sends it as data and the parent translates it.
# Filled with MAX_PDF_PAGES by the worker; the parent recognises the result.
PAGES_REFUSAL = N_("the PDF has more than {pages} pages")
BROTLI_REFUSAL = N_("the PDF uses Brotli compression, refused until MuPDF fixes CVE-2026-111497")
UNCHECKED_REFUSAL = N_("the PDF's compression filters cannot be checked")

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


# Brotli's names, in any spelling, as whole names.
_BROTLI = re.compile(
    b"/(?:" + _spelled(b"BrotliDecode") + b"|" + _spelled(b"Br") + b")" + _NAME_END
)
# A filter key.
_KEY = re.compile(b"/" + _spelled(b"F") + b"(?:" + _spelled(b"ilter") + b")?" + _NAME_END)
# Possessive and atomic quantifiers throughout: no pattern can backtrack.
_SPACE = re.compile(rb"(?:[\s\x00]|%[^\r\n]*+)*+")
_NAME = re.compile(rb"/([^" + _DELIMITER + rb"]*+)")
_TOKEN = re.compile(
    rb"[\s\x00]++|%[^\r\n]*+|<<|>>|<[^>]*+>?|[^" + _DELIMITER + rb"]++|[\[\](){}>/]"
)
_STRING_PART = re.compile(rb"[^()\\]++|\\.?|[()]", re.DOTALL)
_NUMBER_START = re.compile(rb"[+\-.\d]")
# MuPDF accepts the keyword before any whitespace or delimiter.
_STREAM = re.compile(rb"stream" + _NAME_END)
# Bytes the scans of one input may read beyond each key, in total, beyond the
# input's own length.
_SCAN_BUDGET_SLACK = 64 * 1024


@dataclass(frozen=True)
class FilterScan:
    """What a scan of filter keys found, and whether it finished.

    ``irregular`` is a stream filter written as anything but a name or an
    array of names: after ``/Filter`` anywhere, or after ``/F`` in a
    dictionary a stream follows (elsewhere ``/F`` is usually a file
    specification). Real PDF writers never produce one; it could be a
    reference whose name hides in compressed data.
    """

    brotli: bool
    irregular: bool
    complete: bool


def raw_problem(data: bytes) -> str | None:
    """Why the raw PDF bytes must be refused, or None if they may be parsed."""
    if names_brotli(data):
        return BROTLI_REFUSAL
    found = scan(data)
    if found.brotli:
        return BROTLI_REFUSAL
    if found.irregular:
        return N_("the PDF writes a stream filter in a form Sugo cannot check safely")
    if not found.complete:
        return UNCHECKED_REFUSAL
    return None


def names_brotli(data: bytes) -> bool:
    """Whether PDF bytes contain a name of the Brotli filter anywhere."""
    return _BROTLI.search(data) is not None


def scan(data: bytes) -> FilterScan:
    """Read every filter key's value in PDF bytes, raw or decoded.

    Used where Brotli names occur by chance (image pixels), so only a name
    given to a filter key counts.
    """
    budget = [len(data) * 4 + _SCAN_BUDGET_SLACK]
    brotli = irregular = False
    position = 0
    while (key := _KEY.search(data, position)) is not None:
        position = key.end()
        value = _SPACE.match(data, position).end()  # type: ignore[union-attr]  # matches empty
        regular = True
        if (filter_name := _NAME.match(data, value)) is not None:
            brotli |= _unescape(filter_name[1]) in _BROTLI_NAMES
        elif data[value : value + 1] == b"[":
            names, regular = _array(data, value + 1, budget)
            brotli |= not names.isdisjoint(_BROTLI_NAMES)
        elif _unescape(key[0]) == b"/Filter":
            regular = False
        else:
            # After "/F", only a reference, which starts with a number, could
            # name a filter; strings and dictionaries are file specifications.
            regular = _NUMBER_START.match(data, value) is None
        if not regular and not irregular:
            irregular = _unescape(key[0]) == b"/Filter" or _ends_in_stream(data, value, budget)
        if budget[0] < 0:
            break
    return FilterScan(brotli, irregular, budget[0] >= 0)


def _array(data: bytes, position: int, budget: list[int]) -> tuple[set[bytes], bool]:
    """The names in the array starting at ``position``, nested arrays included,
    and whether it holds only names."""
    names: set[bytes] = set()
    only_names = True
    depth = 1
    start = position
    while depth and (token := _next_token(data, position, start, budget)) is not None:
        text = token[0]
        position = token.end()
        if text == b"]":
            depth -= 1
        elif text == b"/":
            name = _NAME.match(data, token.start())
            assert name is not None  # noqa: S101  (a "/" always starts a name)
            names.add(_unescape(name[1]))
            position = name.end()
        elif text[0] not in b" \t\r\n\f\x00%":
            only_names = False
            if text == b"(":
                position = _string_end(data, position)
            elif text == b"[":
                depth += 1
    budget[0] -= position - start
    return names, only_names and not depth


def _ends_in_stream(data: bytes, position: int, budget: list[int]) -> bool:
    """Whether the dictionary around ``position`` is followed by a stream.

    A dictionary still open at the end of the data has no stream after it:
    strings, comments and hex strings are read exactly as MuPDF reads them.
    One left open by the work cap is caught by the cap itself.
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
        return False
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
