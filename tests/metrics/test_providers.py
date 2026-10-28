"""Tests for sugo.metrics.providers: formulas, data-file validation and safe loading."""

import tomllib

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from sugo.metrics.providers import (
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
checked = 2026-10-28
status = "verified"

[tiers.standard]
kind = "patches"
patch_size = 28
max_long_edge = 1568
max_tokens = 1568
"""

sides = st.integers(min_value=1, max_value=20_000)


def test_bundled_providers_are_listed() -> None:
    assert list_providers() == ["claude", "gemini", "openai"]


@pytest.mark.parametrize("name", ["claude", "gemini", "openai"])
def test_bundled_provider_files_are_valid(name: str) -> None:
    assert load_provider(name).provider == name


def test_openai_formula_is_marked_unverified() -> None:
    # docs/ARCHITECTURE.md section 25: the recent OpenAI formula is still to verify.
    assert load_provider("openai").source.status is VerificationStatus.UNVERIFIED


class TestClaude:
    @pytest.mark.parametrize(
        ("width", "height", "expected"),
        [
            (28, 28, 1),
            (29, 28, 2),
            (1000, 1000, 36 * 36),
            # iPhone screenshot: resized to 724 x 1568, then 26 x 56 patches.
            (1170, 2532, 1456),
            # Square image resized to 1568 x 1568 exceeds the cap of 1568 tokens.
            (4000, 4000, 1568),
        ],
    )
    def test_standard_tier(self, width: int, height: int, expected: int) -> None:
        assert load_provider("claude").estimate(width, height) == expected

    def test_high_resolution_tier_allows_more_tokens(self) -> None:
        claude = load_provider("claude")
        assert claude.estimate(4000, 4000, "high_resolution") == 4784

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
        # Worked examples of the older tile formula: 1024 x 1024 -> 768 x 768 -> 4 tiles.
        [(1024, 1024, 765), (2048, 4096, 1105), (512, 512, 255)],
    )
    def test_high_detail_tiles(self, width: int, height: int, expected: int) -> None:
        assert load_provider("openai").estimate(width, height) == expected


@pytest.mark.parametrize(("width", "height"), [(0, 10), (10, 0), (-5, 10)])
def test_non_positive_image_size_is_rejected(width: int, height: int) -> None:
    with pytest.raises(ValueError, match="positive"):
        load_provider("claude").estimate(width, height)


@given(width=sides, height=sides)
def test_patch_estimate_stays_within_cap(width: int, height: int) -> None:
    formula = PatchFormula(kind="patches", patch_size=28, max_long_edge=1568, max_tokens=1568)
    assert 1 <= formula.estimate(width, height) <= 1568


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
