"""Pictures inside Office files, read with OCR in Sugo's own process (ADR-054).

The worker marks each picture not converted and names the package part that
holds it; it never loads the image stack. Here the part is read with the
package's limits, counted while decompressing, recognised by its content and,
if it is a PNG, JPEG or WEBP image, read with the same OCR pipeline and the
same pixel and size limits as an image file.

The text found takes the picture's place on the page, with its flags: the
text of a hidden picture stays hidden. On a slide, the text keeps its place
inside the picture; elsewhere it has no position, since a picture's own
coordinates are not the page's. A picture under 32 x 32 pixels is decoration:
flagged ``decorative``, so a cleaner removes it with a reason.

Anything else stays marked not converted, never guessed: other formats (EMF,
WMF, GIF, TIFF), damaged or oversized images, pictures without text, pictures
past the first ``OFFICE_MAX_PICTURES`` read in a document, and every picture
when ``sugo[lite]`` is not installed. A picture used many times is read once.
"""

import hashlib
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING

from sugo.core.constants import OFFICE_DECORATION_PIXELS, OFFICE_MAX_PICTURES
from sugo.core.models import BBox, Block, BlockFlag, BlockType, Page
from sugo.extractors.office.package import Package
from sugo.extractors.office.xml_reader import Refusal

if TYPE_CHECKING:
    from sugo.extractors.image.ocr_engine import OcrEngine


class Pictures:
    """Reads the pictures of one document, each at most once."""

    def __init__(self, data: bytes, ocr: Callable[[], "OcrEngine"]) -> None:
        self._data = data
        self._ocr = ocr
        self._package: Package | None = None
        self._unreadable = False
        # Blocks read from each picture, by the SHA-256 of its bytes.
        self._read: dict[str, tuple[Block, ...]] = {}

    def apply(self, page: Page, parts: Mapping[str, str]) -> Page:
        """The page with each picture block in ``parts`` (block id -> part) read with OCR."""
        if not parts:
            return page
        blocks: list[Block] = []
        for block in page.blocks:
            part = parts.get(block.id)
            blocks.extend([block] if part is None else self._picture(block, part))
        if len(blocks) == len(page.blocks) and all(
            new is old for new, old in zip(blocks, page.blocks, strict=True)
        ):
            return page
        renumbered = tuple(
            block.model_validate(
                {**block.model_dump(), "id": f"b{number}", "reading_order": number}
            )
            for number, block in enumerate(blocks)
        )
        return page.model_validate({**page.model_dump(), "blocks": renumbered})

    def _picture(self, block: Block, part: str) -> list[Block]:
        data = self._bytes(part)
        if data is None:
            return [block]
        try:
            from sugo.extractors.image.extract import extract_image
            from sugo.extractors.image.loader import ImageLoadError, decode_image, image_size
        except ImportError:
            # Without sugo[lite], pictures stay marked not converted.
            return [block]
        try:
            width, height = image_size(data)
        except ImageLoadError:
            return [block]
        if width < OFFICE_DECORATION_PIXELS and height < OFFICE_DECORATION_PIXELS:
            return [_with(block, flags=(*block.flags, BlockFlag.DECORATIVE))]
        key = hashlib.sha256(data).hexdigest()
        found = self._read.get(key)
        if found is None:
            if len(self._read) >= OFFICE_MAX_PICTURES:
                return [block]
            try:
                found = extract_image(decode_image(data), self._ocr()).blocks
            except ImageLoadError:
                found = ()
            self._read[key] = found
        if not any(item.text.strip() for item in found):
            return [block]
        hidden = (BlockFlag.HIDDEN,) if BlockFlag.HIDDEN in block.flags else ()
        return [
            _with(item, bbox=_inside(item.bbox, block.bbox), flags=(*item.flags, *hidden))
            for item in found
        ]

    def _bytes(self, part: str) -> bytes | None:
        """The part's bytes, within the package's limits; None if it cannot be read."""
        if self._unreadable:
            return None
        try:
            if self._package is None:
                self._package = Package(self._data)
            return self._package.read(part)
        except Refusal as refusal:
            # A package that is refused, or whose limits are used up, gives no more pictures.
            self._unreadable = refusal.code == "OFFICE_TOO_LARGE" or self._package is None
            return None


def _with(block: Block, **changes: object) -> Block:
    return block.model_validate({**block.model_dump(), **changes})


def _inside(box: BBox | None, picture: BBox | None) -> BBox | None:
    """A box given within the picture, placed on the page; None if the picture has no place."""
    if box is None or picture is None:
        return None
    width, height = picture.x1 - picture.x0, picture.y1 - picture.y0

    def unit(value: float) -> float:
        # Rounding must not push a corner past the page.
        return min(max(value, 0.0), 1.0)

    return BBox(
        x0=unit(picture.x0 + box.x0 * width),
        y0=unit(picture.y0 + box.y0 * height),
        x1=unit(picture.x0 + box.x1 * width),
        y1=unit(picture.y0 + box.y1 * height),
    )


def is_picture(block: Block) -> bool:
    """Whether a block can stand for a picture: an image marked not converted."""
    return block.type is BlockType.IMAGE and BlockFlag.ILLEGIBLE in block.flags
