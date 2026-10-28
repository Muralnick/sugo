"""Read untrusted image files safely into an RGB pixel array.

Images arrive from users, clipboards and archives, so every file is treated as
hostile until proven otherwise:

- the size is capped before the file is read in full;
- the format comes from the file's magic bytes, never from its extension, and
  only PNG, JPEG and WEBP are accepted (v0.1 scope);
- the pixel count is checked from the header before any pixel is decoded, so a
  small file declaring a huge image (a decompression bomb) is refused cheaply;
- Pillow is restricted to the detected format, so a file cannot steer it into
  another, less hardened decoder.

Error messages never contain file names (principle 11).
"""

import hashlib
import warnings
from dataclasses import dataclass
from enum import StrEnum
from io import BytesIO
from pathlib import Path
from typing import ClassVar

import numpy as np
import numpy.typing as npt
from PIL import Image, ImageOps

from sugo.core.constants import MAX_IMAGE_FILE_BYTES, MAX_IMAGE_PIXELS

RgbArray = npt.NDArray[np.uint8]

# Bits dropped to turn a 16-bit sample into an 8-bit one.
_SIXTEEN_TO_EIGHT_BITS = 8
_WHITE = (255, 255, 255, 255)


class ImageFormat(StrEnum):
    """Image formats accepted in v0.1 (ROADMAP.md)."""

    PNG = "PNG"
    JPEG = "JPEG"
    WEBP = "WEBP"


class ImageLoadError(ValueError):
    """The file is not a readable image."""

    code: ClassVar[str] = "IMAGE_INVALID"


class UnsupportedImageError(ImageLoadError):
    """The file is an image Sugo does not handle (format, animation)."""

    code: ClassVar[str] = "IMAGE_UNSUPPORTED"


class ImageTooLargeError(ImageLoadError):
    """The file or its decoded pixels exceed the safety limits."""

    code: ClassVar[str] = "IMAGE_TOO_LARGE"


@dataclass(frozen=True)
class LoadedImage:
    """A decoded image: read-only 8-bit RGB pixels, height x width x 3."""

    pixels: RgbArray
    format: ImageFormat
    # Hash of the original file bytes, for provenance and caching (principle 5).
    sha256: str

    @property
    def width(self) -> int:
        """Width in pixels."""
        return int(self.pixels.shape[1])

    @property
    def height(self) -> int:
        """Height in pixels."""
        return int(self.pixels.shape[0])


def detect_format(data: bytes) -> ImageFormat:
    """Identify the image format from its magic bytes.

    Raises:
        UnsupportedImageError: If the bytes are not PNG, JPEG or WEBP.
    """
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ImageFormat.PNG
    if data.startswith(b"\xff\xd8\xff"):
        return ImageFormat.JPEG
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ImageFormat.WEBP
    raise UnsupportedImageError("not a PNG, JPEG or WEBP image")


def read_image_file(path: Path) -> LoadedImage:
    """Read and decode an image file.

    Raises:
        ImageTooLargeError: If the file or the image exceeds the limits.
        UnsupportedImageError: If the format is not supported.
        ImageLoadError: If the file is corrupt or truncated.
        OSError: If the file cannot be read.
    """
    with path.open("rb") as file:
        # One byte more than the limit tells "too large" apart from "exactly the limit".
        data = file.read(MAX_IMAGE_FILE_BYTES + 1)
    return decode_image(data)


def decode_image(data: bytes) -> LoadedImage:
    """Decode image bytes into RGB pixels, applying EXIF orientation.

    Transparent areas are composited onto white, as they appear in viewers.

    Raises:
        ImageTooLargeError: If the data or the image exceeds the limits.
        UnsupportedImageError: If the format is not supported or is animated.
        ImageLoadError: If the data is corrupt or truncated.
    """
    if len(data) > MAX_IMAGE_FILE_BYTES:
        raise ImageTooLargeError(f"image file exceeds {MAX_IMAGE_FILE_BYTES} bytes")
    image_format = detect_format(data)
    try:
        with warnings.catch_warnings():
            # Second guard: Pillow only warns between its own limit and twice that.
            # Sugo's lower MAX_IMAGE_PIXELS check below normally fires first.
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data), formats=[image_format.value]) as image:
                width, height = image.size
                if width * height > MAX_IMAGE_PIXELS:
                    raise ImageTooLargeError(f"image exceeds {MAX_IMAGE_PIXELS} pixels")
                if getattr(image, "n_frames", 1) > 1:
                    raise UnsupportedImageError("animated images are not supported")
                rgb = _to_rgb(ImageOps.exif_transpose(image))
    except ImageLoadError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
        # Pillow's own bomb guard can trigger first, while opening the header.
        raise ImageTooLargeError(f"image exceeds {MAX_IMAGE_PIXELS} pixels") from error
    except (OSError, ValueError, SyntaxError) as error:
        # Pillow reports corrupt data through several exception types.
        raise ImageLoadError("image data is corrupt or truncated") from error
    pixels = np.asarray(rgb, dtype=np.uint8).copy()
    pixels.setflags(write=False)
    return LoadedImage(pixels=pixels, format=image_format, sha256=hashlib.sha256(data).hexdigest())


def _to_rgb(image: Image.Image) -> Image.Image:
    """Convert any decoded mode to 8-bit RGB."""
    if image.mode in {"I;16", "I;16B", "I;16L", "I"}:
        # 16-bit greyscale PNG: keep the high byte instead of letting convert() clip.
        high = (np.asarray(image, dtype=np.uint32) >> _SIXTEEN_TO_EIGHT_BITS).astype(np.uint8)
        return Image.fromarray(np.dstack([high, high, high]))
    if image.mode in {"RGBA", "LA", "PA"} or "transparency" in image.info:
        rgba = image.convert("RGBA")
        return Image.alpha_composite(Image.new("RGBA", rgba.size, _WHITE), rgba).convert("RGB")
    return image.convert("RGB")
