"""Thresholds and limits used by the core, each with the reason for its value."""

from types import MappingProxyType
from typing import Final

# The PyPI distribution name, for `importlib.metadata.version()` and install
# hints: "sugo" itself is squatted on PyPI (ADR-033 amendment, 2026-11-03),
# so the published distribution is "sugo-cli" while the package stays `sugo`
# and the command stays `sugo`. The one place to change if that ever flips.
DISTRIBUTION_NAME: Final = "sugo-cli"

# Markdown has six heading levels (`#` to `######`); deeper levels cannot be rendered.
MAX_HEADING_LEVEL: Final = 6

# List levels count from 0, the outermost; PowerPoint has nine (0-8), and so
# does Word's numbering.
MAX_LIST_LEVEL: Final = 8

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

# Handwriting in scans (ADR-063): an OCR line at least this many times taller
# than the page's typical text line, read with less than this confidence, is
# a pen stroke such as a signature, never text. The typical height is the
# median weighted by characters, so long body lines set it, not short logo
# words. Measured on 2026-11-07 (benchmarks/handwriting.py and one real
# signed scan): signatures read as words were 1.6 to 2.6 times taller and
# read with at most 0.92 confidence; typed lines read below 0.95 were at most
# 1.1 times taller, and taller typed headings were read with at least 0.99.
HANDWRITING_MIN_HEIGHT_RATIO: Final = 1.6
HANDWRITING_MAX_CONFIDENCE: Final = 0.95

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

# Two text rows whose heights differ by at least this factor are never one
# paragraph on a document page (ADR-064): a letterhead's small captions
# touching the body below them. Measured on a real scanned record
# (2026-11-07): letterhead to body 1.6 to 1.9; adjacent body rows mostly
# below 1.25. Screenshots are exempt: a chat message and its small timestamp
# are one bubble.
LAYOUT_SIZE_SPLIT_RATIO: Final = 1.5
# Rows with fewer readable characters are not measured: a short row's box
# depends on its letters (ascenders, descenders), not on its type size.
LAYOUT_SIZE_MIN_CHARS: Final = 25

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

# Opacity (0-255) under which text drawn over other text is hidden: at 1%
# opacity over a visible paragraph it reads as that paragraph's pixels
# (security review F3, 2026-11-02). Faint text over nothing else is judged
# by the rendered page, so outlined text with an opaque stroke stays visible.
PDF_MIN_TEXT_ALPHA: Final = 64

# Share of a text span's box that must change on the rendered page when the
# page's text is removed. Text that changes nothing is hidden: under an
# opaque shape, the colour of what it covers, or almost transparent (F3).
# Measured 2026-11-07: visible text changes 20 to 35% of its box.
PDF_MIN_VISIBLE_SHARE: Final = 0.02

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

# --- Office and XML reader (ADR-054) -----------------------------------------

# Largest XML file read. The whole tree is held in the worker's memory, about
# ten times the file's size; a larger file is refused before parsing.
MAX_XML_FILE_BYTES: Final = 50 * 1024 * 1024

# Largest receipt read by sugo verify and the web UI: a receipt holds at most
# the text of a document, as large as an XML file may be (ADR-056, ADR-059).
MAX_RECEIPT_BYTES: Final = MAX_XML_FILE_BYTES

# Deepest nesting and most elements in one XML file. Real data files nest a
# dozen levels; deeper or larger files are attacks on time and memory.
XML_MAX_DEPTH: Final = 256
XML_MAX_ELEMENTS: Final = 1_000_000

# Bytes looked at to recognise XML by its content, after a byte order mark.
XML_SNIFF_BYTES: Final = 1024

# Sibling records with the same simple fields (invoice lines, rows of an
# export) become a table from this many on; fewer read better as an outline.
XML_MIN_TABLE_RECORDS: Final = 3

# Rows in one table block; longer tables are split, the header repeated, so a
# chunk never has to hold an unbounded table (ADR-047).
OFFICE_TABLE_MAX_ROWS: Final = 200

