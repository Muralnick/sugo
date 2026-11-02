"""Count text tokens with tiktoken's o200k_base encoding, fully offline.

tiktoken normally downloads its vocabulary on first use. Sugo never lets it:
the vocabulary ships inside the package, is checked against a pinned SHA-256
on every load, and is parsed here instead of by tiktoken's loader, which would
also write a copy to a temporary cache directory (principle 1, ADR-038).
"""

import base64
import functools
import hashlib
from importlib import resources

from tiktoken.core import Encoding

from sugo.core.constants import O200K_BASE_SHA256
from sugo.i18n import gettext as _

# Copied from tiktoken_ext/openai_public.py (tiktoken 0.14.0, MIT): the
# pre-tokenisation pattern is part of the encoding, not of the vocabulary file.
_O200K_PATTERN = "|".join(
    [
        r"""[^\r\n\p{L}\p{N}]?[\p{Lu}\p{Lt}\p{Lm}\p{Lo}\p{M}]*[\p{Ll}\p{Lm}\p{Lo}\p{M}]+(?i:'s|'t|'re|'ve|'m|'ll|'d)?""",
        r"""[^\r\n\p{L}\p{N}]?[\p{Lu}\p{Lt}\p{Lm}\p{Lo}\p{M}]+[\p{Ll}\p{Lm}\p{Lo}\p{M}]*(?i:'s|'t|'re|'ve|'m|'ll|'d)?""",
        r"""\p{N}{1,3}""",
        r""" ?[^\s\p{L}\p{N}]+[\r\n/]*""",
        r"""\s*[\r\n]+""",
        r"""\s+(?!\S)""",
        r"""\s+""",
    ]
)
_O200K_SPECIAL_TOKENS = {"<|endoftext|>": 199999, "<|endofprompt|>": 200018}
_O200K_FILE = ("data", "tokenizers", "o200k_base.tiktoken")


class VocabularyIntegrityError(RuntimeError):
    """The bundled vocabulary does not match its pinned hash; it was altered or corrupted."""


def parse_vocabulary(data: bytes, expected_sha256: str) -> dict[bytes, int]:
    """Verify and parse a tiktoken vocabulary file.

    Args:
        data: File content: one base64-encoded token and its rank per line.
        expected_sha256: Pinned hexadecimal SHA-256 of the content.

    Returns:
        Mapping from token bytes to rank.

    Raises:
        VocabularyIntegrityError: If the hash does not match.
    """
    # The hash is checked before parsing, so altered content is never interpreted.
    if hashlib.sha256(data).hexdigest() != expected_sha256:
        raise VocabularyIntegrityError(_("tokenizer vocabulary failed its SHA-256 check"))
    ranks: dict[bytes, int] = {}
    for line in data.splitlines():
        if line:
            token, rank = line.split()
            ranks[base64.b64decode(token)] = int(rank)
    return ranks


@functools.cache
def get_encoding() -> Encoding:
    """Return the o200k_base encoding, loaded once per process from package data."""
    data = resources.files("sugo").joinpath(*_O200K_FILE).read_bytes()
    return Encoding(
        name="o200k_base",
        pat_str=_O200K_PATTERN,
        mergeable_ranks=parse_vocabulary(data, O200K_BASE_SHA256),
        special_tokens=_O200K_SPECIAL_TOKENS,
    )


def count_tokens(text: str) -> int:
    """Count the o200k_base tokens of a text.

    Special-token markers such as ``<|endoftext|>`` inside a document are counted
    as ordinary text: document content is data and must never act as a control
    token.
    """
    return len(get_encoding().encode_ordinary(text))
