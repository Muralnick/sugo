"""Tests for the UI chrome cleaner, alone and after the real image extractor."""

from io import BytesIO

import pytest
from PIL import Image, ImageDraw, ImageFont

from sugo.cleaners.ui_chrome import REASON, UiChromeCleaner
from sugo.core.decisions import Decision, apply_decisions
from sugo.core.models import Block, BlockType, Page, PageOrigin
from sugo.extractors.image.extract import extract_page
from sugo.extractors.image.ocr_engine import OcrEngine, bundled_models
from sugo.metrics.tokenizer import count_tokens


def block(block_id: str, kind: BlockType, text: str = "x") -> Block:
    return Block(id=block_id, type=kind, text=text, origin_engine="t")


def page(*blocks: Block) -> Page:
    return Page(index=0, width=100, height=100, origin=PageOrigin.OCR, blocks=blocks)


def test_proposes_only_ui_chrome_blocks() -> None:
    p = page(
        block("clock", BlockType.UI_CHROME, "9:41"),
        block("msg", BlockType.CHAT_MESSAGE, "Ciao"),
        block("para", BlockType.PARAGRAPH, "10:42"),
    )
    assert UiChromeCleaner().propose(p) == [Decision(block_id="clock", reason=REASON)]


def test_skips_blocks_already_removed() -> None:
    p = page(block("clock", BlockType.UI_CHROME, "9:41").mark_removed("other", "r"))
    assert UiChromeCleaner().propose(p) == []


def test_page_without_chrome_gets_no_proposals() -> None:
    assert UiChromeCleaner().propose(page(block("a", BlockType.PARAGRAPH))) == []


def test_proposals_are_accepted_by_the_core() -> None:
    p = page(block("clock", BlockType.UI_CHROME, "9:41"), block("a", BlockType.PARAGRAPH))
    cleaner = UiChromeCleaner()
    out = apply_decisions(p, cleaner.propose(p), cleaner=cleaner.name)
    assert [(b.id, b.removed, b.removed_by) for b in out.blocks] == [
        ("clock", True, "ui_chrome"),
        ("a", False, None),
    ]


@pytest.fixture(scope="module")
def engine() -> OcrEngine:
    return OcrEngine(*bundled_models())


def test_chat_screenshot_loses_only_the_status_bar(engine: OcrEngine) -> None:
    width, height = 750, 1334
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=30)
    draw.text((30, 20), "9:41", fill="black", font=font)
    draw.text((560, 20), "5G", fill="black", font=font)
    draw.text((640, 20), "87%", fill="black", font=font)
    bubbles = [
        ("left", "Hello, are we meeting tomorrow?"),
        ("right", "Yes, at six 10:42"),
        ("left", "Great, I will bring the papers"),
        ("right", "Thanks!"),
    ]
    for n, (side, text) in enumerate(bubbles):
        y = 200 + n * 160
        text_width = draw.textlength(text, font=font)
        x = 40 if side == "left" else width - 40 - text_width
        draw.text((x, y), text, fill="black", font=font)
    buffer = BytesIO()
    image.save(buffer, format="PNG")

    extracted = extract_page(buffer.getvalue(), engine)
    cleaner = UiChromeCleaner()
    cleaned = apply_decisions(extracted, cleaner.propose(extracted), cleaner=cleaner.name)

    removed = [(b.text, b.reason) for b in cleaned.blocks if b.removed]
    kept = [b.text for b in cleaned.blocks if not b.removed]
    assert removed == [("9:41", REASON), ("5G", REASON), ("87%", REASON)]
    # The message timestamp is content and stays (ADR-040).
    assert kept == [text for _, text in bubbles]
    before = count_tokens("\n\n".join(b.text for b in extracted.blocks))
    after = count_tokens("\n\n".join(kept))
    # Measured 35 -> 26 tokens (ADR-041); the gate leaves room for OCR drift.
    assert after <= 0.8 * before