# Attributes of the XML Schema instance namespace that only point at schemas.
XML_SCHEMA_INSTANCE_NS: Final = "http://www.w3.org/2001/XMLSchema-instance"
XML_SCHEMA_LOCATION_ATTRIBUTES: Final = frozenset({"schemalocation", "nonamespaceschemalocation"})

# Element and attribute names that hold credentials, compared without namespace,
# casefolded, without "-", "_" and ".". Their blocks are flagged ``secret`` and
# never sent to an agent (ADR-053). Bare "token" and "key" are too common.
XML_CREDENTIAL_NAMES: Final = frozenset(
    {
        "password",
        "passwd",
        "pwd",
        "cpassword",
        "passphrase",
        "secret",
        "clientsecret",
        "sharedsecret",
        "apikey",
        "accesskey",
        "secretkey",
        "privatekey",
        "accesstoken",
        "refreshtoken",
        "authtoken",
        "apitoken",
        "bearertoken",
        "connectionstring",
        # Wi-Fi profiles exported with netsh (key=clear).
        "keymaterial",
        "sharedkey",
        "presharedkey",
    }
)

# Words that mark a credential anywhere in a name split at case changes and
# separators: "AdministratorPassword", "userPWD", FileZilla's <Pass>,
# "clientSecret" (security review F8, 2026-11-02). "secretary" or "passport"
# are single words and do not match.
XML_CREDENTIAL_WORDS: Final = frozenset(
    {"password", "passwd", "pwd", "pass", "passphrase", "secret", "psk"}
)

# Names of the element or attribute that names a value in key/value formats:
# KeePass <Key>Password</Key>, .NET <add key="DbPassword" value=…>, Java
# <entry key="db.password">, <setting name="ApiKey">. A credential name as
# their value flags the block (F8).
XML_KEY_NAMES: Final = frozenset({"key", "name"})

# Largest Office file read, as for PDF; Office files are ZIP archives of XML parts.
MAX_OFFICE_FILE_BYTES: Final = 200 * 1024 * 1024

# ZIP limits against archive bombs: entries, bytes of one part and of all parts
# read, counted while decompressing (sizes in the archive are not trusted), and
# the compression ratio of parts over a megabyte. XML compresses about 10:1.
OFFICE_MAX_ENTRIES: Final = 10_000
OFFICE_MAX_PART_BYTES: Final = 50 * 1024 * 1024
OFFICE_MAX_TOTAL_BYTES: Final = 300 * 1024 * 1024
OFFICE_MAX_RATIO: Final = 200
OFFICE_RATIO_MIN_BYTES: Final = 1024 * 1024

# Most XML elements in one Office part: a 500-page report has about half a million.
OFFICE_MAX_PART_ELEMENTS: Final = 2_000_000

# Bytes of [Content_Types].xml searched to recognise a Word document. The file
# lists a few dozen parts; a larger one is not a document Sugo reads.
OFFICE_MAX_CONTENT_TYPES_BYTES: Final = 1024 * 1024

