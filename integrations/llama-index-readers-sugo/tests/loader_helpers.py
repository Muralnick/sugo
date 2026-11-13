"""Helpers the tests import by name (conftest.py itself is loaded under another name)."""

from typing import Any

import pymupdf


class NetworkBlockedError(RuntimeError):
    """A test tried to open a network connection."""


def blocked(*args: Any, **kwargs: Any) -> Any:
    raise NetworkBlockedError("network access is blocked in tests")


def make_pdf(*paragraphs: str) -> bytes:
    document = pymupdf.open()
    page = document.new_page()
    for row, text in enumerate(paragraphs):
        page.insert_text((72, 100 + row * 40), text, fontsize=11)
    return bytes(document.tobytes())
