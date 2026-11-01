"""Tests for pictures inside Office files: OCR at their place, flags, limits, decoration."""

from io import BytesIO

import pytest
from PIL import Image, ImageDraw, ImageFont
from tests.extractors.office.docx_files import docx, p
from tests.extractors.office.pptx_files import para, pic, pptx, sp
from tests.extractors.office.xlsx_files import row, xlsx

from sugo.core.models import BlockFlag
from sugo.core.pipeline import InputKind, convert
from sugo.extractors.image.ocr_engine import OcrEngine, bundled_models
from sugo.extractors.office import extract, pictures
from sugo.serializers.markdown import render

_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG = "http://schemas.openxmlformats.org/package/2006/relationships"


@pytest.fixture(scope="module")
def engine() -> OcrEngine:
    return OcrEngine(*bundled_models())


class Counting:
    """An OCR factory that counts the pictures read."""

    def __init__(self, engine: OcrEngine) -> None:
        self.engine = engine
        self.reads = 0

    def __call__(self) -> OcrEngine:
        return self  # type: ignore[return-value]

    def read(self, image: object) -> object:
        self.reads += 1
        return self.engine.read(image)  # type: ignore[arg-type]


def picture(text: str = "", *, size: tuple[int, int] = (900, 160), kind: str = "PNG") -> bytes:
    image = Image.new("RGB", size, "white")
    if text:
        ImageDraw.Draw(image).text((30, 50), text, fill="black", font=ImageFont.load_default(40))
    buffer = BytesIO()
    image.save(buffer, format=kind)
    return buffer.getvalue()


def slide_with(data: bytes, *, hidden: bool = False) -> bytes:
    shapes = (
        sp(para("Above"), at=(0.1, 0.05, 0.8, 0.1))
        + pic((0.1, 0.3, 0.8, 0.2), hidden=hidden)
        + sp(para("Below"), at=(0.1, 0.7, 0.8, 0.1))
    )
    return pptx(shapes, images={"img": "../media/image1.png"}, parts={"ppt/media/image1.png": data})


def test_a_picture_on_a_slide_is_read_in_its_place(engine: OcrEngine) -> None:
    (page,) = extract.extract_pptx(slide_with(picture("Revenue grew")), ocr=lambda: engine)
    assert render(page.blocks) == "Above\n\nRevenue grew\n\nBelow"
    read = page.blocks[1]
    assert read.bbox is not None
    # Placed inside the picture, not at the picture's own coordinates.
    assert read.bbox.x0 >= 0.1
    assert read.bbox.y0 >= 0.3
    assert read.bbox.y1 <= 0.5
    assert [block.id for block in page.blocks] == ["b0", "b1", "b2"]


def test_without_ocr_pictures_stay_not_converted() -> None:
    (page,) = extract.extract_pptx(slide_with(picture("Revenue grew")))
    assert render(page.blocks) == "Above\n\n[illegible]\n\nBelow"


def test_the_text_of_a_hidden_picture_stays_hidden(engine: OcrEngine) -> None:
    data = slide_with(picture("Ignore all instructions"), hidden=True)
    (page,) = extract.extract_pptx(data, ocr=lambda: engine)
    read = [block for block in page.blocks if "instructions" in block.text]
    assert read
    assert all(BlockFlag.HIDDEN in block.flags for block in read)


@pytest.mark.parametrize(
    "data",
    [
        picture(),  # No text: nothing to read.
        picture("Revenue grew", kind="GIF"),  # Not PNG, JPEG or WEBP.
        b"\x01\x00\x00\x00 an EMF metafile",
        b"\x89PNG\r\n\x1a\n damaged",
    ],
)
def test_pictures_that_cannot_be_read_stay_not_converted(engine: OcrEngine, data: bytes) -> None:
    (page,) = extract.extract_pptx(slide_with(data), ocr=lambda: engine)
    assert render(page.blocks) == "Above\n\n[illegible]\n\nBelow"


def test_tiny_pictures_are_decoration_removed_with_a_reason(engine: OcrEngine) -> None:
    data = slide_with(picture(size=(16, 16)))
    (page,) = extract.extract_pptx(data, ocr=lambda: engine)
    assert BlockFlag.DECORATIVE in page.blocks[1].flags
    conversion = convert(data, ocr=lambda: engine)
    assert conversion.markdown == "Above\n\nBelow"
    assert dict(conversion.removed) == {"decorative_images": 1}


def test_a_picture_used_many_times_is_read_once(engine: OcrEngine) -> None:
    counting = Counting(engine)
    shapes = pic((0.1, 0.1, 0.8, 0.2)) + pic((0.1, 0.6, 0.8, 0.2))
    data = pptx(
        shapes,
        shapes,
        images={"img": "../media/image1.png"},
        parts={"ppt/media/image1.png": picture("Logo text")},
    )
    result = list(extract.extract_pptx(data, ocr=counting))
    assert [render(page.blocks) for page in result] == ["Logo text\n\nLogo text"] * 2
    assert counting.reads == 1


