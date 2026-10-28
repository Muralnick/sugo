"""Tests for sugo.metrics.tokenizer: correct counts, integrity check, no network."""

import hashlib
import socket
from collections.abc import Iterator
from importlib import resources
from typing import Any, NoReturn

import pytest
import tiktoken.load
from tiktoken.core import Encoding
from tiktoken_ext import openai_public  # type: ignore[import-untyped]

from sugo.core.constants import O200K_BASE_SHA256
from sugo.metrics import tokenizer
from sugo.metrics.tokenizer import (
    VocabularyIntegrityError,
    count_tokens,
    get_encoding,
    parse_vocabulary,
)


@pytest.fixture
def fresh_encoding() -> Iterator[None]:
    # Forces the next get_encoding() call to load the file again.
    get_encoding.cache_clear()
    yield
    get_encoding.cache_clear()


def test_bundled_vocabulary_matches_pinned_hash() -> None:
    data = resources.files("sugo").joinpath("data", "tokenizers", "o200k_base.tiktoken")
    assert hashlib.sha256(data.read_bytes()).hexdigest() == O200K_BASE_SHA256


def test_empty_text_has_no_tokens() -> None:
    assert count_tokens("") == 0


def test_hello_world_matches_published_o200k_ids() -> None:
    assert get_encoding().encode_ordinary("Hello world") == [13225, 2375]


@pytest.mark.parametrize(
    "text",
    [
        "Il contratto può essere risolto entro 30 giorni.",
        "Der Vertrag kann widerrufen werden.",
        "契約は30日以内に解除できます。",
        "合同可以在三十天内解除。",
        "  tabs\tand\r\nnewlines\n\n  ",
        "def f(x):\n    return x ** 2  # it's",
    ],
)
def test_encoding_matches_tiktoken_definition(monkeypatch: pytest.MonkeyPatch, text: str) -> None:
    # Our copy of the pattern and special tokens must equal tiktoken's own
    # definition; only the vocabulary source differs (bundled, not downloaded).
    ranks = get_encoding()._mergeable_ranks
    monkeypatch.setattr(openai_public, "load_tiktoken_bpe", lambda *_a, **_k: ranks)
    reference = Encoding(**openai_public.o200k_base())
    assert get_encoding().encode_ordinary(text) == reference.encode_ordinary(text)
    assert get_encoding()._pat_str == reference._pat_str
    assert get_encoding()._special_tokens == reference._special_tokens


def test_special_token_markers_in_documents_are_plain_text() -> None:
    # A document containing "<|endoftext|>" must neither raise nor become one control token.
    assert count_tokens("<|endoftext|>") > 1


def test_encoding_is_loaded_once() -> None:
    assert get_encoding() is get_encoding()


def test_parse_rejects_altered_vocabulary() -> None:
    with pytest.raises(VocabularyIntegrityError):
        parse_vocabulary(b"IQ== 0\n", O200K_BASE_SHA256)


def test_parse_reads_tokens_and_ranks() -> None:
    data = b"IQ== 0\nIg== 1\n"
    assert parse_vocabulary(data, hashlib.sha256(data).hexdigest()) == {b"!": 0, b'"': 1}


def test_tampered_bundled_file_is_refused(
    monkeypatch: pytest.MonkeyPatch, fresh_encoding: None
) -> None:
    monkeypatch.setattr(tokenizer, "O200K_BASE_SHA256", "0" * 64)
    with pytest.raises(VocabularyIntegrityError):
        get_encoding()


@pytest.mark.invariant
def test_loading_and_counting_never_touch_the_network(
    monkeypatch: pytest.MonkeyPatch, fresh_encoding: None
) -> None:
    # Principle 1 and ADR-036: tiktoken must never download its vocabulary.
    def forbidden(*_args: Any, **_kwargs: Any) -> NoReturn:
        raise AssertionError("network or tiktoken loader used")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(tiktoken.load, "read_file", forbidden)
    monkeypatch.setattr(tiktoken.load, "read_file_cached", forbidden)
    assert count_tokens("Documents, reduced.") > 0
