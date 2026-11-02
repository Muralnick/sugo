"""Tests for the savings estimate: text baseline for every input, image baseline per provider."""

from io import BytesIO
from types import MappingProxyType

import pytest
from PIL import Image

from sugo.core.estimate import estimate_savings
from sugo.core.pipeline import Conversion, InputKind
from sugo.metrics.providers import ImageRejectedError, ProviderFormulas, load_provider
from sugo.metrics.tokenizer import count_tokens

MARKDOWN = "Meeting at 10:30 tomorrow\n\nBring the signed contract."


def png(width: int = 900, height: int = 300) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (width, height), "white").save(buffer, format="PNG")
    return buffer.getvalue()


def conversion(kind: InputKind, raw_tokens: int | None = 40) -> Conversion:
    return Conversion(
        markdown=MARKDOWN,
        kind=kind,
        source="note.png",
        source_sha256="a" * 64,
        pages=1,
        failed_pages=(),
        removed=MappingProxyType({}),
        chunks=(),
        sugo_version="0.0.0",
        config_hash="b" * 64,
        raw_tokens=raw_tokens,
    )


def test_image_is_compared_with_each_provider() -> None:
    estimate = estimate_savings(png(), conversion(InputKind.IMAGE), ["claude", "gemini"])
    tokens = count_tokens(MARKDOWN)
    assert estimate.text.baseline_tokens == 40
    assert estimate.text.result_tokens == tokens
    assert [image.provider for image in estimate.images] == ["claude", "gemini"]
    claude = load_provider("claude")
    assert estimate.images[0].baseline_tokens == claude.estimate(900, 300)
    assert estimate.images[0].tier == claude.default_tier
    assert all(image.result_tokens == tokens for image in estimate.images)
    assert estimate.rejected_by == ()


def test_pdf_has_only_the_text_baseline() -> None:
    estimate = estimate_savings(b"%PDF-1.7", conversion(InputKind.PDF), ["claude"])
    assert estimate.images == ()
    assert estimate.text.saved_tokens == 40 - count_tokens(MARKDOWN)


def test_provider_that_refuses_the_image_is_listed(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(self: ProviderFormulas, width: int, height: int, tier: str | None = None) -> int:
        raise ImageRejectedError("too large")

    monkeypatch.setattr(ProviderFormulas, "estimate", refuse)
    estimate = estimate_savings(png(), conversion(InputKind.IMAGE), ["openai"])
    assert (estimate.images, estimate.rejected_by) == ((), ("openai",))


def test_raw_tokens_are_required() -> None:
    with pytest.raises(ValueError, match="raw tokens"):
        estimate_savings(png(), conversion(InputKind.IMAGE, raw_tokens=None), ["claude"])


def test_unknown_provider_is_refused() -> None:
    with pytest.raises(ValueError, match="unknown provider"):
        estimate_savings(png(), conversion(InputKind.IMAGE), ["nobody"])
