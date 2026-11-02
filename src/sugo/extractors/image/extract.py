"""Turn an image into one IR page: decode, classify, preprocess, OCR, layout.

Blank images skip OCR entirely and yield a page without blocks. Pages of
scanned PDFs enter after decoding, as pixels rendered by the PDF extractor.
"""

from sugo.core.models import Page
from sugo.extractors.image.classifier import ImageKind, classify
from sugo.extractors.image.layout import build_page
from sugo.extractors.image.loader import LoadedImage, decode_image
from sugo.extractors.image.ocr_engine import ENGINE_NAME, OcrEngine
from sugo.extractors.image.preprocess import preprocess


def extract_page(data: bytes, engine: OcrEngine) -> Page:
    """Extract the text of an image as an IR page.

    Raises:
        sugo.extractors.image.loader.ImageLoadError: If the data is not a usable image.
    """
    return extract_image(decode_image(data), engine)


def extract_image(
    image: LoadedImage, engine: OcrEngine, *, index: int = 0, document_page: bool = False
) -> Page:
    """Extract the text of decoded image pixels as the IR page at ``index``.

    A ``document_page`` (a scanned PDF page) never gets screenshot rules: its
    flat white background would pass for a screen, and a contract's top line
    must not be read as a status bar.
    """
    classification = classify(image)
    lines = (
        []
        if classification.kind is ImageKind.BLANK
        else engine.read(preprocess(image, classification))
    )
    return build_page(
        lines,
        width=image.width,
        height=image.height,
        origin_engine=ENGINE_NAME,
        screenshot=classification.kind is ImageKind.SCREENSHOT and not document_page,
        index=index,
    )
