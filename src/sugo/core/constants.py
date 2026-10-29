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

# --- Markdown serializer (roadmap step 4, ADR-042) --------------------------

# CommonMark code fences are at least three backticks, and must be longer than
# any backtick run inside the code, or the code would close its own fence.
MARKDOWN_MIN_FENCE: Final = 3

# Continuation lines of list items and chat messages are indented by this many
# spaces, so a line such as "right: I agree" inside a left bubble cannot be
# read as a new message. Two spaces keep a list item's continuation inside it.
MARKDOWN_CONTINUATION_INDENT: Final = 2

# A line indented by up to three spaces can still open Markdown structure
# (heading, list, quote); four or more make an indented code block instead.
MARKDOWN_MAX_STRUCTURE_INDENT: Final = 3

# CommonMark expands a tab in indentation to the next multiple of four columns.
MARKDOWN_TAB_STOP: Final = 4

# --- PDF extractor (roadmap step 5a, ADR-043) --------------------------------

# Largest PDF file read into memory. Scanned books reach a few hundred MB, but
# v0.1 targets native documents; bigger files are refused before parsing.
MAX_PDF_FILE_BYTES: Final = 200 * 1024 * 1024

# Most pages read from one PDF. A long book has about 1 000 pages; a file
# declaring far more is a mistake or an attack on time and memory.
MAX_PDF_PAGES: Final = 5_000

# Address space of the PDF worker process (Linux and macOS). MuPDF needs a few
# hundred MB on large pages; a hostile file that asks for more is stopped by
# the operating system instead of slowing the whole machine (ADR-018).
PDF_WORKER_MEMORY_BYTES: Final = 1536 * 1024 * 1024

# Seconds the worker may take to open and check a document, and to return one
# page. Native pages take milliseconds; a page that takes longer is hostile or
# broken, and the worker is killed (ARCHITECTURE §4, error handling).
PDF_OPEN_TIMEOUT_S: Final = 60.0
PDF_PAGE_TIMEOUT_S: Final = 30.0

# Times the worker is restarted after a page kills or stalls it. Each failed
# page is marked illegible; beyond this many the document is refused, since
# the file is evidently built to crash the parser.
PDF_MAX_WORKER_RESTARTS: Final = 3

# Largest message the worker may send: a page rendered for OCR at the limits
# below, plus room for its header. Anything bigger is a broken worker.
PDF_MAX_MESSAGE_BYTES: Final = 64 * 1024 * 1024

# Resolution used to check whether text is visible: 72 DPI renders an A4 page
# in a few milliseconds and keeps 6 pt text a few pixels high.
PDF_VISIBILITY_DPI: Final = 72

# Text smaller than this many points cannot be read on a printed page; it is
# a classic way to hide instructions from people but not from LLMs.
PDF_MIN_VISIBLE_FONT_SIZE: Final = 2.0

# Colour distance (0-255, largest channel difference) under which text is
# considered the same colour as the page behind it: white on white, or text
# under an opaque shape. Anti-aliased small text still differs by 60 or more.
PDF_MIN_TEXT_CONTRAST: Final = 32

# Pages are read with OCR when images cover at least this share of the page
# and less than this many characters of visible text exist: a scan, possibly
# with a stamp or page number in native text.
PDF_SCAN_MIN_IMAGE_COVERAGE: Final = 0.5
PDF_SCAN_MAX_VISIBLE_CHARS: Final = 20

# Resolution used to render scanned pages for OCR (ADR-018 adaptive DPI: an
# A4 page at 200 DPI is about 12 MB), lowered when a page is large so the
# image never exceeds the pixel limit below.
PDF_OCR_DPI: Final = 200
PDF_OCR_MAX_PIXELS: Final = 20_000_000

# A text block is a heading when its font is at least this many times the
# page's body text size. Initial value, to be calibrated (step 8).
PDF_HEADING_MIN_SIZE_RATIO: Final = 1.2
# ...and it has at most this many lines: a large-print paragraph is not a heading.
PDF_HEADING_MAX_LINES: Final = 3

# --- Headers, footers and page numbers (roadmap step 5b, ADR-044) ------------
# Conservative on purpose: a running header left in costs a few tokens, a
# clause removed by mistake breaks principle 3 (THREAT_MODEL C). Initial
# values, to be calibrated on the benchmark corpus (step 8).

# Share of the page height at the top and bottom where running headers,
# footers and page numbers live. A4 margins are about 70 pt of 842 (8%).
PAGE_EDGE_BAND: Final = 0.1

# Most blocks per page and band the analyzer considers. Real pages have one
# to three; the cap bounds memory on hostile pages with thousands of blocks.
MAX_EDGE_BLOCKS_PER_BAND: Final = 8

# Text repeated on fewer pages than this is never treated as a running
# header or footer: two matches can be chance, three rarely are.
REPEAT_MIN_PAGES: Final = 3

# ...and the repeats must cover at least this share of the pages between the
# first and the last one. A header printed on every other page (left and
# right pages differ) covers 50%; a heading that happens to recur at the top
# of three pages far apart covers almost nothing.
REPEAT_MIN_DENSITY: Final = 0.4

