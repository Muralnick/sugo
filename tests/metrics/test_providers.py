"""Tests for sugo.metrics.providers: formulas, data-file validation and safe loading."""

import math
import tomllib

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from sugo.metrics.providers import (
    BudgetedPatchFormula,
    ImageRejectedError,
    PatchFormula,
    TileFormula,
    VerificationStatus,
    list_providers,
    load_provider,
    parse_provider,
)

VALID = """
schema_version = 1
provider = "example"
default_tier = "standard"

[source]
description = "test"
url = "https://example.com/docs"
checked = 2026-10-28
status = "verified"

[tiers.standard]
kind = "patches"
patch_size = 28
max_long_edge = 1568
max_tokens = 1568
"""

# Every row of the table in the official Vision documentation, section
# "Resolution and token cost" (checked 2026-10-28).
CLAUDE_OFFICIAL_TABLE = (
    # width, height, standard tier, high-resolution tier
    (200, 200, 64, 64),
    (1000, 1000, 1296, 1296),
    (1092, 1092, 1521, 1521),
    (1920, 1080, 1560, 2691),
    (2000, 1500, 1564, 3888),
    (3840, 2160, 1560, 4784),
)

sides = st.integers(min_value=1, max_value=20_000)


def test_bundled_providers_are_listed() -> None:
    assert list_providers() == ["claude", "gemini", "openai"]


@pytest.mark.parametrize("name", ["claude", "gemini", "openai"])
def test_bundled_provider_files_are_valid(name: str) -> None:
    assert load_provider(name).provider == name


@pytest.mark.parametrize("name", ["claude", "gemini", "openai"])
def test_bundled_formulas_are_verified_with_official_url(name: str) -> None:
    source = load_provider(name).source
    assert source.status is VerificationStatus.VERIFIED
    assert source.url.startswith("https://")


class TestClaude:
    @pytest.mark.parametrize(("width", "height", "standard", "high"), CLAUDE_OFFICIAL_TABLE)
    def test_matches_official_table(
        self, width: int, height: int, standard: int, high: int
    ) -> None:
        claude = load_provider("claude")
        assert claude.estimate(width, height, "standard") == standard
        assert claude.estimate(width, height, "high_resolution") == high

    @pytest.mark.parametrize(("width", "height", "standard", "high"), CLAUDE_OFFICIAL_TABLE)
    def test_orientation_does_not_change_the_cost(
        self, width: int, height: int, standard: int, high: int
    ) -> None:
        claude = load_provider("claude")
        assert claude.estimate(height, width, "standard") == standard
        assert claude.estimate(height, width, "high_resolution") == high

    def test_default_tier_is_high_resolution_for_current_models(self) -> None:
        assert load_provider("claude").estimate(1920, 1080) == 2691

    def test_unknown_tier_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="unknown tier"):
            load_provider("claude").estimate(100, 100, "ultra")


class TestGemini:
    @pytest.mark.parametrize(
        ("width", "height", "expected"),
        [(384, 384, 258), (385, 100, 258), (768, 768, 258), (769, 768, 516), (1170, 2532, 2064)],
    )
    def test_small_images_and_tiles(self, width: int, height: int, expected: int) -> None:
        assert load_provider("gemini").estimate(width, height) == expected


class TestOpenAI:
    @pytest.mark.parametrize(
        ("width", "height", "expected"),
        # Worked examples for gpt-6-astra, detail high, in the official documentation.
        [(1024, 1024, 1229), (2048, 2048, 3000), (4096, 512, 2458)],
    )
    def test_patch_budget_examples(self, width: int, height: int, expected: int) -> None:
        assert load_provider("openai").estimate(width, height) == expected

    @pytest.mark.parametrize(
        ("tier", "expected"),
        # 1024 x 1024 -> 768 x 768 -> four 512 px tiles, plus base tokens.
        [
            ("gpt-4o-high", 85 + 4 * 170),
            ("gpt-5.1-high", 70 + 4 * 140),
            ("gpt-4o-mini-high", 2833 + 4 * 5667),
        ],
    )
    def test_tile_models(self, tier: str, expected: int) -> None:
        assert load_provider("openai").estimate(1024, 1024, tier) == expected

    def test_images_above_patch_limit_are_rejected(self) -> None:
        formula = BudgetedPatchFormula(
            kind="budgeted_patches",
            patch_size=32,
            max_dimension=65535,
            max_patches=100,
            multiplier=1.0,
        )
        with pytest.raises(ImageRejectedError):
            formula.estimate(1024, 1024)

    def test_multiplier_is_applied_without_float_error(self) -> None:
        # 320 x 480 needs 10 x 15 = 150 patches; 150 * 1.62 is 243.00000000000003
        # in binary floating point, so a naive ceil() would give 244.
        formula = BudgetedPatchFormula(
            kind="budgeted_patches",
            patch_size=32,
            max_dimension=65535,
            max_patches=30000,
            multiplier=1.62,
        )
        assert formula.estimate(320, 480) == 243