# Namespaces Office understands when it chooses among alternate content
# (mc:AlternateContent, ISO/IEC 29500-3): it shows the first mc:Choice whose
# Requires names only namespaces it knows, else the mc:Fallback. The readers
# choose the same way, so a Choice requiring a made-up namespace, which Office
# never shows, is never read either. Office's own extension namespaces that
# documents put in Requires; one missing here makes the readers take the
# Fallback where Office shows the Choice (ADR-054, residual risks).
OFFICE_UNDERSTOOD_NAMESPACES: Final = frozenset(
    {
        # The standard's own, transitional and strict, and VML.
        "http://schemas.openxmlformats.org/markup-compatibility/2006",
        "http://schemas.openxmlformats.org/presentationml/2006/main",
        "http://purl.oclc.org/ooxml/presentationml/main",
        "http://schemas.openxmlformats.org/drawingml/2006/main",
        "http://purl.oclc.org/ooxml/drawingml/main",
        "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
        "http://purl.oclc.org/ooxml/wordprocessingml/main",
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
        "http://purl.oclc.org/ooxml/officeDocument/relationships",
        "http://schemas.openxmlformats.org/officeDocument/2006/math",
        "http://purl.oclc.org/ooxml/officeDocument/math",
        "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
        "http://schemas.openxmlformats.org/drawingml/2006/picture",
        "http://schemas.openxmlformats.org/drawingml/2006/chart",
        "http://schemas.openxmlformats.org/drawingml/2006/diagram",
        "urn:schemas-microsoft-com:vml",
        "urn:schemas-microsoft-com:office:office",
        "urn:schemas-microsoft-com:office:word",
        # PowerPoint.
        "http://schemas.microsoft.com/office/powerpoint/2010/main",
        "http://schemas.microsoft.com/office/powerpoint/2012/main",
        "http://schemas.microsoft.com/office/powerpoint/2015/09/main",
        "http://schemas.microsoft.com/office/powerpoint/2015/10/main",
        "http://schemas.microsoft.com/office/powerpoint/2017/3/main",
        "http://schemas.microsoft.com/office/powerpoint/2017/10/main",
        "http://schemas.microsoft.com/office/powerpoint/2018/8/main",
        # DrawingML.
        "http://schemas.microsoft.com/office/drawing/2007/8/2/chart",
        "http://schemas.microsoft.com/office/drawing/2010/main",
        "http://schemas.microsoft.com/office/drawing/2012/main",
        "http://schemas.microsoft.com/office/drawing/2014/main",
        "http://schemas.microsoft.com/office/drawing/2014/chartex",
        "http://schemas.microsoft.com/office/drawing/2015/9/8/chartex",
        "http://schemas.microsoft.com/office/drawing/2015/10/21/chartex",
        "http://schemas.microsoft.com/office/drawing/2016/5/9/chartex",
        "http://schemas.microsoft.com/office/drawing/2016/5/10/chartex",
        "http://schemas.microsoft.com/office/drawing/2016/5/11/chartex",
        "http://schemas.microsoft.com/office/drawing/2016/5/12/chartex",
        "http://schemas.microsoft.com/office/drawing/2016/5/13/chartex",
        "http://schemas.microsoft.com/office/drawing/2016/5/14/chartex",
        "http://schemas.microsoft.com/office/drawing/2016/ink",
        "http://schemas.microsoft.com/office/drawing/2017/model3d",
        # Word.
        "http://schemas.microsoft.com/office/word/2010/wordml",
        "http://schemas.microsoft.com/office/word/2010/wordprocessingDrawing",
        "http://schemas.microsoft.com/office/word/2010/wordprocessingShape",
        "http://schemas.microsoft.com/office/word/2010/wordprocessingGroup",
        "http://schemas.microsoft.com/office/word/2010/wordprocessingCanvas",
        "http://schemas.microsoft.com/office/word/2010/wordprocessingInk",
        "http://schemas.microsoft.com/office/word/2012/wordml",
        "http://schemas.microsoft.com/office/word/2015/wordml/symex",
        "http://schemas.microsoft.com/office/word/2016/wordml/cid",
        "http://schemas.microsoft.com/office/word/2018/wordml",
        "http://schemas.microsoft.com/office/word/2018/wordml/cex",
        "http://schemas.microsoft.com/office/word/2020/wordml/sdtdatahash",
    }
)

# Pictures inside Office files read with OCR (ADR-054): at most this many in
# one document, each OCR run taking a second or more; a picture smaller than
# this many pixels on both sides is decoration (a bullet, a rule, an icon).
OFFICE_MAX_PICTURES: Final = 200
OFFICE_DECORATION_PIXELS: Final = 32
# Text a picture shows smaller than this, in points, cannot be read on the
# page: hidden, as for text in a document (DOCX_MIN_VISIBLE_HALF_POINTS).
OFFICE_MIN_VISIBLE_POINTS: Final = 2.0

# Text under this size, in half-points (2 pt), cannot be read on the page.
DOCX_MIN_VISIBLE_HALF_POINTS: Final = 4

