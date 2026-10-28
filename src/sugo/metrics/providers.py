"""Provider image-token formulas, loaded from data files (ADR-003).

Providers bill images in their own tokens, with formulas that change over time.
The formula *kinds* live here as code; their numbers live in TOML files under
``sugo/data/providers/``, each with its source, check date and verification
status, so a pricing change needs a data update, not a release.

Formula files are validated strictly: unknown keys, wrong types and absurd
values are rejected, because later versions will also read user-supplied files.
"""

import datetime
import math
import re
import tomllib
from enum import StrEnum
from importlib import resources
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from sugo.core.constants import MAX_FORMULA_VALUE

PositiveValue = Annotated[int, Field(ge=1, le=MAX_FORMULA_VALUE)]
TokenCount = Annotated[int, Field(ge=0, le=MAX_FORMULA_VALUE)]

# Provider names become file names, so only a strict identifier is accepted:
# no separators, dots or drive letters can reach the filesystem.
_PROVIDER_NAME = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_PROVIDERS_DIR = ("data", "providers")


class _Model(BaseModel):
    """Shared configuration: immutable, unknown keys rejected, no silent coercion."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class VerificationStatus(StrEnum):
    """Whether a formula was checked against the provider's own documentation."""

    VERIFIED = "verified"
    UNVERIFIED = "unverified"


class FormulaSource(_Model):
    """Where a formula comes from, so every reported number can be traced."""

    description: Annotated[str, Field(min_length=1)]
    checked: datetime.date
    # Strict mode accepts only enum instances from Python input; TOML gives strings.
    status: Annotated[VerificationStatus, Field(strict=False)]


def _scale_down(width: int, height: int, factor: float) -> tuple[int, int]:
    """Scale both sides by ``factor`` (at most 1), keeping each side at least 1 px."""
    return max(1, math.floor(width * factor)), max(1, math.floor(height * factor))


class PatchFormula(_Model):
    """Patch-based billing (Claude): one token per patch after a long-edge resize."""

    kind: Literal["patches"]
    patch_size: PositiveValue
    max_long_edge: PositiveValue
    max_tokens: PositiveValue

    def estimate(self, width: int, height: int) -> int:
        """Return the image tokens for an image of the given pixel size.

        The provider shrinks further when the patch count still exceeds the cap;
        capping the count gives the same result without guessing its rounding.
        """
        long_edge = max(width, height)
        if long_edge > self.max_long_edge:
            width, height = _scale_down(width, height, self.max_long_edge / long_edge)
        patches = math.ceil(width / self.patch_size) * math.ceil(height / self.patch_size)
        return min(patches, self.max_tokens)


class TileFormula(_Model):
    """Tile-based billing (Gemini, older OpenAI models): a fixed cost per tile."""

    kind: Literal["tiles"]
    tile_size: PositiveValue
    tokens_per_tile: PositiveValue
    base_tokens: TokenCount = 0
    # Images whose sides both fit within small_max_side cost small_tokens flat.
    small_max_side: PositiveValue | None = None
    small_tokens: TokenCount | None = None
    # Optional downscaling before tiling: fit inside a square, then shrink the
    # shortest side. Images are never scaled up.
    fit_within: PositiveValue | None = None
    shortest_side: PositiveValue | None = None

    @model_validator(mode="after")
    def _check_small_pair(self) -> Self:
        if (self.small_max_side is None) != (self.small_tokens is None):
            raise ValueError("small_max_side and small_tokens must be set together")
        return self

    def estimate(self, width: int, height: int) -> int:
        """Return the image tokens for an image of the given pixel size."""
        if (
            self.small_max_side is not None
            and self.small_tokens is not None
            and max(width, height) <= self.small_max_side
        ):
            return self.small_tokens
        if self.fit_within is not None and max(width, height) > self.fit_within:
            width, height = _scale_down(width, height, self.fit_within / max(width, height))
        if self.shortest_side is not None and min(width, height) > self.shortest_side:
            width, height = _scale_down(width, height, self.shortest_side / min(width, height))
        tiles = math.ceil(width / self.tile_size) * math.ceil(height / self.tile_size)
        return self.base_tokens + tiles * self.tokens_per_tile


ImageFormula = Annotated[PatchFormula | TileFormula, Field(discriminator="kind")]


class ProviderFormulas(_Model):
    """All billing tiers of one provider, as read from its data file."""

    schema_version: Literal[1]
    provider: Annotated[str, Field(pattern=_PROVIDER_NAME.pattern)]
    default_tier: Annotated[str, Field(min_length=1)]
    source: FormulaSource
    tiers: Annotated[dict[str, ImageFormula], Field(min_length=1)]

    @model_validator(mode="after")
    def _check_default_tier(self) -> Self:
        if self.default_tier not in self.tiers:
            raise ValueError(f"default_tier {self.default_tier!r} is not among the tiers")
        return self

    def estimate(self, width: int, height: int, tier: str | None = None) -> int:
        """Return the image tokens for an image, using ``tier`` or the default one.

        Raises:
            ValueError: If the size is not positive or the tier does not exist.
        """
        if width < 1 or height < 1:
            raise ValueError("image width and height must be positive")
        name = self.default_tier if tier is None else tier
        if name not in self.tiers:
            raise ValueError(f"unknown tier {name!r} for provider {self.provider!r}")
        return self.tiers[name].estimate(width, height)


def parse_provider(text: str) -> ProviderFormulas:
    """Parse and validate the TOML content of a provider formula file.

    Raises:
        tomllib.TOMLDecodeError: If the text is not valid TOML.
        pydantic.ValidationError: If the content does not match the schema.
    """
    # Python mode, not strict JSON mode: TOML already yields native dates and ints.
    return ProviderFormulas.model_validate(tomllib.loads(text))


def list_providers() -> list[str]:
    """Return the names of the bundled providers, sorted."""
    directory = resources.files("sugo").joinpath(*_PROVIDERS_DIR)
    return sorted(
        entry.name.removesuffix(".toml")
        for entry in directory.iterdir()
        if entry.name.endswith(".toml")
    )


def load_provider(name: str) -> ProviderFormulas:
    """Load a bundled provider's formulas by name, e.g. ``"claude"``.

    Raises:
        ValueError: If the name is malformed, unknown, or does not match the file.
    """
    if not _PROVIDER_NAME.fullmatch(name):
        raise ValueError(f"invalid provider name {name!r}")
    if name not in list_providers():
        raise ValueError(f"unknown provider {name!r}")
    text = resources.files("sugo").joinpath(*_PROVIDERS_DIR, f"{name}.toml").read_text("utf-8")
    formulas = parse_provider(text)
    if formulas.provider != name:
        raise ValueError(f"provider file {name!r} declares provider {formulas.provider!r}")
    return formulas
