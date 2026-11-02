"""Tests for the PDF worker, run in-process: checks, hidden text, scans."""

import subprocess
import sys
import zlib
from collections.abc import Callable

import pymupdf
import pytest

from sugo.core.constants import PDF_OCR_MAX_PIXELS
from sugo.extractors.pymupdf import worker
from sugo.extractors.pymupdf.guard import BROTLI_REFUSAL, raw_problem
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


def test_content_stream_claiming_to_be_an_image_is_still_checked(raw_pdf: RawPdf) -> None:
    # "/Subtype /Image" is written by the attacker; MuPDF runs /Contents anyway.
    content = b"q BI /W 1 /H 1 /CS /G /BPC 8 /F /Br ID x EI Q"
    data = raw_pdf(b"/Filter /FlateDecode /Subtype /Image", content=zlib.compress(content))
    (refusal,) = messages(data)
    assert isinstance(refusal, Refused)
    assert refusal.code == "PDF_UNSUPPORTED"


def test_restarted_worker_skips_the_stream_check(raw_pdf: RawPdf) -> None:
    # The first worker checked the same bytes; restarts must not pay for it again.
    content = b"q BI /W 1 /H 1 /CS /G /BPC 8 /F /Br ID x EI Q"
    data = raw_pdf(b"/Filter /FlateDecode", content=zlib.compress(content))
    assert isinstance(messages(data, first_page=1)[0], Opened)


def test_hidden_space_does_not_carry_a_hidden_word_into_visible_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def span(text: str, x: float, *, hidden: bool) -> worker._Span:
        return worker._Span(text, (x, 10.0, x + 30, 20.0), 11.0, False, False, hidden)

    spans = [span("Hello", 10, hidden=False), span(" ", 40, hidden=True)]
    spans.append(span("INJECT", 45, hidden=True))
    monkeypatch.setattr(worker, "_span", lambda raw, *_: raw)
    lines = worker._split_line({"spans": spans}, pymupdf.Rect(0, 0, 200, 200), None, 1.0)  # type: ignore[arg-type]
    assert [(line.text, line.hidden) for line in lines] == [("Hello", False), ("INJECT", True)]


def test_page_failing_in_any_way_is_reported_and_reading_continues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = pymupdf.open()
    for number in range(3):
        document.new_page().insert_text((72, 72), f"page {number}")
    read_page = worker._read_page

    def fail_on_page_1(page: pymupdf.Page, index: int) -> object:
        if index == 1:
            raise TypeError("unexpected MuPDF failure")
        return read_page(page, index)

    monkeypatch.setattr(worker, "_read_page", fail_on_page_1)
    out = messages(document.tobytes())
    assert [m.kind for m in out] == ["opened", "native", "page_failed", "native"]


def test_page_that_fails_to_load_keeps_the_document_readable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = pymupdf.open()
    for _ in range(2):
        document.new_page(width=300, height=400)
    box = worker._box
    calls = iter([True, False])
    monkeypatch.setattr(worker, "_box", lambda page: box(page) if next(calls) else 1 / 0)
    opened = messages(document.tobytes())[0]
    assert isinstance(opened, Opened)
    assert [(b.width, b.height) for b in opened.pages] == [(300.0, 400.0), (300.0, 400.0)]


def test_corrupt_stream_does_not_stop_the_document(raw_pdf: RawPdf) -> None:
    # MuPDF decodes what it can; the check sees what the interpreter would see.
    data = raw_pdf(b"/Filter /FlateDecode", content=b"not zlib data at all")
    assert [m.kind for m in messages(data)] == ["opened", "native"]


@pytest.mark.parametrize("size", [(595.0, 842.0), (1350.0, 1920.0), (14400.0, 14400.0)])
def test_scan_render_always_fits_the_pixel_limit(size: tuple[float, float]) -> None:
    document = pymupdf.open()
    page = document.new_page(width=size[0], height=size[1])
    pixmap = page.get_pixmap(dpi=worker._ocr_dpi(*size), alpha=False)
    assert pixmap.width * pixmap.height <= PDF_OCR_MAX_PIXELS