# Workbook cells with a value read, over all sheets; and table cells written,
# empty ones included, so that a few cells far apart cannot make a huge grid.
XLSX_MAX_CELLS: Final = 2_000_000
XLSX_MAX_GRID_CELLS: Final = 4_000_000
# Cells with a value in one sheet. A sheet is one page, sent as one message
# within the page time limit: measured, a million numeric cells take about
# 20 s and 60 MB, too close to OFFICE_PAGE_TIMEOUT_S and OFFICE_MAX_MESSAGE_BYTES.
XLSX_MAX_SHEET_CELLS: Final = 500_000
# Characters of cell text in one sheet, hidden cells included: one long shared
# string used by many cells must not fill the worker or the page message.
XLSX_MAX_SHEET_TEXT: Final = 16_000_000
# Excel's own grid: 1 048 576 rows and 16 384 columns (A to XFD).
XLSX_MAX_ROWS: Final = 1_048_576
XLSX_MAX_COLUMNS: Final = 16_384

# Office positions and sizes are in EMU: 12 700 to a point. A presentation
# that gives no slide size gets PowerPoint's 16:9 default, 13.333 by 7.5 inches.
OFFICE_EMU_PER_POINT: Final = 12_700
PPTX_DEFAULT_SLIDE_WIDTH_EMU: Final = 12_192_000
PPTX_DEFAULT_SLIDE_HEIGHT_EMU: Final = 6_858_000
# Coordinates beyond the standard's range (ST_Coordinate, about 27 million
# inches) are not positions: such a shape is placed as if it had none.
OFFICE_MAX_COORDINATE: Final = 27_273_042_329_600
# Table cells written in one presentation, empty ones and those a span covers
# included: the serializer draws every cell of the grid, so a cell spanning a
# billion columns must not reach it. As XLSX_MAX_GRID_CELLS; PowerPoint's own
# tables stop at 75 columns.
PPTX_MAX_GRID_CELLS: Final = 4_000_000
# Line height, as a share of the slide's height, from which the XY-cut sets
# the gaps that separate shapes (LAYOUT_PARAGRAPH_GAP, LAYOUT_COLUMN_GAP):
# about 11 pt on a 7.5-inch slide, so shapes set slightly apart are split.
PPTX_LINE_HEIGHT: Final = 0.02

# The worker process, as for PDF (ADR-043): address space on Linux and macOS,
# seconds to open and check a file and to return one page, restarts after a
# page kills or stalls it, and the largest message it may send.
OFFICE_WORKER_MEMORY_BYTES: Final = 1536 * 1024 * 1024
OFFICE_OPEN_TIMEOUT_S: Final = 60.0
OFFICE_PAGE_TIMEOUT_S: Final = 30.0
OFFICE_MAX_WORKER_RESTARTS: Final = 3
OFFICE_MAX_MESSAGE_BYTES: Final = 64 * 1024 * 1024

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

