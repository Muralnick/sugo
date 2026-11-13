"""LlamaIndex reader for Sugo (ADR-068).

    from llama_index.readers.sugo import SugoReader

    documents = SugoReader().load_data("handbook.pdf")

Each document is one Sugo chunk, with its pages and headings in the metadata.
"""

from llama_index.readers.sugo._reader import Mode, OnError, OnSecret, Skipped, SugoReader

__all__ = ["Mode", "OnError", "OnSecret", "Skipped", "SugoReader"]