def test_worker_never_loads_the_pymupdf_models() -> None:
    """PyMuPDF 2.0 loads ONNX models on import unless the worker blocks them."""
    code = (
        "import sys; import sugo.extractors.pymupdf.worker\n"
        "blocked = [m for m in ('pymupdf.layout', 'pymupdf4llm')"
        " if sys.modules.get(m, 0) is not None]\n"
        "loaded = {m.split('.')[0] for m in sys.modules}"
        " & {'onnxruntime', 'networkx', 'tabulate', 'psutil', 'yaml'}\n"
        "sys.exit(f'not blocked: {blocked}, loaded: {sorted(loaded)}' if blocked or loaded else 0)"
    )
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-I", "-c", code], capture_output=True, text=True, check=False, timeout=60
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "stream_dict",
    [b"/F 5 0 R", b"/Filter +5 0 R", b"/Filter [ %]\n /Br]", b"/F [ (]) 5 0 R]"],
    ids=["short-key", "signed-reference", "commented-array", "string-in-array"],
)
def test_stream_filter_naming_brotli_is_refused_before_decoding(
    raw_pdf: RawPdf, stream_dict: bytes
) -> None:
    # The worker reads each stream's filter through MuPDF's objects, so no
    # spelling the raw guard might miss reaches the decoder.
    (refusal,) = messages(raw_pdf(stream_dict, content=b"x", extra=b"/Br"))
    assert isinstance(refusal, Refused)
    assert refusal.message == BROTLI_REFUSAL


def two_contents(first: bytes, second: bytes) -> bytes:
    """A one-page PDF whose content is split into two compressed streams."""
    document = pymupdf.open()
    page = document.new_page()
    parts = []
    for content in (first, second):
        xref = document.get_new_xref()
        document.update_object(xref, "<<>>")
        document.update_stream(xref, content)
        parts.append(f"{xref} 0 R")
    document.xref_set_key(page.xref, "Contents", f"[{' '.join(parts)}]")
    return document.tobytes()


@pytest.mark.parametrize(
    ("first", "second"),
    [
        (b"q BI /W 1 /H 1 /CS /G /BPC 8 /F", b"/Br ID x EI Q"),
        (b"q BI /W 1 /H 1 /CS /G /BPC 8 /F [", b"/Br] ID x EI Q"),
    ],
    ids=["name", "array"],
)
def test_inline_image_split_across_content_streams_is_refused(first: bytes, second: bytes) -> None:
    # MuPDF joins a page's content streams, so neither half alone shows the filter.
    (refusal,) = messages(two_contents(first, second))
    assert isinstance(refusal, Refused)
    assert refusal.message == BROTLI_REFUSAL


def test_page_with_several_content_streams_is_read() -> None:
    data = two_contents(b"BT /Helv 11 Tf 72 72 Td (first) Tj ET", b"BT 72 90 Td (second) Tj ET")
    assert isinstance(messages(data)[0], Opened)


def with_stream(
    dictionary: str, data: bytes, link: Callable[[pymupdf.Document, int], None]
) -> bytes:
    """A one-page PDF with one more stream, attached to the document by ``link``."""
    document = pymupdf.open()
    document.new_page()
    xref = document.get_new_xref()
    document.update_object(xref, dictionary)
    document.update_stream(xref, data)
    link(document, xref)
    return document.tobytes()


def test_brotli_name_hidden_in_an_object_stream_is_refused() -> None:
    # Compressed in an object stream, the name is out of the raw guard's sight;
    # the worker reads every object as MuPDF parsed it.
    document = pymupdf.open()
    page = document.new_page()
    xref = document.get_new_xref()
    document.update_object(xref, "<< /X /Br >>")
    document.xref_set_key(page.xref, "Hidden", f"{xref} 0 R")
    data = document.tobytes(use_objstms=True, deflate=True)
    assert raw_problem(data) is None
    (refusal,) = messages(data)
    assert isinstance(refusal, Refused)
    assert refusal.message == BROTLI_REFUSAL


def page_contents(document: pymupdf.Document, xref: int) -> None:
    document.xref_set_key(document[0].xref, "Contents", f"{xref} 0 R")


def appearance(document: pymupdf.Document, xref: int) -> None:
    annot = document.get_new_xref()
    document.update_object(
        annot, f"<< /Type /Annot /Subtype /Square /Rect [0 0 9 9] /AP << /N {xref} 0 R >> >>"
    )
    document.xref_set_key(document[0].xref, "Annots", f"[{annot} 0 R]")


@pytest.mark.parametrize("link", [page_contents, appearance], ids=["contents", "appearance"])
def test_stream_run_as_content_is_refused_for_any_brotli_name(
    link: Callable[[pymupdf.Document, int], None],
) -> None:
    # It claims to be an image, but MuPDF runs it as content all the same.
    image = "<< /Type /XObject /Subtype /Image /Width 1 /Height 1 /BitsPerComponent 8 >>"
    (refusal,) = messages(with_stream(image, b"q BI /W 1 /H 1 /DP << /X /Br >> ID x EI Q", link))
    assert isinstance(refusal, Refused)
    assert refusal.message == BROTLI_REFUSAL


def test_brotli_name_by_chance_in_image_pixels_is_not_refused() -> None:
    image = (
        "<< /Type /XObject /Subtype /Image /Width 4 /Height 1"
        " /ColorSpace /DeviceGray /BitsPerComponent 8 >>"
    )
    data = with_stream(image, b"/Br ", lambda document, xref: None)
    assert isinstance(messages(data)[0], Opened)
