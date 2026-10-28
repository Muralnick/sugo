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

# --- OCR (roadmap step 2b, ADR-039) -----------------------------------------

# SHA-256 of the PP-OCRv6 small models bundled in rapidocr 3.10.0, identical to
# the hashes in RapidOCR's own model registry (default_models.yaml). A mismatch
# means the installed file was altered.
PPOCRV6_DET_SMALL_SHA256: Final = "090f04abcd9d9a7498bc4ebf677e4cb9bdce1fe4197ddb7e529f1ef44e1ff94f"
PPOCRV6_REC_SMALL_SHA256: Final = "6f327246b50388f3c176ae304bd95767ea6dc0c9ae92153ef8cbe210b3c14884"

# The text detector shrinks images so their long side is at most this many
# pixels. RapidOCR's default instead enlarges every image to a 736 px short
# side, which made detection several times slower in the ADR-039 spike.
OCR_DETECTION_MAX_SIDE: Final = 960

# Recognition confidence (0-1) below which a line is treated as unreadable: it
# is kept as an illegible line without text, never guessed (principle 4). Same
# value as RapidOCR's own default filter, which Sugo disables because it drops
# lines silently. Initial value, to be calibrated (step 8).
OCR_MIN_CONFIDENCE: Final = 0.5

# --- Layout (roadmap step 2c) -----------------------------------------------
# Gaps are measured in median text-line heights, so the same rules work at any
# resolution and font size. Initial values, to be calibrated (step 8).

# A vertical gap larger than this separates two paragraphs: line spacing inside
# a paragraph is typically 0.2-0.6 line heights, a paragraph break 1 or more.
LAYOUT_PARAGRAPH_GAP: Final = 0.8

# A horizontal gap larger than this separates two columns: a column gutter is
# a few characters wide (about 1.5-3 line heights), a word space far less.
LAYOUT_COLUMN_GAP: Final = 1.5

# Two boxes are on the same text row when their vertical overlap exceeds this
# share of the shorter box's height.
LAYOUT_SAME_ROW_OVERLAP: Final = 0.5

# --- Screenshot detectors (roadmap step 3a) ----------------------------------
# Conservative on purpose: leaving noise costs a few tokens, removing content
# breaks principle 3. Initial values, to be calibrated (step 8).

# Share of the screenshot height at the top and bottom where status bars,
# navigation bars and icon rows live. A phone status bar is about 5% of the
# height (140 of 2532 px on an iPhone), a desktop menu bar about 2-3%.
UI_CHROME_EDGE_BAND: Final = 0.06

# Longest text treated as an icon misread by OCR (e.g. "Q", "<", "@") when it
# sits alone in an edge band.
UI_CHROME_ICON_MAX_CHARS: Final = 2

# A chat bubble is left-aligned when its text starts within this share of the
# width from the left edge and ends before the same margin from the right edge;
# right-aligned symmetrically. Centred or full-width text is neither.
CHAT_SIDE_MARGIN: Final = 0.15

# A screenshot is a chat when it has at least this many aligned bubbles, on
# both sides, making up at least this share of its text blocks.
CHAT_MIN_MESSAGES: Final = 3
CHAT_MIN_ALIGNED_SHARE: Final = 0.6

# A text block is code when at least this share of its rows shows code syntax
# (keywords, brackets, operators at the end or start of the row).
CODE_MIN_SIGNAL_SHARE: Final = 0.5
# ...and at least this many rows: a one-row heading ending with ":" must never
# become code.
CODE_MIN_SIGNAL_ROWS: Final = 2