# Letterheads on pages read with OCR (ADR-064): the top band is taller, since
# a scanned letterhead of logos and captions reaches about 15% of the page.
# Only the top band is matched by similarity; see sugo.analyzers.letterheads.
OCR_EDGE_BAND: Final = 0.2
# A block is a copy of a letterhead when at least this share of its
# character trigrams is found in the same band of another page: OCR errors
# and a different grouping of the logo captions change the rest.
LETTERHEAD_MIN_CONTAINMENT: Final = 0.5
# Blocks with fewer distinct trigrams are too short to compare ("O", "11").
LETTERHEAD_MIN_TRIGRAMS: Final = 4
# Only text clearly smaller than the page's typical text can be a letterhead
# copy: logo captions are small print. Body text that repeats at a page edge
# (formulaic clauses) is set at body size, and matching it by similarity
# could remove the part that is new on its page. Measured 2026-11-07 on a
# real scan: letterhead rows 0.3 to 0.7 of the body's line height.
LETTERHEAD_MAX_SIZE_RATIO: Final = 0.8
# Pages compared with each page, before and after it: a letterhead repeats
# on neighbouring pages, and the bound keeps the work linear in pages.
LETTERHEAD_WINDOW_PAGES: Final = 5
# Size of the keyed trigram bitsets, per block and per band. A band of about
# 500 trigrams fills about 11% of it, well below the containment threshold.
LETTERHEAD_SKETCH_BITS: Final = 4096

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
# Largest chunk size accepted: the input limit of common embedding models
# (8 191 tokens for OpenAI's); larger "chunks" would not be chunks for RAG.
CHUNK_MAX_TOKENS_LIMIT: Final = 8_192

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
# THREAT_MODEL D, ADR-053): folders and files holding keys, tokens, passwords,
# browser profiles and shell histories. Compared case-insensitively with every
# component of the resolved path.
MCP_EXCLUDED_DIRS: Final = frozenset(
    {
        ".ssh",
        ".gnupg",
        ".aws",
        ".azure",
        ".kube",
        ".docker",
        ".password-store",
        "keyrings",
        ".git",
        ".terraform.d",
        ".bitcoin",
        ".ethereum",
        ".electrum",
        ".mozilla",
        ".thunderbird",
        "thunderbird",
        "bravesoftware",
        "chromium",
        "filezilla",
    }
)
MCP_EXCLUDED_FILES: Final = frozenset(
    {
        ".netrc",
        ".pgpass",
        ".env",
        "_netrc",
        "pgpass.conf",
        ".git-credentials",
        ".npmrc",
        ".pypirc",
        ".yarnrc",
        ".yarnrc.yml",
        ".my.cnf",
        ".boto",
        ".s3cfg",
        ".vault-token",
        ".htpasswd",
        ".histfile",
        "consolehost_history.txt",
        "wallet.dat",
        "nuget.config",
        "sitemanager.xml",
        "recentservers.xml",
        "filezilla.xml",
        "unattend.xml",
        "autounattend.xml",
        "groups.xml",
        "web.config",
        "app.config",
        "login data",
        "web data",
        "cookies",
        "logins.json",
        "key3.db",
        "key4.db",
        "cookies.sqlite",
        "signons.sqlite",
    }
)
MCP_EXCLUDED_PATTERNS: Final = (
    "id_rsa*",
    "id_dsa*",
    "id_ecdsa*",
    "id_ed25519*",
    ".env.*",
    "*.kdbx",
    "*.kdb",
    "*.pem",
    "*.key",
    "*.p8",
    "*.p12",
    "*.pfx",
    "*.jks",
    "*.keystore",
    "*.ppk",
    "*.ovpn",
    "*.tfstate",
    "*.tfstate.*",
    "*.publishsettings",
    "credentials*",
    "secrets.*",
    # .bash_history, .zsh_history, .python_history, .psql_history and others.
    "*_history",
)
# Components that are secret only one after the other: "gh" or "protect"
# alone is an ordinary folder name, ".config/gh" holds GitHub tokens.
MCP_EXCLUDED_SEQUENCES: Final = (
    (".config", "gh"),
    (".config", "gcloud"),
    (".config", "rclone"),
    (".config", "hub"),
    (".m2", "settings.xml"),
    (".m2", "settings-security.xml"),
    (".gradle", "gradle.properties"),
    (".subversion", "auth"),
    # Windows credential, key and certificate stores.
    ("microsoft", "credentials"),
    ("microsoft", "protect"),
    ("microsoft", "crypto"),
    ("microsoft", "vault"),
    ("microsoft", "systemcertificates"),
    # Browser profiles: passwords, cookies, session tokens.
    ("google", "chrome"),
    ("microsoft", "edge"),
    (".config", "google-chrome"),
    (".config", "microsoft-edge"),
    ("mozilla", "firefox"),
    ("application support", "firefox"),
)
# The end of a PEM or OpenPGP private key header ("-----BEGIN RSA PRIVATE KEY-----",
# "-----BEGIN PGP PRIVATE KEY BLOCK-----"): never sent to an agent (ADR-053).
# Lenient on purpose: OCR reads dashes as en or em dashes, line wrapping and
# the serializer's line-start escape can split the header.
MCP_PRIVATE_KEY_PATTERN: Final = r"private\s+key(?:\s+block)?\s*\\?[-\u2010-\u2015\u2212]{3,}"

