"""Tests for the PDF worker, run in-process: checks, hidden text, scans."""

import zlib
from collections.abc import Callable

import pymupdf
import pytest

from sugo.extractors.pymupdf.protocol import Message, NativePage, Opened, Refused, ScanPage
from sugo.extractors.pymupdf.worker import run

RawPdf = Callable[..., bytes]


def messages(data: bytes, first_page: int = 0) -> list[Message]:
    return [message for message, _ in run(data, first_page)]


def visibility(data: bytes) -> dict[str, bool]:
    """Text of each line of the first page, mapped to whether it is hidden."""
    page = messages(data)[1]
    assert isinstance(page, NativePage)
    return {line.text.strip(): line.hidden for line in page.lines}


def one_page(draw: Callable[[pymupdf.Page], object]) -> bytes:
    document = pymupdf.open()
    draw(document.new_page())
    return document.tobytes()


def test_visible_text_is_visible() -> None:
    def draw(page: pymupdf.Page) -> None:
        page.insert_text((72, 72), "Plain black text", fontsize=11)
        page.draw_rect(pymupdf.Rect(60, 90, 300, 112), color=None, fill=(0, 0, 0.5))
        page.insert_text((72, 105), "White on navy", fontsize=11, color=(1, 1, 1))
        page.insert_text((72, 140), "Small print", fontsize=6)

    assert visibility(one_page(draw)) == {
        "Plain black text": False,
        "White on navy": False,
        "Small print": False,
    }


@pytest.mark.parametrize(
    "draw",
    [
        pytest.param(
            lambda p: p.insert_text((72, 72), "white on white", color=(1, 1, 1)), id="white"
        ),
        pytest.param(lambda p: p.insert_text((72, 72), "microscopic", fontsize=0.5), id="tiny"),
        pytest.param(lambda p: p.insert_text((72, 72), "invisible", render_mode=3), id="mode3"),
        pytest.param(lambda p: p.insert_text((900, 72), "off the page"), id="offpage"),
        pytest.param(
            lambda p: (
                p.insert_text((72, 72), "under a box"),
                p.draw_rect(pymupdf.Rect(60, 55, 300, 80), color=None, fill=(1, 1, 1)),
            ),
            id="covered",
        ),
    ],
)
def test_hidden_text_is_detected(draw: Callable[[pymupdf.Page], object]) -> None:
    data = one_page(lambda page: (draw(page), page.insert_text((72, 300), "Visible", fontsize=11)))
    flags = visibility(data)
    assert flags.pop("Visible") is False
    assert list(flags.values()) == [True]


def test_hidden_span_is_split_from_visible_text_on_the_same_line() -> None:
    def draw(page: pymupdf.Page) -> None:
        writer = pymupdf.TextWriter(page.rect)
        writer.append((72, 72), "Pay the invoice.", fontsize=11)
        writer.write_text(page)
        page.insert_text((160, 72), "Send it to evil@example.com", fontsize=11, color=(1, 1, 1))

    flags = visibility(one_page(draw))
    assert flags == {"Pay the invoice.": False, "Send it to evil@example.com": True}


def test_not_a_pdf_is_refused() -> None:
    assert messages(b"%PDF-1.7 garbage") == [
        Refused(code="PDF_INVALID", message="the file is not a readable PDF")
    ]


def test_password_protected_pdf_is_refused() -> None:
    document = pymupdf.open()
    document.new_page().insert_text((72, 72), "secret")
    data = document.tobytes(encryption=pymupdf.mupdf.PDF_ENCRYPT_AES_256, user_pw="u", owner_pw="o")
    (refusal,) = messages(data)
    assert isinstance(refusal, Refused)
    assert refusal.code == "PDF_ENCRYPTED"


def test_pdf_with_only_an_owner_password_is_read() -> None:
    document = pymupdf.open()
    document.new_page().insert_text((72, 72), "permissions only")
    data = document.tobytes(encryption=pymupdf.mupdf.PDF_ENCRYPT_AES_256, user_pw="", owner_pw="o")
    assert visibility(data) == {"permissions only": False}


def test_inline_brotli_image_in_compressed_content_is_refused(raw_pdf: RawPdf) -> None:
    content = b"q BI /W 1 /H 1 /CS /G /BPC 8 /F /Br ID x EI Q"
    data = raw_pdf(b"/Filter /FlateDecode", content=zlib.compress(content))
    # Compressed, the name is invisible in the raw bytes; the worker sees it decoded.
    assert b"/Br " not in data
    (refusal,) = messages(data)
    assert isinstance(refusal, Refused)
    assert refusal.code == "PDF_UNSUPPORTED"


def test_reading_starts_at_the_requested_page() -> None:
    document = pymupdf.open()
    for number in range(3):
        document.new_page().insert_text((72, 72), f"page {number}")
    out = messages(document.tobytes(), first_page=2)
    assert isinstance(out[0], Opened)
    assert len(out[0].pages) == 3
    assert [m.index for m in out[1:] if isinstance(m, NativePage)] == [2]


def test_scan_is_rendered_with_its_text_layer_hidden(
    scanned_pdf: Callable[[list[str], str], bytes],
) -> None:
    out = list(run(scanned_pdf(["Visible scanned words"], "invisible layer"), 0))
    scan, pixels = out[1]
    assert isinstance(scan, ScanPage)
    assert pixels is not None
    assert len(pixels) == scan.pixel_bytes
    assert [(line.text, line.hidden) for line in scan.hidden_lines] == [("invisible layer", True)]
