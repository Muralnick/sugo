"""Turn image bytes into one IR page: decode, classify, preprocess, OCR, layout.

Blank images skip OCR entirely and yield a page without blocks.
"""

from sugo.core.models import Page
from sugo.extractors.image.classifier import ImageKind, classify
from sugo.extractors.image.layout import build_page
from sugo.extractors.image.loader import decode_image
from sugo.extractors.image.ocr_engine import ENGINE_NAME, OcrEngine
from sugo.extractors.image.preprocess import preprocess


def extract_page(data: bytes, engine: OcrEngine) -> Page:
    """Extract the text of an image as an IR page.

    Raises:
        sugo.extractors.image.loader.ImageLoadError: If the data is not a usable image.
    """
    image = decode_image(data)
    classification = classify(image)
    lines = (
        []
        if classification.kind is ImageKind.BLANK
        else engine.read(preprocess(image, classification))
    )
    return build_page(lines, width=image.width, height=image.height, origin_engine=ENGINE_NAME)
