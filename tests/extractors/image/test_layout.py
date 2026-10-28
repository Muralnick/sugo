"""Tests for sugo.extractors.image.layout and the end-to-end image extractor."""

from collections import Counter
from collections.abc import Callable

import pytest
from hypothesis import given
from hypothesis import strategies as st
from PIL import Image, ImageDraw, ImageFont

from sugo.core.models import BBox, BlockFlag, BlockType, PageOrigin
from sugo.extractors.image.extract import extract_page
from sugo.extractors.image.layout import build_blocks, build_page
from sugo.extractors.image.ocr_engine import OcrEngine, OcrLine, bundled_models

Encode = Callable[..., bytes]
LINE = 0.02  # line height used by the synthetic layouts, as a share of the page


def line(text: str, x: float, y: float, width: float = 0.3, *, illegible: bool = False) -> OcrLine:
    return OcrLine(
        text="" if illegible else text,
        confidence=0.2 if illegible else 0.95,
        bbox=BBox(x0=x, y0=y, x1=min(x + width, 1.0), y1=min(y + LINE, 1.0)),
        illegible=illegible,
    )


def texts(lines: list[OcrLine]) -> list[str]:
    return [block.text for block in build_blocks(lines, origin_engine="test")]


def test_no_lines_give_no_blocks() -> None:
    assert build_blocks([], origin_engine="test") == ()


def test_close_lines_form_one_paragraph_joined_by_newlines() -> None:
    lines = [
        line("The contract may", 0.1, 0.10),
        line("be with-", 0.1, 0.125),
        line("drawn.", 0.1, 0.15),
    ]
    assert texts(lines) == ["The contract may\nbe with-\ndrawn."]


def test_paragraph_gap_starts_a_new_block() -> None:
    lines = [line("First paragraph.", 0.1, 0.10), line("Second paragraph.", 0.1, 0.16)]
    assert texts(lines) == ["First paragraph.", "Second paragraph."]


def test_two_columns_are_read_column_by_column() -> None:
    lines = [
        line("Left one", 0.05, 0.10),
        line("Right one", 0.55, 0.10),
        line("Left two", 0.05, 0.125),
        line("Right two", 0.55, 0.125),
    ]
    assert texts(lines) == ["Left one\nLeft two", "Right one\nRight two"]


def test_full_width_title_comes_before_the_columns() -> None:
    lines = [
        line("Title across the page", 0.05, 0.05, width=0.9),
        line("Left", 0.05, 0.10),
        line("Right", 0.55, 0.10),
        line("Left more", 0.05, 0.125),
        line("Right more", 0.55, 0.125),
    ]
    assert texts(lines) == ["Title across the page", "Left\nLeft more", "Right\nRight more"]


def test_boxes_on_the_same_row_are_joined_with_a_space() -> None:
    # OCR sometimes splits one visual line in two boxes with a small gap.
    lines = [line("Total due", 0.10, 0.30, width=0.15), line("1250 EUR", 0.26, 0.302, width=0.1)]
    assert texts(lines) == ["Total due 1250 EUR"]


def test_chat_bubbles_alternate_in_time_order() -> None:
    lines = [
        line("Ciao, ci vediamo?", 0.05, 0.10),
        line("Sì, alle 18", 0.60, 0.16),
        line("Perfetto", 0.05, 0.22),
    ]
    assert texts(lines) == ["Ciao, ci vediamo?", "Sì, alle 18", "Perfetto"]


@pytest.mark.invariant
def test_illegible_line_is_never_merged_into_readable_text() -> None:
    # Principle 4: the unreadable middle line keeps its own flagged, empty block.
    lines = [
        line("Readable before", 0.1, 0.10),
        line("", 0.1, 0.125, illegible=True),
        line("Readable after", 0.1, 0.15),
    ]
    blocks = build_blocks(lines, origin_engine="test")
    assert [b.text for b in blocks] == ["Readable before", "", "Readable after"]
    assert BlockFlag.ILLEGIBLE in blocks[1].flags
    assert not blocks[0].flags
    assert not blocks[2].flags


