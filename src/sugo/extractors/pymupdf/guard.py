"""Refuse PDFs that would reach MuPDF's Brotli decoder (CVE-2026-111497, ADR-043).

MuPDF below 1.28.6 has an out-of-bounds write in its bundled Brotli decoder,
reached by any stream or inline image compressed with ``/BrotliDecode``.
Brotli is a recent addition to PDF and almost never used, so such files are
refused until a PyMuPDF release ships the fix; then this module goes away.

Two layers, so MuPDF never decodes Brotli data:

1. ``raw_problem`` runs in Sugo on the file bytes, before MuPDF sees them. Stream
   dictionaries are never compressed (a stream cannot sit inside an object
   stream), so every ``/Filter`` of every stream is visible in the raw bytes,
   unless it is an indirect reference whose name hides in compressed data:
   those are refused too, as no real PDF writer produces them.
2. The worker, after layer 1 passed, runs ``names_brotli`` on every decoded
   stream, where inline images name their own filter. Every stream, because
   a dictionary's ``/Subtype`` is written by the attacker: a page's content
   can claim to be an image and is still interpreted as content.

This module never imports MuPDF, so the first layer runs without it.

Names may escape characters as ``#xx`` (``/Br#6ftliDecode``); both layers
undo the escapes before looking. MuPDF also accepts the inline-image
abbreviation ``/Br``, which is short enough to occur by chance in compressed
data; it only counts as a filter name right after a filter key (``/Filter``,
or ``/F`` in inline images), alone or in an array. The full name is long
enough to count anywhere.
"""

import re

from sugo.i18n import N_

# Marked, not translated: the worker sends it as data and the parent translates it.
# Filled with MAX_PDF_PAGES by the worker; the parent recognises the result.
PAGES_REFUSAL = N_("the PDF has more than {pages} pages")
BROTLI_REFUSAL = N_("the PDF uses Brotli compression, refused until MuPDF fixes CVE-2026-111497")

_NAME_ESCAPE = re.compile(rb"#([0-9A-Fa-f]{2})")
# One unit of PDF whitespace: a whitespace byte (NUL included) or a comment,
# which runs to the end of its line. The two never start with the same byte
# and a comment must reach its line end, so matching never backtracks
# exponentially on hostile input.
_SPACE = rb"(?:[\s\x00]|%[^\r\n]*[\r\n])"
# "5 0 R": two numbers need whitespace between them, or they would be one.
_REF = rb"\d+" + _SPACE + rb"+\d+" + _SPACE + rb"*R"
# Filter arrays are short; the bound keeps a file full of unclosed "[" cheap.
_INDIRECT_FILTER = re.compile(
    rb"/Filter" + _SPACE + rb"*(?:" + _REF + rb"|\[[^\]]{0,512}?" + _REF + rb")"
)
# Brotli as a filter: the full name anywhere; the abbreviation "/Br" only as a
# whole name right after a filter key, alone or inside a short array.
_NAME_END = rb"(?=[\s\x00/\[\]<>(){}%]|$)"
_BROTLI_NAME = rb"/Br(?:otliDecode)?" + _NAME_END
_BROTLI = re.compile(
    rb"/BrotliDecode|/F(?:ilter)?"
    + _SPACE
    + rb"*(?:"
    + _BROTLI_NAME
    + rb"|\[[^\]]{0,512}?"
    + _BROTLI_NAME
    + rb")"
)


def raw_problem(data: bytes) -> str | None:
    """Why the raw PDF bytes must be refused, or None if they may be parsed."""
    unescaped = _unescape(data)
    if _BROTLI.search(unescaped):
        return BROTLI_REFUSAL
    if _INDIRECT_FILTER.search(unescaped):
        return N_("the PDF names a stream filter indirectly, which Sugo cannot check safely")
    return None


def names_brotli(data: bytes) -> bool:
    """Whether PDF bytes, raw or decoded, name the Brotli filter."""
    return _BROTLI.search(_unescape(data)) is not None


def _unescape(data: bytes) -> bytes:
    return _NAME_ESCAPE.sub(lambda match: bytes.fromhex(match[1].decode()), data)
