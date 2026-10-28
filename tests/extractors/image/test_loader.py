"""Tests for sugo.extractors.image.loader, including hostile inputs."""

import contextlib
import hashlib
import time
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from PIL import Image

from sugo.extractors.image import loader
from sugo.extractors.image.loader import (
    ImageFormat,
    ImageLoadError,
    ImageTooLargeError,
    UnsupportedImageError,
    decode_image,
    detect_format,
    read_image_file,
)

Encode = Callable[..., bytes]

MAGIC_PREFIXES = (b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff", b"RIFF\x00\x00\x00\x00WEBP")


@pytest.mark.parametrize(
    ("image_format", "expected"),
    [("PNG", ImageFormat.PNG), ("JPEG", ImageFormat.JPEG), ("WEBP", ImageFormat.WEBP)],
)
def test_decodes_supported_formats(
    encode: Encode, image_format: str, expected: ImageFormat
) -> None:
    data = encode(Image.new("RGB", (40, 30), "red"), image_format)
    image = decode_image(data)
    assert image.format is expected
    assert (image.width, image.height) == (40, 30)
    assert image.pixels.shape == (30, 40, 3)
    assert image.pixels.dtype == np.uint8
    assert image.sha256 == hashlib.sha256(data).hexdigest()


def test_pixels_are_read_only(encode: Encode) -> None:
    image = decode_image(encode(Image.new("RGB", (4, 4)), "PNG"))
    with pytest.raises(ValueError, match="read-only"):
        image.pixels[0, 0, 0] = 1


def test_format_comes_from_content_not_extension(encode: Encode, tmp_path: Path) -> None:
    path = tmp_path / "picture.jpg"
    path.write_bytes(encode(Image.new("RGB", (8, 8)), "PNG"))
    assert read_image_file(path).format is ImageFormat.PNG


@pytest.mark.parametrize("image_format", ["GIF", "BMP", "TIFF"])
def test_other_image_formats_are_unsupported(encode: Encode, image_format: str) -> None:
    with pytest.raises(UnsupportedImageError):
        decode_image(encode(Image.new("RGB", (8, 8)), image_format))


@pytest.mark.parametrize("data", [b"", b"hello", b"%PDF-1.7\n", b"PK\x03\x04zip"])
def test_non_images_are_unsupported(data: bytes) -> None:
    with pytest.raises(UnsupportedImageError):
        detect_format(data)


def test_truncated_image_is_reported_as_corrupt(encode: Encode) -> None:
    data = encode(Image.effect_noise((200, 200), 64).convert("RGB"), "PNG")
    with pytest.raises(ImageLoadError, match="corrupt"):
        decode_image(data[: len(data) // 2])


@pytest.mark.parametrize(
    ("width", "height"),
    [
        (8_000, 8_000),  # 64 MP: above Sugo's limit, below Pillow's own guard
        (10_000, 10_000),  # 100 MP: Pillow's warning range, made fatal
        (100_000, 100_000),  # 30 GB once decoded: Pillow's error range
    ],
)
def test_huge_declared_size_is_refused_before_decoding(
    png_header_only: Callable[[int, int], bytes], width: int, height: int
) -> None:
    # A file of about 50 bytes that only declares its size in the header.
    data = png_header_only(width, height)
    start = time.perf_counter()
    with pytest.raises(ImageTooLargeError):
        decode_image(data)
    assert time.perf_counter() - start < 1.0


def test_image_just_above_pixel_limit_is_refused(
    png_header_only: Callable[[int, int], bytes], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(loader, "MAX_IMAGE_PIXELS", 100)
    with pytest.raises(ImageTooLargeError):
        decode_image(png_header_only(11, 10))


def test_oversized_file_is_refused_without_reading_it_all(
    encode: Encode, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(loader, "MAX_IMAGE_FILE_BYTES", 1000)
    path = tmp_path / "big.png"
    path.write_bytes(encode(Image.effect_noise((300, 300), 64).convert("RGB"), "PNG"))
    with pytest.raises(ImageTooLargeError):
        read_image_file(path)


def test_animated_images_are_unsupported(encode: Encode) -> None:
    frames = [Image.new("RGB", (16, 16), colour) for colour in ("red", "blue")]
    data = encode(frames[0], "WEBP", save_all=True, append_images=frames[1:])
    with pytest.raises(UnsupportedImageError, match="animated"):
        decode_image(data)


def test_transparency_is_composited_on_white(encode: Encode) -> None:
    image = Image.new("RGBA", (4, 4), (0, 0, 0, 0))
    image.putpixel((0, 0), (255, 0, 0, 255))
    pixels = decode_image(encode(image, "PNG")).pixels
    assert tuple(pixels[0, 0]) == (255, 0, 0)
    assert tuple(pixels[3, 3]) == (255, 255, 255)


def test_palette_transparency_is_composited_on_white(encode: Encode) -> None:
    image = Image.new("P", (4, 4), 0)
    image.putpalette([0, 0, 0, 255, 0, 0])
    image.putpixel((0, 0), 1)
    pixels = decode_image(encode(image, "PNG", transparency=0)).pixels
    assert tuple(pixels[0, 0]) == (255, 0, 0)
    assert tuple(pixels[1, 1]) == (255, 255, 255)


def test_sixteen_bit_greyscale_keeps_its_tones(encode: Encode) -> None:
    image = Image.fromarray(np.full((4, 4), 0x8000, dtype=np.uint16))
    pixels = decode_image(encode(image, "PNG")).pixels
    assert tuple(pixels[0, 0]) == (0x80, 0x80, 0x80)


def test_cmyk_jpeg_becomes_rgb(encode: Encode) -> None:
    pixels = decode_image(encode(Image.new("CMYK", (8, 8), (0, 0, 0, 0)), "JPEG")).pixels
    assert pixels.shape == (8, 8, 3)


def test_exif_orientation_is_applied(encode: Encode) -> None:
    # Orientation 6: the camera was rotated, so viewers turn the image 90 degrees.
    exif = Image.Exif()
    exif[0x0112] = 6
    image = decode_image(encode(Image.new("RGB", (40, 10)), "JPEG", exif=exif))
    assert (image.width, image.height) == (10, 40)


@pytest.mark.invariant
def test_errors_never_mention_the_file_name(tmp_path: Path) -> None:
    # Principle 11: a file name can itself be sensitive.
    path = tmp_path / "secret-client-name.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\nnot really")
    with pytest.raises(ImageLoadError) as caught:
        read_image_file(path)
    assert "secret-client-name" not in str(caught.value)


@settings(max_examples=300)
@given(prefix=st.sampled_from(MAGIC_PREFIXES), body=st.binary(max_size=2048))
def test_arbitrary_bytes_only_raise_image_errors(prefix: bytes, body: bytes) -> None:
    # Hostile input must fail with Sugo's own errors, never crash with another type.
    with contextlib.suppress(ImageLoadError):
        decode_image(prefix + body)
