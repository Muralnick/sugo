"""Thresholds and limits used by the core, each with the reason for its value."""

from typing import Final

# Markdown has six heading levels (`#` to `######`); deeper levels cannot be rendered.
MAX_HEADING_LEVEL: Final = 6

# Pages are rotated in quarter turns by PDF viewers and image EXIF orientation alike.
PAGE_ROTATIONS: Final = frozenset({0, 90, 180, 270})

# A SHA-256 digest is 32 bytes, written as 64 hexadecimal characters.
SHA256_HEX_LENGTH: Final = 64

# SHA-256 of the bundled o200k_base vocabulary, as pinned by tiktoken itself
# (tiktoken_ext/openai_public.py); a mismatch means the file was altered (ADR-038).
O200K_BASE_SHA256: Final = "446a9538cb6c348e3516120d7c08b09f57c36495e2acfffe59a5bf8b0cfb1a2d"

# Upper bound for any pixel size or token count in a provider formula file. Real
# values stay below 10 000; anything larger is a typo or a hostile file.
MAX_FORMULA_VALUE: Final = 100_000

# --- Images (roadmap step 2) ------------------------------------------------

# Largest image file read into memory. An 8K PNG screenshot is about 30 MB and
# a 48-megapixel phone JPEG about 15 MB; anything bigger is not a screenshot or
# page photo and is refused before decoding.
MAX_IMAGE_FILE_BYTES: Final = 50 * 1024 * 1024

# Largest decoded image, checked from the header before any pixel is decoded
# (decompression bombs). 50 megapixels covers 48 MP phone cameras; as 8-bit RGB
# it takes 150 MB, well inside the 1 GB budget of the lite level.
MAX_IMAGE_PIXELS: Final = 50_000_000

# Long side of the thumbnail used by the classifier: enough to see backgrounds
# and colour statistics, small enough to cost a few milliseconds.
CLASSIFIER_SAMPLE_SIDE: Final = 256

# Standard deviation of luminance (0-255) below which an image is treated as
# blank. JPEG noise on a flat area stays around 1; one line of text exceeds 5.
# Initial value, to be calibrated on the benchmark corpus (roadmap step 8).
BLANK_LUMINANCE_STDDEV: Final = 2.0

# Share of thumbnail pixels covered by the most common colours above which an
# image looks like a rendered screen (flat UI backgrounds) rather than a camera
# photo (noise and gradients). Initial value, to be calibrated (step 8).
SCREENSHOT_TOP_COLOURS: Final = 8
SCREENSHOT_TOP_COLOURS_SHARE: Final = 0.5

# Median luminance (0-255) below which a screenshot is in dark mode: the
# background, which covers most pixels, is darker than mid-grey.
DARK_MODE_MEDIAN_LUMINANCE: Final = 128

# Images whose long side is below this many pixels are upscaled before OCR, so
# small UI fonts reach the size the recogniser was trained on. Initial value,
# to be calibrated (step 8).
SMALL_IMAGE_LONG_SIDE: Final = 600
SMALL_IMAGE_UPSCALE: Final = 2
