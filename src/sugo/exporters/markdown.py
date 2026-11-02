"""Write a converted document as a Markdown file, optionally with YAML front matter.

Front matter is off by default: it costs tokens every time the file is read
by an LLM. When asked for, it records where the text comes from and how it
was made (ARCHITECTURE §13). Values are double-quoted scalars that no text
can break out of: JSON escapes quotes, backslashes and control characters,
and characters YAML forbids or reads as line breaks (C1 controls, U+2028,
U+2029, U+FFFE, U+FFFF) are escaped too. Other characters, emoji included,
are written as they are: YAML has no surrogate-pair escapes. A lone
surrogate, which UTF-8 cannot encode, becomes U+FFFD.
"""

import json
from collections.abc import Mapping
from pathlib import Path

from sugo.exporters.files import write_text_atomic

_YAML_ESCAPES = {
    code: f"\\u{code:04x}" for code in (*range(0x7F, 0xA0), 0x2028, 0x2029, 0xFFFE, 0xFFFF)
}
_YAML_ESCAPES.update({code: "\\ufffd" for code in range(0xD800, 0xE000)})


def _quoted(value: str) -> str:
    return json.dumps(value, ensure_ascii=False).translate(_YAML_ESCAPES)


def front_matter(fields: Mapping[str, str | None]) -> str:
    """Render YAML front matter; None values are written as ``null``."""
    lines = ["---"]
    for name, value in fields.items():
        if not name.isidentifier():
            raise ValueError("front matter keys must be plain identifiers")
        lines.append(f"{name}: {'null' if value is None else _quoted(value)}")
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
