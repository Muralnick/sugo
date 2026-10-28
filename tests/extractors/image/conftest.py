"""Fixtures that build test images in memory; no files from outside the repository."""

import struct
import zlib
from collections.abc import Callable
from io import BytesIO

import pytest
from PIL import Image, ImageDraw, ImageFont


def _encode(image: Image.Image, image_format: str, **options: object) -> bytes:
    """Encode a Pillow image into file bytes."""
    buffer = BytesIO()
    image.save(buffer, format=image_format, **options)
    return buffer.getvalue()


def _screenshot(*, dark: bool = False, size: tuple[int, int] = (900, 600)) -> Image.Image:
    """A synthetic UI screenshot: flat background, a toolbar and lines of text."""
    background, foreground = ("#1e1e1e", "#e6e6e6") if dark else ("#ffffff", "#202020")
    image = Image.new("RGB", size, background)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, size[0], 40), fill="#3a3a3a" if dark else "#f0f0f0")
    font = ImageFont.load_default(size=22)
    for row in range(8):
        draw.text(
            (30, 70 + row * 60),
            f"Line {row}: the contract may be withdrawn.",
            fill=foreground,
            font=font,
        )
    return image


def _png_header_only(width: int, height: int) -> bytes:
    """A PNG that declares a size in its header but carries no pixel data."""

    def chunk(kind: bytes, payload: bytes) -> bytes:
        crc = zlib.crc32(kind + payload) & 0xFFFFFFFF
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", crc)

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IEND", b"")


@pytest.fixture
def encode() -> Callable[..., bytes]:
    return _encode


@pytest.fixture
def screenshot() -> Callable[..., Image.Image]:
    return _screenshot


@pytest.fixture
def png_header_only() -> Callable[[int, int], bytes]:
    return _png_header_only
