"""Tests for the Brotli guard: every way of naming Brotli is refused, real PDFs pass."""

import time
from collections.abc import Callable

import pymupdf
import pytest

from sugo.extractors.pymupdf.guard import names_brotli, raw_problem

RawPdf = Callable[..., bytes]


@pytest.mark.parametrize(
    "entry",
    [
        b"/Filter /BrotliDecode",
        b"/Filter /Br#6ftliDecode",
        b"/Filter [/FlateDecode /BrotliDecode]",
        b"/F#69lter /Br",
    ],
)
def test_brotli_stream_filter_is_refused(raw_pdf: RawPdf, entry: bytes) -> None:
    problem = raw_problem(raw_pdf(entry))
    assert problem is not None
    assert "Brotli" in problem


@pytest.mark.parametrize(
    "entry",
    [
        b"/Filter 5 0 R",
        b"/Filter [/FlateDecode 5 0 R]",
        b"/Filter %comment\n5 %c\n0\nR",
        b"/Filter\x005\x000 R",
    ],
)
def test_indirect_stream_filter_is_refused(raw_pdf: RawPdf, entry: bytes) -> None:
    # The referenced name could hide in compressed data, out of the guard's sight.
    problem = raw_problem(raw_pdf(entry, extra=b"/FlateDecode"))
    assert problem is not None
    assert "indirectly" in problem


def test_ordinary_pdfs_pass(raw_pdf: RawPdf) -> None:
    document = pymupdf.open()
    document.new_page().insert_text((72, 72), "Brotli is a bread, /Brioche too")
    assert raw_problem(document.tobytes(garbage=3, deflate=True)) is None
    assert raw_problem(raw_pdf(b"/Filter /FlateDecode")) is None
    assert raw_problem(raw_pdf(b"/Filter [/ASCIIHexDecode /FlateDecode]")) is None


def test_inline_image_abbreviation_is_recognised() -> None:
    assert names_brotli(b"BI /W 1 /H 1 /F /Br ID x EI")
    assert names_brotli(b"BI /F [/AHx /Br] ID")
    assert not names_brotli(b"/Brioche /Bread /BR")


@pytest.mark.parametrize(
    "hostile",
    [
        b"%" * 200_000,
        b"/Filter [" * 50_000,
        b"/Filter " + b"% x\n" * 50_000,
        b"/Filter [" + b"1 " * 100_000,
    ],
)
def test_hostile_bytes_are_scanned_in_linear_time(hostile: bytes) -> None:
    # Regular expressions that backtrack could be stalled for hours by such input.
    start = time.perf_counter()
    raw_problem(b"%PDF-1.7\n" + hostile)
    assert time.perf_counter() - start < 2.0