# Repeated edge text with at least this many words is substantive: it may be
# a clause, not boilerplate, so its first copy is kept (THREAT_MODEL C).
# "Payment is due within 30 days" has 6 words; "Confidential" or "Annual
# Report 2026" are clearly boilerplate.
SUBSTANTIVE_MIN_WORDS: Final = 6
# ...or this many visible characters, for scripts written without spaces
# (Thai, Khmer) and text spaced with characters that only look blank. A
# 6-word English clause has about 30.
SUBSTANTIVE_MIN_CHARS: Final = 40

# Longest block read as page furniture. Running headers and footers are a
# line or two; longer text is a paragraph and stays.
MAX_EDGE_TEXT_CHARS: Final = 300

# Longest edge text read as a page number, e.g. "Page 1234 of 5000" or
# "- xii -". Longer text is a sentence, never a page number.
PAGE_NUMBER_MAX_CHARS: Final = 30

# Digit runs longer than this are never page numbers (MAX_PDF_PAGES has four
# digits) and are compared as text, not converted to integers.
PAGE_NUMBER_MAX_DIGITS: Final = 6
# --- Page cache (roadmap step 5c, ADR-045) -----------------------------------

# Default size limit of the page cache; least recently used pages go first.
# A 300-page book takes about 2 MB of compressed page records, so 2 GB keeps
# hundreds of books, while staying small next to the models (ADR-019).
CACHE_MAX_BYTES: Final = 2 * 1024 * 1024 * 1024

# When the limit is passed, eviction goes down to this share of it, so the
# next few pages do not each trigger another eviction.
CACHE_EVICT_TO_SHARE: Final = 0.9

# Pages are not cached when less free disk space than this would remain: the
# cache is optional, and filling the disk would break the user's other work.
CACHE_MIN_FREE_BYTES: Final = 512 * 1024 * 1024

# Largest decompressed page record read back from the cache, the same bound
# as a PDF worker frame. A bigger record is corrupt or forged and is dropped.
CACHE_MAX_RECORD_BYTES: Final = 64 * 1024 * 1024

# Seconds a process waits for another one writing to the same cache, e.g.
# two CLI commands run at once, before giving up on that cache operation.
CACHE_BUSY_TIMEOUT_S: Final = 5.0

# Pages used in the last day are never evicted, even past the size limit: a
# running job, here or in another process, must find its own pages again in
# its later passes (the page store, ADR-006). The limit is soft for them.
CACHE_PROTECT_RECENT_S: Final = 24 * 3600

# A cache hit refreshes the page's last use only if older than this, so
# reading a cached document does not take the write lock once per page.
# Far below CACHE_PROTECT_RECENT_S, so a page in use is always protected.
CACHE_TOUCH_INTERVAL_S: Final = 600

# The write-ahead log is cut back to this size after each checkpoint, so it
# does not keep the space of a large job once the job is done.
CACHE_WAL_LIMIT_BYTES: Final = 64 * 1024 * 1024

# --- Chunks (roadmap step 6, ADR-047) ----------------------------------------

# Default chunk size in o200k_base tokens. 512 suits most embedding models
# (many are trained on 512-token passages) and keeps a retrieved chunk cheap
# to put in a prompt (ARCHITECTURE §14, [chunking] max_tokens).
CHUNK_MAX_TOKENS: Final = 512

# Smallest chunk size accepted: below this, a heading and one sentence no
# longer fit, and chunks lose their meaning.
CHUNK_MIN_TOKENS: Final = 32

# Hex digits of the chunk and document ids: 128 bits, so collisions stay
# negligible even across billions of chunks in one vector database.
OUTPUT_ID_HEX_DIGITS: Final = 32

# --- MCP server (roadmap step 7b, ADR-049) -------------------------------------

# Tokens per tool response. 8 000 leaves room in an agent's context for its
# own work; 20 000 stays below the 25 000-token output cap of common clients
# (Claude Code); 1 024 always fits one 512-token chunk record and its fields.
MCP_DEFAULT_TOKENS: Final = 8_000
MCP_MIN_TOKENS: Final = 1_024
MCP_MAX_TOKENS: Final = 20_000

# Tokens reserved in each response for the wrapper and the metadata around the
# document text, so the whole response stays within the budget.
MCP_WRAPPER_TOKENS: Final = 200

# Largest JSON-RPC message accepted on stdin. Tool arguments are a path and a
# few options; anything near this size is malformed or hostile.
MCP_MAX_MESSAGE_BYTES: Final = 1_000_000

# Longest path and cursor accepted in tool arguments.
MCP_MAX_PATH_CHARS: Final = 4_096
MCP_MAX_CURSOR_CHARS: Final = 512

# Hex digits of the content hash that labels a response's document wrapper.
MCP_WRAPPER_ID_HEX_DIGITS: Final = 12

# Never readable through MCP, whatever the allowed roots (principle 7,
# THREAT_MODEL D): folders and files holding keys, tokens and passwords.
# Compared case-insensitively with every component of the resolved path.
MCP_EXCLUDED_DIRS: Final = frozenset(
    {".ssh", ".gnupg", ".aws", ".azure", ".kube", ".docker", ".password-store", "keyrings"}
)
MCP_EXCLUDED_FILES: Final = frozenset({".netrc", ".pgpass", ".env"})
MCP_EXCLUDED_PATTERNS: Final = (
    "id_rsa*",
    "id_dsa*",
    "id_ecdsa*",
    "id_ed25519*",
    ".env.*",
    "*.kdbx",
    "*.pem",
)
