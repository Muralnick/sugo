"""The two savings baselines of ADR-003: raw vs clean text, and image vs extracted text.

Savings are reported as percentages because tokenizers differ across LLMs. They
can be zero or negative (e.g. a small sparse screenshot sent to Gemini): Sugo
reports them honestly instead of hiding them.
"""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from sugo.metrics.providers import ProviderFormulas, VerificationStatus
from sugo.metrics.tokenizer import count_tokens

Tokens = Annotated[int, Field(ge=0)]


class Savings(BaseModel):
    """Tokens before and after, with the derived saving."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    baseline_tokens: Tokens
    result_tokens: Tokens

    @property
    def saved_tokens(self) -> int:
        """Tokens saved; negative when the result costs more than the baseline."""
        return self.baseline_tokens - self.result_tokens

    @property
    def saved_percent(self) -> float:
        """Saving as a percentage of the baseline; 0 when the baseline is empty."""
        if self.baseline_tokens == 0:
            return 0.0
        return 100.0 * self.saved_tokens / self.baseline_tokens


class ImageSavings(Savings):
    """Image baseline: what the provider would bill for the image itself."""

    provider: str
    tier: str
    formula_verified: bool


def text_savings(raw_text: str, clean_text: str) -> Savings:
    """Compare the tokens of the raw extracted text with the cleaned text."""
    return Savings(baseline_tokens=count_tokens(raw_text), result_tokens=count_tokens(clean_text))


def image_savings(
    width: int,
    height: int,
    markdown: str,
    formulas: ProviderFormulas,
    tier: str | None = None,
) -> ImageSavings:
    """Compare sending an image to a provider with sending its extracted Markdown.

    Args:
        width: Image width in pixels.
        height: Image height in pixels.
        markdown: Markdown extracted from the image.
        formulas: The provider's billing formulas.
        tier: Billing tier; the provider's default when omitted.

    Raises:
        ValueError: If the size is not positive or the tier does not exist.
    """
    tier_name = formulas.default_tier if tier is None else tier
    return ImageSavings(
        baseline_tokens=formulas.estimate(width, height, tier_name),
        result_tokens=count_tokens(markdown),
        provider=formulas.provider,
        tier=tier_name,
        formula_verified=formulas.source.status is VerificationStatus.VERIFIED,
    )
