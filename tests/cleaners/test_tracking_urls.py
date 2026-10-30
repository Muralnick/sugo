"""Tests for the tracking URL cleaner: trackers go, the link keeps working (ADR-050)."""

import pytest

from sugo.analyzers.lexicon import LexiconAnalyzer
from sugo.cleaners.tracking_urls import TrackingUrlCleaner, tracking_spans
from sugo.core.decisions import apply_decisions
from sugo.core.models import Block, BlockType, Page, PageOrigin
from sugo.metrics.tokenizer import count_tokens


def clean(text: str, block_type: BlockType = BlockType.PARAGRAPH) -> str:
    p = Page(
        index=0,
        width=100,
        height=100,
        origin=PageOrigin.NATIVE,
        blocks=(Block(id="b", type=block_type, text=text, origin_engine="t"),),
    )
    cleaner = TrackingUrlCleaner()
    stats = LexiconAnalyzer().finalize()
    return apply_decisions(p, cleaner.propose(p, stats), cleaner=cleaner.name).blocks[0].text


def strip(url: str) -> str:
    for start, end in reversed(tracking_spans(url)):
        url = url[:start] + url[end:]
    return url


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://a.it/p?utm_source=n", "https://a.it/p"),
        ("https://a.it/p?utm_source=n&utm_medium=e", "https://a.it/p"),
        ("https://a.it/p?id=7&utm_source=n", "https://a.it/p?id=7"),
        ("https://a.it/p?utm_source=n&id=7", "https://a.it/p?id=7"),
        ("https://a.it/p?a=1&fbclid=x&gclid=y&b=2", "https://a.it/p?a=1&b=2"),
        ("https://a.it/p?a=1&UTM_Campaign=x&b=2&mc_eid=3", "https://a.it/p?a=1&b=2"),
        ("https://a.it/p?utm_source=n#part", "https://a.it/p#part"),
        ("https://a.it/p?id=7#utm_source=n", "https://a.it/p?id=7#utm_source=n"),
        ("https://a.it/p?id=7", "https://a.it/p?id=7"),
        ("https://a.it/p", "https://a.it/p"),
        ("https://a.it/p?source=n&utmost=1", "https://a.it/p?source=n&utmost=1"),
    ],
)
def test_only_tracking_parameters_go(url: str, expected: str) -> None:
    assert strip(url) == expected


def test_urls_in_prose_are_cleaned_and_punctuation_kept() -> None:
    text = "See https://a.it/p?id=1&utm_source=n. Or (http://b.it/?fbclid=z)!"
    assert clean(text) == "See https://a.it/p?id=1. Or (http://b.it/)!"


def test_code_is_left_alone() -> None:
    code = 'fetch("https://a.it/p?utm_source=n")'
    assert clean(code, BlockType.CODE) == code


def test_each_deletion_is_recorded() -> None:
    p = Page(
        index=0,
        width=100,
        height=100,
        origin=PageOrigin.NATIVE,
        blocks=(
            Block(
                id="b",
                type=BlockType.PARAGRAPH,
                text="https://a.it/?utm_a=1&k=2&gclid=3",
                origin_engine="t",
            ),
        ),
    )
    cleaner = TrackingUrlCleaner()
    block = apply_decisions(
        p, cleaner.propose(p, LexiconAnalyzer().finalize()), cleaner="tracking_urls"
    ).blocks[0]
    assert [e.original for e in block.edits] == ["utm_a=1&", "&gclid=3"]
    assert {e.edited_by for e in block.edits} == {"tracking_urls"}
    assert block.original_text() == "https://a.it/?utm_a=1&k=2&gclid=3"


def test_newsletter_link_costs_half_the_tokens() -> None:
    text = (
        "Read the full information at https://news.example.com/article/2026/10/sugo"
        "?utm_source=newsletter&utm_medium=email&utm_campaign=october"
        "&fbclid=IwAR0abc123def456 and share it."
    )
    cleaned = clean(text)
    assert cleaned.endswith("https://news.example.com/article/2026/10/sugo and share it.")
    # Measured 47 -> 22 o200k_base tokens (-53%); fails below -40%.
    assert count_tokens(cleaned) <= count_tokens(text) * 0.6


def test_url_with_endless_trackers_is_left_alone() -> None:
    text = "https://x.it/?" + "utm_a=1&x=1&" * 5_000
    assert clean(text) == text
