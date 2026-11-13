"""Private keys written in a document's text (ADR-053).

The MCP server refuses such a document, and the Python API reports it so the
framework loaders can skip it (ADR-067, ADR-068). One check for all of them.
"""

import re

from sugo.core.constants import MCP_PRIVATE_KEY_PATTERN

_PRIVATE_KEY = re.compile(MCP_PRIVATE_KEY_PATTERN, re.IGNORECASE)
# Table cells join their lines with "<br>", which would split a wrapped key
# header where the pattern expects white space.
_LINE_BREAK_TAG = re.compile(r"<br\s*/?>", re.IGNORECASE)


def holds_private_key(*texts: str) -> bool:
    """True if any text holds the header of a PEM or OpenPGP private key."""
    return any(_PRIVATE_KEY.search(_LINE_BREAK_TAG.sub(" ", text)) for text in texts)
