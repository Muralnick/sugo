"""Detect screenshot structures: UI chrome, chat bubbles and code.

Detectors only decide what a line or a paragraph *is*; they never remove
anything. UI chrome is typed ``ui_chrome`` and removed later, with a reason, by
a cleaner (soft deletion, principle 3).

- **UI chrome:** status-bar items (clock, battery, network) and lone icon
  misreads, only inside the top and bottom bands of a screenshot. Message
  timestamps inside a chat are content and are kept.
- **Chat:** a screenshot whose paragraphs are bubbles aligned to both sides.
  Each bubble becomes a ``chat_message`` with its side (ADR-040).
- **Code:** paragraphs whose rows mostly show code syntax. Indentation, which
  OCR drops, is rebuilt from the x position of each row.

All rules are deliberately conservative; see the thresholds in
``sugo.core.constants``.
"""

import re
import statistics
from collections.abc import Sequence
from dataclasses import dataclass

from sugo.core.constants import (
    CHAT_MIN_ALIGNED_SHARE,
    CHAT_MIN_MESSAGES,
    CHAT_SIDE_MARGIN,
    CODE_MIN_SIGNAL_ROWS,
    CODE_MIN_SIGNAL_SHARE,
    UI_CHROME_EDGE_BAND,
    UI_CHROME_ICON_MAX_CHARS,
)
from sugo.core.models import BlockType, ChatSide
from sugo.extractors.image.ocr_engine import OcrLine

Rows = Sequence[Sequence[OcrLine]]

_STATUS_ITEM = re.compile(
    r"""^(
        \d{1,2}[:.]\d{2}(\s?[AaPp]\.?[Mm]\.?)?  # clock: 9:41, 21.05, 9:41 PM
      | \d{1,3}\s?%                            # battery
      | (LTE|[2-5]G|[2-5]G\+|E|H\+?|Wi-?Fi|VPN)  # network
    )$""",
    re.VERBOSE,
)
# Each signal needs code structure, not just a word: legal lists end rows with
# ";" and English prose starts rows with "if", "for", "from" or "return".
_CODE_SIGNALS = (
    re.compile(r"[{}]\s*$"),  # block opens or closes
    re.compile(r"^\s*[}\])]"),  # row starts by closing a bracket
    re.compile(r"^\s*(if|elif|while|for|switch)\b.*[:{]\s*$"),  # control flow header
    re.compile(r"^\s*(def|class|function|func|fn)\s+\w+\s*[(:{<]"),  # definition
    re.compile(r"^\s*(import\s+[\w.]+(\s+as\s+\w+)?;?$|from\s+[\w.]+\s+import\b|#include\s*[<\"])"),
    re.compile(r"^\s*(const|let|var)\s+\w+\s*="),  # declaration
    re.compile(r"^\s*(public|private|protected|static)\s+[\w<>\[\]]+\s+\w+\s*[({=;]"),
    re.compile(r"^\s*return\b[^.]*;\s*$"),  # return statement with semicolon
    re.compile(r"(==|!=|=>|->|\+=|-=|&&|\|\||::)"),  # operators rare in prose
    re.compile(r"^\s*[\w.\[\]]+\s*=\s*\S"),  # assignment
    re.compile(r"\w\([^()]*\)\s*[:;{]?\s*$"),  # call or signature at the end of a row
)


@dataclass(frozen=True)
class Detection:
    """What a paragraph is, and its text as it should be stored."""

    type: BlockType
    text: str
    speaker: ChatSide | None = None


def is_ui_chrome(line: OcrLine) -> bool:
    """Whether a screenshot line is a status-bar item or an icon misread."""
    if line.illegible:
        return False
    in_band = line.bbox.y1 <= UI_CHROME_EDGE_BAND or line.bbox.y0 >= 1.0 - UI_CHROME_EDGE_BAND
    if not in_band:
        return False
    text = line.text.strip()
    return bool(_STATUS_ITEM.match(text)) or len(text) <= UI_CHROME_ICON_MAX_CHARS


def plain_text(rows: Rows) -> str:
    """Rows joined with newlines, boxes on one row with a space."""
    return "\n".join(" ".join(line.text for line in row) for row in rows)


def detect(paragraphs: Sequence[Rows], *, screenshot: bool) -> list[Detection]:
    """Classify the readable paragraphs of a page, in the given order."""
    detections = [_code_or_paragraph(rows) for rows in paragraphs]
    if not screenshot:
        return detections
    sides = [_side(rows) for rows in paragraphs]
    aligned = [side for side in sides if side is not None]
    is_chat = (
        len(aligned) >= CHAT_MIN_MESSAGES
        and ChatSide.LEFT in aligned
        and ChatSide.RIGHT in aligned
        and len(aligned) >= CHAT_MIN_ALIGNED_SHARE * len(paragraphs)
    )
    if not is_chat:
        return detections
    return [
        Detection(BlockType.CHAT_MESSAGE, detection.text, side)
        if side is not None and detection.type is BlockType.PARAGRAPH
        else detection
        for detection, side in zip(detections, sides, strict=True)
    ]


def _side(rows: Rows) -> ChatSide | None:
    x0 = min(line.bbox.x0 for row in rows for line in row)
    x1 = max(line.bbox.x1 for row in rows for line in row)
    if x0 < CHAT_SIDE_MARGIN and x1 < 1.0 - CHAT_SIDE_MARGIN:
        return ChatSide.LEFT
    if x1 > 1.0 - CHAT_SIDE_MARGIN and x0 > CHAT_SIDE_MARGIN:
        return ChatSide.RIGHT
    return None


def _code_or_paragraph(rows: Rows) -> Detection:
    texts = [" ".join(line.text for line in row) for row in rows]
    signals = sum(any(signal.search(text) for signal in _CODE_SIGNALS) for text in texts)
    # Two rows at least: a one-row heading such as "For these reasons:" must not
    # become code. A lone command on one row stays text, the cautious choice.
    if signals >= CODE_MIN_SIGNAL_ROWS and signals >= CODE_MIN_SIGNAL_SHARE * len(texts):
        return Detection(BlockType.CODE, _indented(rows))
    return Detection(BlockType.PARAGRAPH, plain_text(rows))


def _indented(rows: Rows) -> str:
    """Rebuild leading spaces from each row's left edge (OCR drops indentation)."""
    widths = [
        (line.bbox.x1 - line.bbox.x0) / len(line.text) for row in rows for line in row if line.text
    ]
    char_width = statistics.median(widths) if widths else 0.0
    left = min(row[0].bbox.x0 for row in rows)
    result = []
    for row in rows:
        indent = round((row[0].bbox.x0 - left) / char_width) if char_width > 0 else 0
        result.append(" " * indent + " ".join(line.text for line in row))
    return "\n".join(result)
