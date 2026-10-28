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

    @pytest.mark.parametrize(
        ("tier", "width", "height", "expected"),
        [
            # Examples stated in the official documentation pages.
            ("standard", 1920, 1080, (1456, 819)),
            ("standard", 1075, 1520, (924, 1307)),  # A4 at 130 DPI: token limit, not edge
            ("high_resolution", 1075, 1520, (1075, 1520)),
            ("high_resolution", 3840, 2160, (2576, 1449)),
            # The table prints 1269 x 952; the official reference code gives
            # 1270 x 952 (same 1564 tokens). Sugo follows the reference code.
            ("standard", 2000, 1500, (1270, 952)),
        ],
    )
    def test_resized_size_matches_documentation(
        self, tier: str, width: int, height: int, expected: tuple[int, int]
    ) -> None:
        formula = load_provider("claude").tiers[tier]
        assert isinstance(formula, PatchFormula)
        assert formula.resized_size(width, height) == expected

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
        assert load_provider("openai").estimate(width, height, "gpt-6-astra-high") == expected

    def test_default_is_the_api_default_detail_auto(self) -> None:
        # gpt-6-astra auto = original: no budget, 1170 x 2532 -> 37 x 80 patches.
        openai = load_provider("openai")
        assert openai.default_tier == "gpt-6-astra-auto"
        assert openai.estimate(1170, 2532) == math.ceil(37 * 80 * 1.2)

    @pytest.mark.parametrize(
        ("tier", "width", "height", "expected"),
        [
            # low fits within 512 px: 1024 x 1024 -> 512 x 512 -> 16 x 16 patches.
            ("gpt-6-astra-low", 1024, 1024, math.ceil(256 * 1.2)),
            # high on gpt-5.6 fits within 2048 px first, then the 2500 budget.
            ("gpt-5.6-high", 4096, 4096, 3000),
            # gpt-5.5 original: 6000 px and 10 000 patches.
            ("gpt-5.5-original", 3000, 3000, math.ceil(94 * 94 * 1.2)),
            # gpt-5.4 low has a larger budget than high, so it can cost more.
            ("gpt-5.4-low", 2048, 2048, math.ceil(4096 * 1.2)),
            ("gpt-5.4-high", 2048, 2048, 3000),
            ("gpt-5.4-auto", 2048, 2048, 3000),  # auto behaves like high
            # gpt-4.1-mini: 6144-patch budget and multiplier 1.62.
            ("gpt-4.1-mini-auto", 1024, 1024, math.ceil(1024 * 1.62)),
        ],
    )
    def test_sizing_table_tiers(self, tier: str, width: int, height: int, expected: int) -> None:
        assert load_provider("openai").estimate(width, height, tier) == expected

    @pytest.mark.parametrize(
        ("tier", "expected"), [("gpt-4o-low", 85), ("gpt-4.1-low", 85), ("gpt-4o-mini-low", 2833)]
    )
    def test_detail_low_costs_base_tokens_only(self, tier: str, expected: int) -> None:
        openai = load_provider("openai")
        assert openai.estimate(64, 64, tier) == expected
        assert openai.estimate(4000, 3000, tier) == expected

    def test_original_detail_rejects_images_above_30000_patches(self) -> None:
        # 6000 x 6000 needs 188 x 188 = 35 344 patches; original never resizes to fit.
        with pytest.raises(ImageRejectedError):
            load_provider("openai").estimate(6000, 6000, "gpt-6-astra-original")

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


def _official_resized_size(
    width: int, height: int, max_edge: int = 1568, max_tokens: int = 1568
) -> tuple[int, int]:
    # Copied verbatim from Anthropic's "How Claude resizes and pads images"
    # reference implementation (checked 2026-10-28); only type hints differ.
    def fits(w: int, h: int) -> bool:
        return (
            math.ceil(w / 28) * 28 <= max_edge
            and math.ceil(h / 28) * 28 <= max_edge
            and math.ceil(w / 28) * math.ceil(h / 28) <= max_tokens
        )

    if fits(width, height):
        return (width, height)
    if height > width:
        resized_h, resized_w = _official_resized_size(height, width, max_edge, max_tokens)
        return (resized_w, resized_h)
    aspect_ratio = width / height
    lo, hi = 1, width
    while lo + 1 < hi:
        mid = (lo + hi) // 2
        if fits(mid, max(round(mid / aspect_ratio), 1)):
            lo = mid
        else:
            hi = mid
    return (lo, max(round(lo / aspect_ratio), 1))


@given(width=sides, height=sides)
@pytest.mark.parametrize("tier", ["standard", "high_resolution"])
def test_claude_matches_official_reference(tier: str, width: int, height: int) -> None:
    formula = load_provider("claude").tiers[tier]
    assert isinstance(formula, PatchFormula)
    expected = _official_resized_size(width, height, formula.max_long_edge, formula.max_tokens)
    assert formula.resized_size(width, height) == expected
    assert formula.estimate(width, height) == math.ceil(expected[0] / 28) * math.ceil(
        expected[1] / 28
    )


@given(
    width=sides,
    height=sides,
    # Limits that are not multiples of 28 exercise the padded edge check, which
    # the bundled tiers (1568 = 56 x 28, 2576 = 92 x 28) never reach.
    max_edge=st.integers(min_value=28, max_value=3000),
    max_tokens=st.integers(min_value=1, max_value=5000),
)
def test_patch_formula_matches_reference_for_any_limits(
    width: int, height: int, max_edge: int, max_tokens: int
) -> None:
    formula = PatchFormula(
        kind="patches", patch_size=28, max_long_edge=max_edge, max_tokens=max_tokens
    )
    expected = _official_resized_size(width, height, max_edge, max_tokens)
    assert formula.resized_size(width, height) == expected


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

    def test_alias_resolves_to_its_tier(self) -> None:
        formulas = parse_provider(VALID + '\n[aliases]\nauto = "standard"\n')
        assert formulas.estimate(1000, 1000, "auto") == formulas.estimate(1000, 1000, "standard")

    @pytest.mark.parametrize(
        ("aliases", "message"),
        [('auto = "missing"', "unknown tier"), ('standard = "standard"', "hides a tier")],
    )
    def test_invalid_aliases_are_rejected(self, aliases: str, message: str) -> None:
        with pytest.raises(ValidationError, match=message):
            parse_provider(VALID + f"\n[aliases]\n{aliases}\n")

    def test_small_image_settings_must_come_in_pairs(self) -> None:
        with pytest.raises(ValidationError, match="together"):
            TileFormula(kind="tiles", tile_size=768, tokens_per_tile=258, small_max_side=384)

    def test_malformed_toml_is_rejected(self) -> None:
        with pytest.raises(tomllib.TOMLDecodeError):
            parse_provider("provider = ")
