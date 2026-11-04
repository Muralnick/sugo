"""Write a conversion receipt as one JSON document (schema v1, ADR-056).

Written through the same atomic writer as the Markdown and JSONL exporters:
a reader sees the old file or the new one, never half.
"""

from pathlib import Path

from sugo.core.receipt import Receipt
from sugo.exporters.files import write_text_atomic

# Never JSON syntax; some readers treat them as line ends (as in ADR-047's JSONL).
# chr() avoids embedding the raw separator characters themselves in this file.
_LINE_SEPARATORS = str.maketrans(
    {"\x85": "\\u0085", chr(0x2028): "\\u2028", chr(0x2029): "\\u2029"}
)


def write_receipt(path: Path, receipt: Receipt) -> None:
    """Write the receipt to ``path``, replacing it atomically."""
    write_text_atomic(path, (receipt.model_dump_json().translate(_LINE_SEPARATORS),))
