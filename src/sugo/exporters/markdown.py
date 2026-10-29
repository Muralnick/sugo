"""Write a converted document as a Markdown file, optionally with YAML front matter.

Front matter is off by default: it costs tokens every time the file is read
by an LLM. When asked for, it records where the text comes from and how it
was made (ARCHITECTURE §13). Values are written as JSON strings, which are
valid YAML double-quoted scalars, so no document text can break out of them.
"""

import json
from collections.abc import Mapping
from pathlib import Path

from sugo.exporters.files import write_text_atomic


def front_matter(fields: Mapping[str, str | None]) -> str:
    """Render YAML front matter; None values are written as ``null``."""
    lines = ["---"]
    for name, value in fields.items():
        if not name.isidentifier():
            raise ValueError("front matter keys must be plain identifiers")
        lines.append(f"{name}: {'null' if value is None else json.dumps(value)}")
    lines.append("---")
    return "\n".join(lines) + "\n"


def write_markdown(
    path: Path, markdown: str, *, metadata: Mapping[str, str | None] | None = None
) -> None:
    """Write the Markdown to ``path``, ending with a newline.

    Args:
        path: The output file; replaced atomically.
        markdown: The converted document.
        metadata: Front matter fields; None writes no front matter.
    """
    head = "" if metadata is None else front_matter(metadata) + "\n"
    write_text_atomic(path, [head, markdown, "\n" if markdown else ""])