def test_blocks_carry_order_bbox_confidence_and_engine() -> None:
    lines = [line("A", 0.1, 0.10), line("B", 0.1, 0.125)]
    (block,) = build_blocks(lines, origin_engine="rapidocr-test")
    assert (block.id, block.reading_order, block.type) == ("b0", 0, BlockType.PARAGRAPH)
    assert block.origin_engine == "rapidocr-test"
    assert block.bbox == BBox(x0=0.1, y0=0.10, x1=0.4, y1=0.145)
    assert block.confidence == pytest.approx(0.95)


def test_page_keeps_image_size_and_ocr_origin() -> None:
    page = build_page([line("A", 0.1, 0.1)], width=1170, height=2532, origin_engine="t")
    assert (page.width, page.height, page.origin) == (1170.0, 2532.0, PageOrigin.OCR)


# --- Properties --------------------------------------------------------------

coordinates = st.floats(min_value=0.0, max_value=0.95, allow_nan=False)
ocr_lines = st.builds(
    line,
    text=st.text(alphabet="abcdefghij ", min_size=1, max_size=12).map(str.strip).filter(bool),
    x=coordinates,
    y=coordinates,
    width=st.floats(min_value=0.01, max_value=0.5),
    illegible=st.booleans(),
)


@pytest.mark.invariant
@given(lines=st.lists(ocr_lines, max_size=25))
def test_every_line_ends_up_in_exactly_one_block(lines: list[OcrLine]) -> None:
    # Principle 3: layout must not lose or duplicate text.
    blocks = build_blocks(lines, origin_engine="test")
    words_in = Counter(w for ln in lines if not ln.illegible for w in ln.text.split())
    words_out = Counter(w for b in blocks for w in b.text.split())
    assert words_in == words_out
    assert sum(BlockFlag.ILLEGIBLE in b.flags for b in blocks) == sum(ln.illegible for ln in lines)
    assert [b.reading_order for b in blocks] == list(range(len(blocks)))
    assert len({b.id for b in blocks}) == len(blocks)


@pytest.mark.invariant
@given(lines=st.lists(ocr_lines, max_size=25), seed=st.randoms(use_true_random=False))
def test_result_does_not_depend_on_input_order(lines: list[OcrLine], seed: object) -> None:
    # Principle 6: the detector's output order must not change the document.
    shuffled = list(lines)
    seed.shuffle(shuffled)  # type: ignore[attr-defined]
    assert build_blocks(shuffled, origin_engine="t") == build_blocks(lines, origin_engine="t")


@pytest.mark.invariant
def test_identical_positions_do_not_leak_input_order() -> None:
    # Regression: found by the property above. Two illegible boxes at the same
    # corner but of different widths used to come out in input order.
    lines = [
        line("a", 0.0, 0.0, width=0.5),
        line("", 0.0, 0.0, width=0.5, illegible=True),
        line("", 0.0, 0.0, width=0.25, illegible=True),
    ]
    forward = build_blocks(lines, origin_engine="t")
    assert build_blocks(list(reversed(lines)), origin_engine="t") == forward


# --- End to end with the real OCR models -------------------------------------


@pytest.fixture(scope="module")
def engine() -> OcrEngine:
    return OcrEngine(*bundled_models())


def test_two_column_image_end_to_end(engine: OcrEngine, encode: Encode) -> None:
    image = Image.new("RGB", (1200, 500), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=28)
    draw.text((40, 30), "Supply agreement between the parties", fill="black", font=font)
    for row, (left, right) in enumerate(
        [("Left column first", "Right column first"), ("Left column second", "Right column second")]
    ):
        draw.text((40, 120 + row * 40), left, fill="black", font=font)
        draw.text((650, 120 + row * 40), right, fill="black", font=font)
    page = extract_page(encode(image, "PNG"), engine)
    assert [b.text for b in page.blocks] == [
        "Supply agreement between the parties",
        "Left column first\nLeft column second",
        "Right column first\nRight column second",
    ]
    assert (page.width, page.height) == (1200.0, 500.0)


def test_blank_image_skips_ocr(encode: Encode) -> None:
    class NoOcr:
        def read(self, image: object) -> list[OcrLine]:
            raise AssertionError("OCR must not run on a blank image")

    page = extract_page(encode(Image.new("RGB", (300, 200), "white"), "PNG"), NoOcr())  # type: ignore[arg-type]
    assert page.blocks == ()
