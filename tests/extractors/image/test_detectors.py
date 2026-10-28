"""Tests for the screenshot detectors: UI chrome, chat bubbles and code."""

from collections import Counter
from collections.abc import Callable

import pytest
from hypothesis import given
from hypothesis import strategies as st
from PIL import Image, ImageDraw, ImageFont

from sugo.core.models import BBox, BlockType, ChatSide
from sugo.extractors.image.extract import extract_page
from sugo.extractors.image.layout import build_blocks
from sugo.extractors.image.ocr_engine import OcrEngine, OcrLine, bundled_models

Encode = Callable[..., bytes]
HEIGHT = 0.02  # line height as a share of the page
CHAR = 0.01  # character width as a share of the page


def line(text: str, x: float, y: float, *, width: float | None = None) -> OcrLine:
    w = width if width is not None else len(text) * CHAR
    return OcrLine(
        text=text,
        confidence=0.95,
        bbox=BBox(x0=x, y0=y, x1=min(x + w, 1.0), y1=min(y + HEIGHT, 1.0)),
        illegible=False,
    )


def blocks(lines: list[OcrLine], *, screenshot: bool = True) -> list[tuple[str, str, str | None]]:
    return [
        (b.type.value, b.text, b.speaker.value if b.speaker else None)
        for b in build_blocks(lines, origin_engine="test", screenshot=screenshot)
    ]


class TestUiChrome:
    def test_status_bar_items_become_ui_chrome(self) -> None:
        lines = [line("9:41", 0.05, 0.01), line("87%", 0.88, 0.01), line("5G", 0.80, 0.01)]
        assert {kind for kind, _, _ in blocks(lines)} == {"ui_chrome"}

    def test_ui_chrome_keeps_its_text_and_is_not_removed(self) -> None:
        (block,) = build_blocks([line("9:41", 0.05, 0.01)], origin_engine="t", screenshot=True)
        assert (block.type, block.text, block.removed) == (BlockType.UI_CHROME, "9:41", False)

    def test_contact_name_under_the_status_bar_is_content(self) -> None:
        lines = [line("9:41", 0.05, 0.01), line("Marco Rossi", 0.40, 0.03)]
        assert blocks(lines) == [("ui_chrome", "9:41", None), ("paragraph", "Marco Rossi", None)]

    def test_times_inside_the_page_are_content(self) -> None:
        # Message timestamps are kept (ADR-040); only the edge bands hold chrome.
        assert blocks([line("10:42", 0.80, 0.50)]) == [("paragraph", "10:42", None)]

    def test_icon_misread_only_counts_in_edge_bands(self) -> None:
        assert blocks([line("Q", 0.9, 0.96)])[0][0] == "ui_chrome"
        assert blocks([line("Q", 0.9, 0.50)])[0][0] == "paragraph"

    def test_no_chrome_outside_screenshots(self) -> None:
        assert blocks([line("9:41", 0.05, 0.01)], screenshot=False)[0][0] == "paragraph"


def chat_lines() -> list[OcrLine]:
    return [
        line("Oggi", 0.46, 0.10),
        line("Ciao, ci vediamo domani?", 0.05, 0.15),
        line("Sì, alle 18", 0.80, 0.21),
        line("Perfetto, porto i documenti", 0.05, 0.27),
        line("10:42", 0.25, 0.30),
        line("Grazie!", 0.86, 0.36),
    ]


class TestChat:
    def test_aligned_bubbles_become_chat_messages_with_sides(self) -> None:
        assert blocks(chat_lines()) == [
            ("paragraph", "Oggi", None),
            ("chat_message", "Ciao, ci vediamo domani?", "left"),
            ("chat_message", "Sì, alle 18", "right"),
            ("chat_message", "Perfetto, porto i documenti\n10:42", "left"),
            ("chat_message", "Grazie!", "right"),
        ]

    def test_messages_on_one_side_only_are_not_a_chat(self) -> None:
        # Slack-like screenshots: everything left-aligned stays paragraphs.
        lines = [line(f"Message number {n}", 0.05, 0.1 + n * 0.06) for n in range(4)]
        assert {kind for kind, _, _ in blocks(lines)} == {"paragraph"}

    def test_no_chat_outside_screenshots(self) -> None:
        assert all(kind == "paragraph" for kind, _, _ in blocks(chat_lines(), screenshot=False))

    def test_speaker_values_are_neutral_sides(self) -> None:
        sides = {b.speaker for b in build_blocks(chat_lines(), origin_engine="t", screenshot=True)}
        assert sides == {None, ChatSide.LEFT, ChatSide.RIGHT}


