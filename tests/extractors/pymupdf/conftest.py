"""Fixtures that build test PDFs in memory; no files from outside the repository."""

from collections.abc import Callable
from io import BytesIO

import pymupdf
import pytest
from PIL import Image, ImageDraw, ImageFont

RawPdf = Callable[..., bytes]


def _raw_pdf(
    stream_dict: bytes = b"", content: bytes = b"BT ET", extra: bytes = b"", gap: bool = False
) -> bytes:
    """A minimal hand-written PDF, so tests control every byte MuPDF would see.

    Args:
        stream_dict: Extra entries for the content stream's dictionary.
        content: The content stream's bytes, stored as is.
        extra: One more object, numbered 5, e.g. a filter name.
        gap: Number ``extra`` 6 instead and list no object 5, a gap in the
            numbering that cairo and Microsoft Print to PDF write.
    """
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] /Contents 4 0 R >>",
        b"<< /Length %d %s >>\nstream\n%s\nendstream" % (len(content), stream_dict, content),
    ]
    if extra:
        objects.append(extra)
    numbers = [1, 2, 3, 4, 6 if gap else 5][: len(objects)]
    out = b"%PDF-1.7\n"
    offsets = []
    for number, body in zip(numbers, objects, strict=True):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (number, body)
    xref = len(out)
    entries = [b"%010d 00000 n \n" % offset for offset in offsets]
    out += b"xref\n0 5\n0000000000 65535 f \n" + b"".join(entries[:4])
    if len(entries) > 4:
        out += b"%d 1\n%s" % (numbers[4], entries[4])
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        numbers[-1] + 1,
        xref,
    )
    return out


def _text_image(lines: list[str], size: tuple[int, int] = (1240, 1754)) -> bytes:
    """A PNG of black text on white, like a scanned A4 page at 150 DPI."""
    image = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=40)
    for row, line in enumerate(lines):
        draw.text((120, 150 + row * 90), line, fill="black", font=font)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture
def raw_pdf() -> RawPdf:
    return _raw_pdf


@pytest.fixture
def scanned_pdf() -> Callable[[list[str], str], bytes]:
    """A one-page scan of ``lines`` with an invisible text layer saying ``layer``."""

    def build(lines: list[str], layer: str) -> bytes:
        document = pymupdf.open()
        page = document.new_page()
        page.insert_image(page.rect, stream=_text_image(lines))
        if layer:
            page.insert_text((72, 100), layer, fontsize=11, render_mode=3)
        return document.tobytes()

    return build
