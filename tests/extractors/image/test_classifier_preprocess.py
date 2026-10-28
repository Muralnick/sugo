"""Tests for the image classifier and preprocessing."""

from collections.abc import Callable

import numpy as np
import pytest
from PIL import Image

from sugo.extractors.image.classifier import ImageKind, classify
from sugo.extractors.image.loader import LoadedImage, decode_image
from sugo.extractors.image.preprocess import preprocess

Encode = Callable[..., bytes]
Screenshot = Callable[..., Image.Image]


def load(encode: Encode, image: Image.Image, image_format: str = "PNG") -> LoadedImage:
    return decode_image(encode(image, image_format))


def photo_like(size: tuple[int, int] = (800, 600)) -> Image.Image:
    # Camera-like content: a gradient with sensor noise, no flat areas.
    rng = np.random.default_rng(seed=7)
    x = np.linspace(0, 200, size[0])
    y = np.linspace(0, 55, size[1])[:, None]
    base = (x + y)[..., None] + rng.normal(0, 12, (size[1], size[0], 3))
    return Image.fromarray(np.clip(base, 0, 255).astype(np.uint8))


class TestClassifier:
    @pytest.mark.parametrize("colour", ["white", "black", "#808080"])
    def test_flat_images_are_blank(self, encode: Encode, colour: str) -> None:
        result = classify(load(encode, Image.new("RGB", (640, 480), colour)))
        assert result.kind is ImageKind.BLANK
        assert not result.dark_mode

    def test_light_screenshot(self, encode: Encode, screenshot: Screenshot) -> None:
        result = classify(load(encode, screenshot()))
        assert result.kind is ImageKind.SCREENSHOT
        assert not result.dark_mode

    def test_dark_mode_screenshot(self, encode: Encode, screenshot: Screenshot) -> None:
        result = classify(load(encode, screenshot(dark=True)))
        assert result.kind is ImageKind.SCREENSHOT
        assert result.dark_mode

    def test_jpeg_compressed_screenshot_is_still_a_screenshot(
        self, encode: Encode, screenshot: Screenshot
    ) -> None:
        result = classify(load(encode, screenshot(), "JPEG"))
        assert result.kind is ImageKind.SCREENSHOT

    def test_camera_photo(self, encode: Encode) -> None:
        assert classify(load(encode, photo_like(), "JPEG")).kind is ImageKind.PHOTO

    def test_is_deterministic(self, encode: Encode) -> None:
        image = load(encode, photo_like(), "JPEG")
        assert classify(image) == classify(image)


class TestPreprocess:
    def test_dark_mode_is_inverted_without_touching_the_original(
        self, encode: Encode, screenshot: Screenshot
    ) -> None:
        image = load(encode, screenshot(dark=True))
        original = image.pixels.copy()
        prepared = preprocess(image, classify(image))
        assert prepared.inverted
        assert np.array_equal(prepared.pixels, 255 - original)
        assert np.array_equal(image.pixels, original)

    def test_light_screenshot_is_left_as_is(self, encode: Encode, screenshot: Screenshot) -> None:
        image = load(encode, screenshot())
        prepared = preprocess(image, classify(image))
        assert (prepared.inverted, prepared.scale) == (False, 1)
        assert np.array_equal(prepared.pixels, image.pixels)

    def test_small_image_is_upscaled(self, encode: Encode, screenshot: Screenshot) -> None:
        image = load(encode, screenshot(size=(300, 200)))
        prepared = preprocess(image, classify(image))
        assert prepared.scale == 2
        assert prepared.pixels.shape == (400, 600, 3)

    def test_upscaling_keeps_normalised_positions(self, encode: Encode) -> None:
        # A dark square at 25-50 % of the width must stay there after upscaling.
        source = Image.new("RGB", (200, 100), "white")
        source.paste((0, 0, 0), (50, 25, 100, 50))
        image = load(encode, source)
        prepared = preprocess(image, classify(image))
        dark = np.argwhere(prepared.pixels[..., 0] < 128)
        height, width = prepared.pixels.shape[:2]
        assert dark[:, 1].min() / width == pytest.approx(0.25, abs=0.01)
        assert (dark[:, 1].max() + 1) / width == pytest.approx(0.50, abs=0.01)
        assert dark[:, 0].min() / height == pytest.approx(0.25, abs=0.01)

    def test_result_is_read_only(self, encode: Encode, screenshot: Screenshot) -> None:
        image = load(encode, screenshot(dark=True))
        with pytest.raises(ValueError, match="read-only"):
            preprocess(image, classify(image)).pixels[0, 0, 0] = 0
