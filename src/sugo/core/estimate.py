"""Estimate what converting one document saves: the two baselines of ADR-003.

The text baseline compares the extracted text before and after cleaning. The
image baseline, for images only, compares what each provider would bill for
the image itself with the tokens of the Markdown Sugo made from it. Every
port (CLI ``sugo stats``, MCP ``estimate_savings``) uses this one operation.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from sugo.core.pipeline import Conversion, InputKind
from sugo.extractors.image.loader import decode_image
from sugo.metrics.baselines import ImageSavings, Savings
from sugo.metrics.providers import ImageRejectedError, VerificationStatus, load_provider
from sugo.metrics.tokenizer import count_tokens


@dataclass(frozen=True)
class SavingsEstimate:
    """Both baselines for one converted document."""

    kind: InputKind
    pages: int
    # Raw extracted text against the cleaned Markdown.
    text: Savings
    # The image against its Markdown, per provider; empty for PDFs.
    images: tuple[ImageSavings, ...]
    # Providers that would refuse the image instead of billing it.
    rejected_by: tuple[str, ...]


def estimate_savings(
    data: bytes, conversion: Conversion, providers: Sequence[str]
) -> SavingsEstimate:
    """Measure a conversion against both baselines.

    Args:
        data: The converted file's content.
        conversion: Its conversion, made with ``count_raw_tokens=True``.
        providers: Names of the bundled providers to compare, e.g. ``["claude"]``.

    Raises:
        ValueError: If the raw tokens were not counted or a provider is unknown.
        sugo.extractors.image.loader.ImageLoadError: If the image cannot be decoded.
    """
    if conversion.raw_tokens is None:
        raise ValueError("the conversion did not count its raw tokens")
    formulas = [load_provider(name) for name in providers]
    markdown_tokens = count_tokens(conversion.markdown)
    images: list[ImageSavings] = []
    rejected: list[str] = []
    if conversion.kind is InputKind.IMAGE:
        image = decode_image(data)
        for provider in formulas:
            try:
                image_tokens = provider.estimate(image.width, image.height)
            except ImageRejectedError:
                rejected.append(provider.provider)
                continue
            images.append(
                ImageSavings(
                    baseline_tokens=image_tokens,
                    result_tokens=markdown_tokens,
                    provider=provider.provider,
                    tier=provider.default_tier,
                    formula_verified=provider.source.status is VerificationStatus.VERIFIED,
                )
            )
    return SavingsEstimate(
        kind=conversion.kind,
        pages=conversion.pages,
        text=Savings(baseline_tokens=conversion.raw_tokens, result_tokens=markdown_tokens),
        images=tuple(images),
        rejected_by=tuple(rejected),
    )
