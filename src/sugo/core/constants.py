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
