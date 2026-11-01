"""Pictures inside Office files, read with OCR in Sugo's own process (ADR-054).

The worker marks each picture not converted and names the package part that
holds it, how much of it is cropped away and the height it is shown at; it
never loads the image stack. Here the part is read with the package's
limits, counted while decompressing, recognised by its content and, if it is
a PNG, JPEG or WEBP image, read with the same OCR pipeline and the same pixel
and size limits as an image file.

The text found takes the picture's place on the page, as paragraphs and the
other block types the image layout gives, never as headings of the document.
On a slide it keeps its place inside the picture; elsewhere it has no
position, since a picture's own coordinates are not the page's.

What a person cannot see stays in the IR flagged ``hidden``, as for text: the
text of a hidden picture, text in the part of a picture cropped away, and
text a picture shows under 2 pt. A picture under 32 x 32 pixels is
decoration: flagged ``decorative``, so a cleaner removes it with a reason.

Anything else stays marked not converted, never guessed: other formats (EMF,
WMF, GIF, TIFF), damaged or oversized images, pictures without text, pictures
past the first ``OFFICE_MAX_PICTURES`` read in a document, and every picture
when ``sugo[lite]`` is not installed. A picture used many times is read once.
"""

import hashlib
import logging
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING

from sugo.core.constants import (
    OFFICE_DECORATION_PIXELS,
    OFFICE_MAX_PICTURES,
    OFFICE_MIN_VISIBLE_POINTS,
)
from sugo.core.models import BBox, Block, BlockFlag, BlockType, Page
from sugo.extractors.office.package import Package, Picture
from sugo.extractors.office.xml_reader import Refusal

if TYPE_CHECKING:
    from sugo.extractors.image.ocr_engine import OcrEngine

_log = logging.getLogger(__name__)
_UNCROPPED = (0.0, 0.0, 0.0, 0.0)


class Pictures:
    """Reads the pictures of one document, each at most once."""

    def __init__(self, data: bytes, ocr: Callable[[], "OcrEngine"]) -> None:
        self._data = data
        self._ocr = ocr
        self._package: Package | None = None
        self._unreadable = False
        # Blocks read from each picture, in the picture's own coordinates, by
        # the SHA-256 of its bytes.
        self._read: dict[str, tuple[Block, ...]] = {}

    def apply(self, page: Page, pictures: Mapping[str, Picture]) -> Page:
        """The page with each picture block in ``pictures`` (by block id) read with OCR."""
        blocks: list[Block] = []
        changed = False
        for block in page.blocks:
            picture = pictures.get(block.id)
            found = [block] if picture is None else self._picture(block, picture)
            changed |= found != [block]
            blocks.extend(found)
        if not changed:
            return page
        renumbered = tuple(
            _with(block, id=f"b{number}", reading_order=number)
            for number, block in enumerate(blocks)
        )
        return page.model_validate({**page.model_dump(), "blocks": renumbered})

    def _picture(self, block: Block, picture: Picture) -> list[Block]:
        data = self._bytes(picture.part)
        if data is None:
            return [block]
        try:
            from sugo.extractors.image.extract import extract_image
            from sugo.extractors.image.loader import ImageLoadError, decode_image, image_size
            from sugo.extractors.image.ocr_engine import ModelIntegrityError
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
            found = ()
            try:
                found = extract_image(decode_image(data), self._ocr()).blocks
            except ImageLoadError:
                pass
            except ModelIntegrityError:
                # A tampered OCR model is never worked around.
                raise
            except Exception:  # noqa: BLE001  (one picture must not end the document)
                _log.warning("a picture inside an Office file could not be read with OCR")
            self._read[key] = found
        if not any(item.text.strip() for item in found):
            return [block]
        return [_placed(item, block, picture) for item in found]

    def _bytes(self, part: str) -> bytes | None:
        """The part's bytes, within the package's limits; None if it cannot be read."""
        if self._unreadable:
            return None
        try:
            if self._package is None:
                self._package = Package(self._data)
            return self._package.read(part)
        except Refusal as refusal:
            # A package refused, or whose limits are used up, gives no more pictures.
            self._unreadable = refusal.code == "OFFICE_TOO_LARGE" or self._package is None
            return None


def _placed(item: Block, block: Block, picture: Picture) -> Block:
    """A block read from a picture, put where the picture is and flagged as a person sees it."""
    hidden = BlockFlag.HIDDEN in block.flags or not _visible(item, picture)
    bbox = None
    if item.bbox is not None and block.bbox is not None and _shown(picture.crop):
        bbox = _inside(_uncropped(item.bbox, picture.crop), block.bbox)
    changes: dict[str, object] = {
        "bbox": bbox,
        "flags": (*item.flags, BlockFlag.HIDDEN) if hidden else item.flags,
    }
    if item.type is BlockType.HEADING:
        # A picture's large text is not a heading of the document.
        changes |= {"type": BlockType.PARAGRAPH, "heading_level": None}
    return _with(item, **changes)


def _visible(item: Block, picture: Picture) -> bool:
    """Whether a person sees the block: inside the part shown, and not too small to read."""
    box = item.bbox
    if box is None:
        # Nothing to judge it by: seen only if nothing of the picture is hidden.
        return picture.crop == _UNCROPPED and picture.height is None
    left, top, right, bottom = picture.crop
    if not _shown(picture.crop):
        return False
    centre_x, centre_y = (box.x0 + box.x1) / 2, (box.y0 + box.y1) / 2
    if not (left <= centre_x <= 1.0 - right and top <= centre_y <= 1.0 - bottom):
        return False
    if picture.height is None:
        return True
    # The height of one line on the page: its share of the part shown.
    line = (box.y1 - box.y0) / (item.text.count("\n") + 1) / (1.0 - top - bottom)
    return line * picture.height >= OFFICE_MIN_VISIBLE_POINTS


def _shown(crop: tuple[float, float, float, float]) -> bool:
    """Whether any of the picture is left once cropped."""
    left, top, right, bottom = crop
    return left + right < 1.0 and top + bottom < 1.0


def _with(block: Block, **changes: object) -> Block:
    return block.model_validate({**block.model_dump(), **changes})


def _unit(value: float) -> float:
    # Rounding must not push a corner past the page.
    return min(max(value, 0.0), 1.0)


def _uncropped(box: BBox, crop: tuple[float, float, float, float]) -> BBox:
    """A box given in the whole picture, moved into the part of it that is shown."""
    left, top, right, bottom = crop
    width, height = 1.0 - left - right, 1.0 - top - bottom
    return BBox(
        x0=_unit((box.x0 - left) / width),
        y0=_unit((box.y0 - top) / height),
        x1=_unit((box.x1 - left) / width),
        y1=_unit((box.y1 - top) / height),
    )


def _inside(box: BBox, picture: BBox) -> BBox:
    """A box given within the picture, placed on the page."""
    width, height = picture.x1 - picture.x0, picture.y1 - picture.y0
    return BBox(
        x0=_unit(picture.x0 + box.x0 * width),
        y0=_unit(picture.y0 + box.y0 * height),
        x1=_unit(picture.x0 + box.x1 * width),
        y1=_unit(picture.y0 + box.y1 * height),
    )


def is_picture(block: Block) -> bool:
    """Whether a block can stand for a picture: an image marked not converted."""
    return block.type is BlockType.IMAGE and BlockFlag.ILLEGIBLE in block.flags
