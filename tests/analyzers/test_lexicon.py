"""Tests for the lexicon analyzer: the words of a document, kept as hashes."""

import pytest

from sugo.analyzers import lexicon as lexicon_module
from sugo.analyzers.lexicon import Lexicon, LexiconAnalyzer
from sugo.core.models import Block, BlockFlag, BlockType, Page, PageOrigin


def page(index: int, *texts: str, flags: tuple[BlockFlag, ...] = ()) -> Page:
    blocks = tuple(
        Block(id=f"b{n}", type=BlockType.PARAGRAPH, text=text, origin_engine="t", flags=flags)
        for n, text in enumerate(texts)
    )
    return Page(index=index, width=100, height=100, origin=PageOrigin.NATIVE, blocks=blocks)


def lexicon(*pages: Page) -> Lexicon:
    analyzer = LexiconAnalyzer()
    for p in pages:
        analyzer.observe(p)
    return analyzer.finalize()


def test_words_are_found_whatever_their_case() -> None:
    words = lexicon(page(0, "The Information age, well-known."))
    assert "information" in words
    assert "INFORMATION" in words
    assert "well-known" in words
    assert "misinformation" not in words


def test_a_word_split_across_lines_is_two_words() -> None:
    words = lexicon(page(0, "infor-\nmation"))
    assert "information" not in words
    assert "infor" in words


def test_soft_hyphens_inside_a_word_are_ignored() -> None:
    assert "information" in lexicon(page(0, "infor" + chr(0xAD) + "mation"))


def test_hidden_and_removed_text_does_not_count() -> None:
    hidden = page(0, "information", flags=(BlockFlag.HIDDEN,))
    removed = page(1, "information").model_copy(
        update={"blocks": (page(1, "information").blocks[0].mark_removed("c", "r"),)}
    )
    assert "information" not in lexicon(hidden, removed)


def test_lexicon_holds_no_text() -> None:
    words = lexicon(page(0, "confidential"))
    assert b"confidential" not in repr(words._words).encode()


def test_digest_does_not_depend_on_page_order() -> None:
    a, b = page(0, "alpha beta"), page(1, "gamma")
    assert lexicon(a, b).digest() == lexicon(b, a).digest()
    assert lexicon(a).digest() != lexicon(a, b).digest()


def test_page_observed_twice_is_refused() -> None:
    analyzer = LexiconAnalyzer()
    analyzer.observe(page(0, "a"))
    with pytest.raises(ValueError, match="observed twice"):
        analyzer.observe(page(0, "a"))


def test_word_count_is_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lexicon_module, "LEXICON_MAX_WORDS", 2)
    words = lexicon(page(0, "one two three four"))
    assert len(words._words) == 2
    assert "three" not in words
