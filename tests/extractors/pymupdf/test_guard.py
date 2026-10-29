"""Tests for the Brotli guard: every way of naming Brotli is refused, real PDFs pass."""

import random
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


def test_short_abbreviation_in_binary_data_is_not_brotli() -> None:
    # "/Br" alone occurs by chance in compressed data; only after a filter key it counts.
    noise = b"\x8f/Br \x00\x13#2fBr]\xfe/Brx /Br(" * 1000
    assert raw_problem(b"%PDF-1.7\n" + noise) is None
    assert not names_brotli(noise)
    assert names_brotli(b"/F /Br ")
    assert names_brotli(b"/Filter[/AHx/Br]")


def test_random_binary_data_is_not_refused() -> None:
    # A large compressed file must not be refused by chance (review of PR #13).
    data = random.Random(43).randbytes(16 * 1024 * 1024)  # noqa: S311  (test data)
    assert raw_problem(b"%PDF-1.7\n" + data) is None
