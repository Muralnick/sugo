"""Prepare image pixels for OCR: dark-mode inversion and upscaling of small images.

Both steps are uniform over the whole image (a colour inversion and a scale by
an integer factor), so coordinates normalised to 0-1 (ADR-005) mean the same
thing before and after: OCR boxes need no mapping back to the original.

The original pixels are never modified; a new array is returned.
"""

from dataclasses import dataclass

import numpy as np
from PIL import Image

from sugo.core.constants import SMALL_IMAGE_LONG_SIDE, SMALL_IMAGE_UPSCALE
from sugo.extractors.image.classifier import Classification
from sugo.extractors.image.loader import LoadedImage, RgbArray

_MAX_CHANNEL = 255


@dataclass(frozen=True)
class PreparedImage:
    """Pixels ready for OCR, with the steps applied so they can be explained."""

    pixels: RgbArray
    inverted: bool
    scale: int


def preprocess(image: LoadedImage, classification: Classification) -> PreparedImage:
    """Apply the preprocessing steps the classification calls for. Deterministic."""
    pixels = image.pixels
    inverted = classification.dark_mode
    if inverted:
        # OCR models are trained on dark text on light backgrounds.
        pixels = (_MAX_CHANNEL - pixels).astype(np.uint8)

    scale = 1
    if max(image.width, image.height) < SMALL_IMAGE_LONG_SIDE:
        scale = SMALL_IMAGE_UPSCALE
        upscaled = Image.fromarray(pixels).resize(
            (image.width * scale, image.height * scale), Image.Resampling.BICUBIC
        )
        pixels = np.asarray(upscaled, dtype=np.uint8)

    result = pixels.copy() if pixels is image.pixels else pixels
    result.setflags(write=False)
    return PreparedImage(pixels=result, inverted=inverted, scale=scale)
