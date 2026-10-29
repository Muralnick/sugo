"""Write chunks as JSON Lines, one chunk record per line (schema v1, ADR-023, ADR-047).

Each line is the chunk's validated JSON, fields in schema order, text kept
as UTF-8. Line breaks inside the text are escaped by JSON, and so are the
Unicode line separators JSON leaves raw (U+0085, U+2028, U+2029), which some
readers, Python's ``str.splitlines`` among them, would take for line ends.
One line is always one chunk, ready for a vector database loader.
"""

from collections.abc import Iterable
from pathlib import Path

from sugo.core.chunks import Chunk
from sugo.exporters.files import write_text_atomic

# Inside JSON strings only: these characters are never JSON syntax.
_LINE_SEPARATORS = str.maketrans({"\x85": "\\u0085", "\u2028": "\\u2028", "\u2029": "\\u2029"})


def jsonl_lines(chunks: Iterable[Chunk]) -> Iterable[str]:
    """Yield one JSON line per chunk, each ending with a newline."""
    for chunk in chunks:
        yield chunk.model_dump_json().translate(_LINE_SEPARATORS) + "\n"


def write_jsonl(path: Path, chunks: Iterable[Chunk]) -> None:
    """Write the chunks to ``path``, replacing it atomically."""
    write_text_atomic(path, jsonl_lines(chunks))