# --- Text edits and text cleaners (ADR-050) ------------------------------------

# Typographic ligatures and the letters they stand for. Only these are expanded:
# full NFKC would also turn "m²" into "m2" and "½" into "1" + U+2044 + "2", changing meaning.
LIGATURES: Final = MappingProxyType(
    {
        "ﬀ": "ff",
        "ﬁ": "fi",
        "ﬂ": "fl",
        "ﬃ": "ffi",
        "ﬄ": "ffl",
        "ﬅ": "st",
        "ﬆ": "st",
    }
)

# Spaces that print like a plain space: no-break, fixed-width and narrow
# spaces. The ideographic space stays until the CJK language packs exist.
SPECIAL_SPACES: Final = "\u00a0" + "".join(map(chr, range(0x2000, 0x200B))) + "\u202f\u205f"

# Characters that never print and only cost tokens: zero-width space, word
# joiner, byte order mark and soft hyphen. Zero-width joiners stay: emoji and
# some scripts need them.
INVISIBLE_CHARS: Final = "\u200b\u2060\ufeff\u00ad"

# Hyphens that can end a line in the middle of a word.
LINE_BREAK_HYPHENS: Final = "-\u2010\u2011\u00ad"

# Distinct words remembered by the lexicon analyzer. Hyphen joins need a word
# seen elsewhere in the document; past this many words the rest are not
# recorded, so a hostile document cannot grow memory without bound and a word
# not recorded is simply left hyphenated.
LEXICON_MAX_WORDS: Final = 200_000

# Text edits the core accepts for one block and for one page. Real prose needs
# a few per line; past these a cleaner is skipped for that block, or its
# proposals for the page are refused, so a hostile document cannot make
# cleaning take minutes per page and fill memory with edit records.
MAX_EDITS_PER_BLOCK: Final = 2_000
MAX_EDITS_PER_PAGE: Final = 10_000

# URL query parameters that only track the reader, removed by the tracking
# URL cleaner. Compared case-insensitively; any parameter starting with a
# prefix also counts.
TRACKING_PARAMETERS: Final = frozenset(
    {
        "fbclid",
        "gclid",
        "gclsrc",
        "dclid",
        "gbraid",
        "wbraid",
        "msclkid",
        "yclid",
        "twclid",
        "ttclid",
        "li_fat_id",
        "igshid",
        "mc_cid",
        "mc_eid",
        "_hsenc",
        "_hsmi",
        "mkt_tok",
        "oly_anon_id",
        "oly_enc_id",
        "vero_id",
        "rb_clickid",
        "wickedid",
    }
)
TRACKING_PARAMETER_PREFIXES: Final = ("utm_",)

# --- Inputs ---------------------------------------------------------------------

# The largest file any extractor accepts; each one applies its own limit.
MAX_INPUT_BYTES: Final = max(
    MAX_PDF_FILE_BYTES, MAX_IMAGE_FILE_BYTES, MAX_OFFICE_FILE_BYTES, MAX_XML_FILE_BYTES
)

# --- Web UI (ADR-055) -----------------------------------------------------------

# Bytes of randomness in the session token: 256 bits, beyond any guessing.
WEB_TOKEN_BYTES: Final = 32
# Seconds a connection may stay silent while sending or receiving. Loopback
# moves 200 MB in about a second; a client that stalls this long is stuck or
# hostile, and would otherwise hold its thread forever. Converting is not
# counted: the socket is idle then, and no timer runs.
WEB_SOCKET_TIMEOUT_S: Final = 60
# Seconds a whole upload may take. 200 MB takes about a second on loopback;
# the socket timeout bounds each wait, not a client that sends a byte now
# and then to keep the server busy.
WEB_UPLOAD_TIMEOUT_S: Final = 300