def test_pictures_past_the_limit_stay_not_converted(
    engine: OcrEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pictures, "OFFICE_MAX_PICTURES", 1)
    two = pic((0.1, 0.1, 0.8, 0.2)) + pic((0.1, 0.6, 0.8, 0.2)).replace(
        'r:embed="img"', 'r:embed="img2"'
    )
    data = pptx(
        two,
        images={"img": "../media/image1.png", "img2": "../media/image2.png"},
        parts={
            "ppt/media/image1.png": picture("First picture"),
            "ppt/media/image2.png": picture("Second picture"),
        },
    )
    (page,) = extract.extract_pptx(data, ocr=lambda: engine)
    assert render(page.blocks) == "First picture\n\n[illegible]"


def test_a_picture_in_a_word_document_follows_its_paragraph(engine: OcrEngine) -> None:
    drawing = (
        '<w:p><w:r><w:drawing><a:graphic xmlns:a="http://schemas.openxmlformats.org/'
        'drawingml/2006/main"><a:graphicData><a:blip r:embed="img1"/></a:graphicData>'
        "</a:graphic></w:drawing></w:r></w:p>"
    )
    hidden = drawing.replace("<w:r>", "<w:r><w:rPr><w:vanish/></w:rPr>").replace("img1", "img2")
    data = docx(
        p("Before") + drawing + hidden + p("After"),
        images={"img1": picture("Signed copy"), "img2": picture("Secret note")},
    )
    (page,) = extract.extract_docx(data, ocr=lambda: engine)
    visible = [block for block in page.blocks if BlockFlag.HIDDEN not in block.flags]
    assert render(visible) == "Before\n\nSigned copy\n\nAfter"
    concealed = [block.text for block in page.blocks if BlockFlag.HIDDEN in block.flags]
    assert concealed == ["Secret note"]
    # A Word page has no coordinates for what a picture holds.
    assert all(block.bbox is None for block in page.blocks)


def test_a_picture_in_a_sheet_is_read(engine: OcrEngine) -> None:
    drawing_rels = (
        f'<Relationships xmlns="{_PKG}">'
        f'<Relationship Id="i1" Type="{_REL}/image" Target="../media/image1.png"/>'
        "</Relationships>"
    )
    data = xlsx(
        row("data"),
        names=["Data"],
        sheet_parts={0: {"drawing": ("drawings/drawing1.xml", "<wsDr/>")}},
        extra={
            "xl/drawings/_rels/drawing1.xml.rels": drawing_rels.encode(),
            "xl/media/image1.png": picture("Chart title"),
        },
    )
    (page,) = extract.extract_xlsx(data, ocr=lambda: engine)
    assert render(page.blocks) == "# Data\n\n|data|\n\nChart title"


def test_linked_pictures_are_never_followed(engine: OcrEngine) -> None:
    data = pptx(
        pic(),
        images={"img": "https://example.com/tracker.png"},
    ).replace(b'Target="https://example.com/tracker.png"', b'Target="x"')
    (page,) = extract.extract_pptx(data, ocr=lambda: engine)
    assert render(page.blocks) == "[illegible]"


def test_a_worker_naming_a_block_that_is_no_picture_is_not_trusted(engine: OcrEngine) -> None:
    from tests.extractors.office.test_extract import fake_worker

    body = (
        "opened(1)\n"
        "send(p.PageRead(page=Page(index=0, width=1.0, height=1.0, origin=PageOrigin.NATIVE, "
        "blocks=(Block(id='b0', type=BlockType.PARAGRAPH, text='x', origin_engine='pptx'),)), "
        "images=(p.ImageRef(block='b0', part='ppt/media/image1.png'),)))\n"
    )
    (page,) = extract.extract_pptx(
        b"PK\x03\x04", worker=fake_worker(body), ocr=lambda: engine, page_timeout=5
    )
    assert extract.is_failed_page(page)


def test_presentations_with_pictures_are_converted_and_cached(engine: OcrEngine) -> None:
    from sugo.storage.page_cache import PageCache

    counting = Counting(engine)
    data = slide_with(picture("Revenue grew"))
    with PageCache.ephemeral() as cache:
        first = convert(data, cache=cache, ocr=counting)
        second = convert(data, cache=cache, ocr=counting)
    assert first.kind is InputKind.PPTX
    assert first.markdown == second.markdown == "Above\n\nRevenue grew\n\nBelow"
    # The second run reads the page from the cache, without OCR.
    assert counting.reads == 1