class TestCode:
    def test_code_gets_its_indentation_back(self) -> None:
        rows = [
            "def total(items):",
            "result = 0",
            "for item in items:",
            "result += item",
            "return result",
        ]
        indents = [0, 4, 4, 8, 4]
        lines = [
            line(text, 0.05 + indent * CHAR, 0.10 + n * 0.025)
            for n, (text, indent) in enumerate(zip(rows, indents, strict=True))
        ]
        (block,) = build_blocks(lines, origin_engine="t")
        assert block.type is BlockType.CODE
        assert block.text == (
            "def total(items):\n    result = 0\n    for item in items:\n"
            "        result += item\n    return result"
        )

    @pytest.mark.parametrize(
        "rows",
        [
            # Legal list: rows end with ";" (the most important false positive).
            [
                "a) il compratore deve pagare il prezzo;",
                "b) il venditore deve consegnare;",
                "c) le parti collaborano;",
            ],
            # English prose starting rows with code keywords.
            [
                "if the buyer fails to pay the price",
                "for the purposes of this agreement,",
                "from the seller to the buyer and",
                "return the goods within 30 days.",
            ],
            # A one-row heading ending with a colon.
            ["For the following reasons:"],
            # One-row texts with a real code signal still stay text (two rows needed).
            ["for the following reasons:"],
            ["Total = 1250 EUR"],
            ["import duties apply to all goods", "shipped from outside the union."],
        ],
    )
    def test_prose_is_not_code(self, rows: list[str]) -> None:
        lines = [line(text, 0.05, 0.10 + n * 0.025) for n, text in enumerate(rows)]
        assert {b.type for b in build_blocks(lines, origin_engine="t")} == {BlockType.PARAGRAPH}


@pytest.mark.invariant
@given(
    texts=st.lists(
        st.sampled_from(
            ["9:41", "87%", "Q", "Ciao", "def f(x):", "return x;", "a = 1", "il prezzo;"]
        ),
        min_size=1,
        max_size=15,
    ),
    xs=st.lists(st.floats(min_value=0.0, max_value=0.9), min_size=15, max_size=15),
    ys=st.lists(st.floats(min_value=0.0, max_value=0.97), min_size=15, max_size=15),
)
def test_detectors_never_lose_words(texts: list[str], xs: list[float], ys: list[float]) -> None:
    # Principle 3: typing blocks (chrome, chat, code) must keep every word.
    lines = [line(t, x, y) for t, x, y in zip(texts, xs, ys, strict=False)]
    out = build_blocks(lines, origin_engine="t", screenshot=True)
    assert Counter(w for ln in lines for w in ln.text.split()) == Counter(
        w for b in out for w in b.text.split()
    )
    assert not any(b.removed for b in out)


# --- End to end with the real OCR models -------------------------------------


@pytest.fixture(scope="module")
def engine() -> OcrEngine:
    return OcrEngine(*bundled_models())


def test_chat_screenshot_end_to_end(engine: OcrEngine, encode: Encode) -> None:
    width, height = 750, 1334
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=30)
    draw.text((30, 20), "9:41", fill="black", font=font)
    draw.text((640, 20), "87%", fill="black", font=font)
    bubbles = [
        ("left", "Hello, are we meeting tomorrow?"),
        ("right", "Yes, at six"),
        ("left", "Great, I will bring the papers"),
        ("right", "Thanks!"),
    ]
    for n, (side, text) in enumerate(bubbles):
        y = 200 + n * 160
        text_width = draw.textlength(text, font=font)
        x = 40 if side == "left" else width - 40 - text_width
        draw.rounded_rectangle((x - 20, y - 20, x + text_width + 20, y + 55), 20, fill="#e9e9eb")
        draw.text((x, y), text, fill="black", font=font)
    page = extract_page(encode(image, "PNG"), engine)
    summary = [(b.type.value, b.text, b.speaker.value if b.speaker else None) for b in page.blocks]
    assert summary == [
        ("ui_chrome", "9:41", None),
        ("ui_chrome", "87%", None),
        ("chat_message", "Hello, are we meeting tomorrow?", "left"),
        ("chat_message", "Yes, at six", "right"),
        ("chat_message", "Great, I will bring the papers", "left"),
        ("chat_message", "Thanks!", "right"),
    ]
