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
# OCR boxes are a few pixels loose: a line may reach this share past a crop
# edge and still be whole.
_EDGE = 0.02


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
        return [piece for item in found for piece in _placed(item, block, picture)]

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


def _placed(item: Block, block: Block, picture: Picture) -> list[Block]:
    """A block read from a picture, put where the picture is and flagged as a person sees it.

    Its lines are judged one by one: a paragraph partly cropped away becomes
    a block of the lines shown and a hidden block of the others.
    """
    pieces = _pieces(item, picture)
    placed = []
    for text, box, seen in pieces:
        hidden = BlockFlag.HIDDEN in block.flags or not seen
        bbox = None
        if box is not None and block.bbox is not None and _shown(picture.crop):
            bbox = _inside(_uncropped(box, picture.crop), block.bbox)
        changes: dict[str, object] = {
            "bbox": bbox,
            "flags": (*item.flags, BlockFlag.HIDDEN) if hidden else item.flags,
        }
        if len(pieces) > 1:
            changes["text"] = text
        if item.type is BlockType.HEADING:
            # A picture's large text is not a heading of the document.
            changes |= {"type": BlockType.PARAGRAPH, "heading_level": None}
        placed.append(_with(item, **changes))
    return placed


def _pieces(item: Block, picture: Picture) -> list[tuple[str, BBox | None, bool]]:
    """The block's runs of lines a person sees or not, with their boxes in the picture."""
    box = item.bbox
    if not _big_enough(picture):
        return [(item.text, box, False)]
    if box is None:
        # Nothing to judge it by: seen only if nothing of the picture is hidden.
        return [(item.text, box, picture.crop == _UNCROPPED and picture.height is None)]
    # Lines of one OCR paragraph are evenly spaced (the layout splits it at
    # wider gaps), so each takes an equal band of the block's height.
    lines = item.text.split("\n") if item.text else [""]
    step = (box.y1 - box.y0) / len(lines)
    runs: list[tuple[list[str], float, float, bool]] = []  # lines, top, bottom, seen
    for number, line in enumerate(lines):
        top, bottom = box.y0 + number * step, box.y0 + (number + 1) * step
        seen = _seen(BBox(x0=box.x0, y0=top, x1=box.x1, y1=bottom), picture)
        if runs and runs[-1][3] == seen:
            runs[-1][0].append(line)
            runs[-1] = (runs[-1][0], runs[-1][1], bottom, seen)
        else:
            runs.append(([line], top, bottom, seen))
    return [
        ("\n".join(run), BBox(x0=box.x0, y0=top, x1=box.x1, y1=bottom), seen)
        for run, top, bottom, seen in runs
    ]


def _big_enough(picture: Picture) -> bool:
    """Whether the picture is shown with any size: no height, or a sliver, hides it all."""
    if picture.height is not None and picture.height <= 0:
        return False
    return picture.width is None or picture.width >= OFFICE_MIN_VISIBLE_POINTS


def _seen(line: BBox, picture: Picture) -> bool:
    """Whether a person sees one line: whole across, its middle not cropped, not too small."""
    left, top, right, bottom = picture.crop
    if not _shown(picture.crop):
        return False
    if line.x0 < left - _EDGE or line.x1 > 1.0 - right + _EDGE:
        return False
    middle = (line.y0 + line.y1) / 2
    if not top <= middle <= 1.0 - bottom:
        return False
    if picture.height is None:
        return True
    # The line's height on the page: its share of the part shown.
    return (line.y1 - line.y0) / (1.0 - top - bottom) * picture.height >= OFFICE_MIN_VISIBLE_POINTS


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