@pytest.mark.parametrize(("width", "height"), [(0, 10), (10, 0), (-5, 10)])
def test_non_positive_image_size_is_rejected(width: int, height: int) -> None:
    with pytest.raises(ValueError, match="positive"):
        load_provider("claude").estimate(width, height)


@given(width=sides, height=sides)
def test_patch_estimate_stays_within_cap(width: int, height: int) -> None:
    formula = PatchFormula(kind="patches", patch_size=28, max_long_edge=1568, max_tokens=1568)
    assert 1 <= formula.estimate(width, height) <= 1568


def _reference_patch_tokens(width: int, height: int) -> int:
    # Slow, obvious version of the documented rule: try every long edge from the
    # largest allowed downwards and keep the first one within both limits.
    long_side, short_side = max(width, height), min(width, height)
    for long_edge in range(min(long_side, 1568), 0, -1):
        short_edge = max(1, short_side * long_edge // long_side)
        tokens = math.ceil(long_edge / 28) * math.ceil(short_edge / 28)
        if tokens <= 1568:
            return tokens
    raise AssertionError("unreachable: a 1 px image always fits")


@given(width=sides, height=sides)
def test_patch_estimate_matches_reference(width: int, height: int) -> None:
    formula = PatchFormula(kind="patches", patch_size=28, max_long_edge=1568, max_tokens=1568)
    assert formula.estimate(width, height) == _reference_patch_tokens(width, height)


@given(width=sides, height=sides)
def test_budgeted_estimate_stays_within_budget(width: int, height: int) -> None:
    formula = BudgetedPatchFormula(
        kind="budgeted_patches",
        patch_size=32,
        max_dimension=65535,
        patch_budget=2500,
        max_patches=30000,
        multiplier=1.0,
    )
    assert 1 <= formula.estimate(width, height) <= 2500


@given(width=sides, height=sides)
def test_tile_estimate_is_at_least_one_tile(width: int, height: int) -> None:
    formula = TileFormula(kind="tiles", tile_size=768, tokens_per_tile=258)
    assert formula.estimate(width, height) >= 258


class TestLoadingIsSafe:
    @pytest.mark.parametrize(
        "name", ["../claude", "claude.toml", "Claude", "a/b", "C:claude", "", "claude\x00"]
    )
    def test_malformed_names_never_reach_the_filesystem(self, name: str) -> None:
        with pytest.raises(ValueError, match="invalid provider name"):
            load_provider(name)

    def test_unknown_provider_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="unknown provider"):
            load_provider("mistral")


class TestDataFileValidation:
    def test_valid_file_parses(self) -> None:
        assert parse_provider(VALID).estimate(28, 28) == 1

    @pytest.mark.parametrize(
        ("old", "new"),
        [
            ("patch_size = 28", "patch_size = 28\nbonus = 1"),  # unknown key
            ("patch_size = 28", "patch_size = -28"),  # negative value
            ("patch_size = 28", "patch_size = 0"),  # division by zero
            ("max_tokens = 1568", "max_tokens = 10000000"),  # absurd value
            ("max_tokens = 1568", 'max_tokens = "1568"'),  # wrong type
            ("patch_size = 28", "patch_size = 28.5"),  # float instead of int
            ('kind = "patches"', 'kind = "pixels"'),  # unknown formula kind
            ("schema_version = 1", "schema_version = 2"),  # future schema
            ('default_tier = "standard"', 'default_tier = "missing"'),
            ('status = "verified"', 'status = "maybe"'),
            ('provider = "example"', 'provider = "../evil"'),
            ('url = "https://example.com/docs"', 'url = "http://example.com/docs"'),
            ('url = "https://example.com/docs"', 'url = "javascript:alert(1)"'),
        ],
    )
    def test_invalid_files_are_rejected(self, old: str, new: str) -> None:
        assert old in VALID
        with pytest.raises(ValidationError):
            parse_provider(VALID.replace(old, new))

    def test_small_image_settings_must_come_in_pairs(self) -> None:
        with pytest.raises(ValidationError, match="together"):
            TileFormula(kind="tiles", tile_size=768, tokens_per_tile=258, small_max_side=384)

    def test_malformed_toml_is_rejected(self) -> None:
        with pytest.raises(tomllib.TOMLDecodeError):
            parse_provider("provider = ")
