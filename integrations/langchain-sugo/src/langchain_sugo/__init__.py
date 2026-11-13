"""LangChain document loader for Sugo (ADR-068).

    from langchain_sugo import SugoLoader

    documents = SugoLoader("handbook.pdf").load()

Each document is one Sugo chunk, with its pages and headings in the metadata.
"""

from langchain_sugo._loader import Mode, OnError, OnSecret, Skipped, SugoLoader

__all__ = ["Mode", "OnError", "OnSecret", "Skipped", "SugoLoader"]
