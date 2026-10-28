"""Tests for sugo.metrics.baselines: both savings baselines of ADR-003."""

import pytest

from sugo.metrics.baselines import Savings, image_savings, text_savings
from sugo.metrics.providers import load_provider, parse_provider
from sugo.metrics.tokenizer import count_tokens


def test_saved_percent_is_relative_to_the_baseline() -> None:
    savings = Savings(baseline_tokens=200, result_tokens=50)
    assert savings.saved_tokens == 150
    assert savings.saved_percent == 75.0


def test_negative_savings_are_reported_not_hidden() -> None:
    savings = Savings(baseline_tokens=100, result_tokens=150)
    assert savings.saved_tokens == -50
    assert savings.saved_percent == -50.0


def test_empty_baseline_reports_zero_percent() -> None:
    assert Savings(baseline_tokens=0, result_tokens=0).saved_percent == 0.0


def test_text_savings_counts_both_texts() -> None:
    raw = "Page 1 of 10\nConfidential\nThe contract may be withdrawn.\nPage 1 of 10"
    clean = "The contract may be withdrawn."
    savings = text_savings(raw, clean)
    assert savings.baseline_tokens == count_tokens(raw)
    assert savings.result_tokens == count_tokens(clean)
    assert savings.saved_percent > 0


def test_image_savings_uses_provider_formula() -> None:
    savings = image_savings(1920, 1080, "Hello world", load_provider("claude"))
    assert (savings.baseline_tokens, savings.result_tokens) == (2691, 2)
    assert (savings.provider, savings.tier, savings.formula_verified) == (
        "claude",
        "high_resolution",
        True,
    )


def test_small_screenshot_can_cost_less_as_image() -> None:
    # ADR-003: a small image with a lot of text can be cheaper to send as an image.
    savings = image_savings(300, 200, "word " * 400, load_provider("gemini"))
    assert savings.saved_tokens < 0


def test_explicit_tier_is_recorded() -> None:
    savings = image_savings(1920, 1080, "x", load_provider("claude"), tier="standard")
    assert (savings.tier, savings.baseline_tokens) == ("standard", 1560)


def test_unknown_tier_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown tier"):
        image_savings(10, 10, "x", load_provider("gemini"), tier="ultra")


def test_unverified_formula_is_flagged_in_the_result() -> None:
    formulas = parse_provider(
        """
schema_version = 1
provider = "example"
default_tier = "standard"
[source]
description = "not checked"
url = "https://example.com/docs"
checked = 2026-10-28
status = "unverified"
[tiers.standard]
kind = "tiles"
tile_size = 512
tokens_per_tile = 170
"""
    )
    assert not image_savings(1024, 1024, "x", formulas).formula_verified
