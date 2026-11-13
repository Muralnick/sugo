"""Sugo: local conversion of documents and images into compact Markdown for LLMs and RAG.

The public Python API (ADR-067) is what this package exports in ``__all__``::

    import sugo

    result = sugo.convert("manual.pdf", chunks=True)
    print(result.markdown, len(result.chunks))

The names are loaded on first use, so ``import sugo`` stays cheap.
"""

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sugo.api import Chunk, Result, SugoError, convert

    __version__: str

__all__ = ["Chunk", "Result", "SugoError", "__version__", "convert"]

# A library adds no output of its own: the application decides (ADR-067).
logging.getLogger(__name__).addHandler(logging.NullHandler())

_API_NAMES = frozenset({"Chunk", "Result", "SugoError", "convert"})


# Hidden from type checkers, so a misspelt name is still an error for them.
if not TYPE_CHECKING:

    def __getattr__(name: str) -> Any:
        if name == "__version__":
            from importlib.metadata import version

            from sugo.core.constants import DISTRIBUTION_NAME

            return version(DISTRIBUTION_NAME)
        if name in _API_NAMES:
            from sugo import api

            return getattr(api, name)
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted({*globals(), *__all__})
