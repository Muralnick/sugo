"""Classify an image before OCR: screenshot, camera photo, or blank.

The classifier is cheap and runs on a small thumbnail, so blank images are
skipped before any model is loaded, and preprocessing knows whether a
screenshot is in dark mode. It only looks at pixel statistics; whether an image
actually contains text is decided later by the OCR detector.

All thresholds live in ``sugo.core.constants`` and are initial values, to be
calibrated on the benchmark corpus (roadmap step 8).
"""

from dataclasses import dataclass
from enum import StrEnum

import numpy as np
from PIL import Image

from sugo.core.constants import (
    BLANK_LUMINANCE_STDDEV,
    CLASSIFIER_SAMPLE_SIDE,
    DARK_MODE_MEDIAN_LUMINANCE,
    SCREENSHOT_TOP_COLOURS,
    SCREENSHOT_TOP_COLOURS_SHARE,
)
from sugo.extractors.image.loader import LoadedImage

# Colours are compared at 5 bits per channel, so JPEG noise on a flat UI
# background still counts as one colour.
_COLOUR_BITS_DROPPED = 3


class ImageKind(StrEnum):
    """What kind of image this is, as far as pixel statistics can tell."""

    SCREENSHOT = "screenshot"
    PHOTO = "photo"
    BLANK = "blank"


@dataclass(frozen=True)
class Classification:
    """Classifier verdict with the statistics behind it, for explanations and tuning."""

    kind: ImageKind
    dark_mode: bool
    luminance_stddev: float
    median_luminance: float
    top_colours_share: float


def classify(image: LoadedImage) -> Classification:
    """Classify an image from a thumbnail of its pixels. Deterministic."""
    thumbnail = Image.fromarray(image.pixels)
    # Nearest-neighbour sampling keeps real pixel colours instead of blending them.
    thumbnail.thumbnail((CLASSIFIER_SAMPLE_SIDE, CLASSIFIER_SAMPLE_SIDE), Image.Resampling.NEAREST)
    luminance = np.asarray(thumbnail.convert("L"), dtype=np.float64)
    stddev = float(luminance.std())
    median = float(np.median(luminance))
    share = _top_colours_share(np.asarray(thumbnail, dtype=np.uint8))

    if stddev < BLANK_LUMINANCE_STDDEV:
        kind = ImageKind.BLANK
    elif share >= SCREENSHOT_TOP_COLOURS_SHARE:
        kind = ImageKind.SCREENSHOT
    else:
        kind = ImageKind.PHOTO
    return Classification(
        kind=kind,
        dark_mode=kind is not ImageKind.BLANK and median < DARK_MODE_MEDIAN_LUMINANCE,
        luminance_stddev=stddev,
        median_luminance=median,
        top_colours_share=share,
    )


def _top_colours_share(rgb: np.ndarray) -> float:
    """Share of pixels covered by the most common (coarsened) colours."""
    coarse = (rgb >> _COLOUR_BITS_DROPPED).reshape(-1, 3)
    _, counts = np.unique(coarse, axis=0, return_counts=True)
    top = np.sort(counts)[::-1][:SCREENSHOT_TOP_COLOURS]
    return float(top.sum() / coarse.shape[0])
