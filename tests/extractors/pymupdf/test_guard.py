"""Tests for the Brotli guard: every way of naming Brotli is refused, real PDFs pass."""

import random
import time
from collections.abc import Callable

import pymupdf
import pytest

from sugo.extractors.pymupdf.guard import BROTLI_REFUSAL, names_brotli, raw_problem, scan

RawPdf = Callable[..., bytes]


@pytest.mark.parametrize(
    "entry",
    [
        b"/Filter /BrotliDecode",
        b"/Filter /Br#6ftliDecode",
        b"/Filter [/FlateDecode /BrotliDecode]",
        b"/F#69lter /Br",
        b"/Filter [ %]\n /Br]",
        b"/Filter [ (]) /Br]",
        b"/Filter [" + b" " * 600 + b"/Br]",
        # MuPDF reads "/A#28" as the name "A(", not as a name and an open string.
        b"/Filter [/A#28 /Br]",
        b"/F [/A#5D/Br]",
    ],
)
def test_brotli_stream_filter_is_refused(raw_pdf: RawPdf, entry: bytes) -> None:
    assert raw_problem(raw_pdf(entry)) == BROTLI_REFUSAL


def test_brotli_name_anywhere_refuses_the_file() -> None:
    # Matching MuPDF's parser exactly proved fragile; the name has no other use.
    assert raw_problem(b"%PDF-1.7\n1 0 obj\n[(text) /Br]\nendobj\n") == BROTLI_REFUSAL
    assert raw_problem(b"%PDF-1.7\n1 0 obj\n/B#72\nendobj\n") == BROTLI_REFUSAL
    assert names_brotli(b"x/BrotliDecode(")
    assert not names_brotli(b"/Brioche /Bread /BR /Br#41 /Bro")


@pytest.mark.parametrize(
    "entry",
    [
        b"/Filter 5 0 R",
        b"/Filter [/FlateDecode 5 0 R]",
        b"/Filter %comment\n5 %c\n0\nR",
        b"/Filter\x005\x000 R",
        # MuPDF's lexer accepts signs, and ends a number at a sign or a letter:
        # "5+0R" is "5 0 R". Only names are allowed, so none needs recognising.
        b"/Filter +5 0 R",
        b"/Filter 5+0R",
        b"/Filter [5 0R]",
        b"/Filter --5 0 R",
        b"/Filter [ [/FlateDecode] ]",
        b"/Filter (x)",
    ],
)
def test_stream_filter_that_is_not_a_name_is_refused(raw_pdf: RawPdf, entry: bytes) -> None:
    # A referenced name could hide in compressed data, out of the guard's sight.
    problem = raw_problem(raw_pdf(entry, extra=b"/FlateDecode"))
    assert problem is not None
    assert "cannot check" in problem


@pytest.mark.parametrize("entry", [b"/F 5 0 R", b"/F [/FlateDecode 5 0 R]", b"/F +5 0 R"])
def test_short_key_reference_in_a_stream_dictionary_is_refused(
    raw_pdf: RawPdf, entry: bytes
) -> None:
    # MuPDF decodes object streams while opening the file, before the worker
    # can check anything, so the raw layer must refuse these itself.
    problem = raw_problem(raw_pdf(entry, extra=b"/FlateDecode"))
    assert problem is not None
    assert "cannot check" in problem


@pytest.mark.parametrize("keyword", [b"stream \n", b"stream\t", b"stream%\n", b"stream<"])
def test_stream_keyword_is_recognised_as_mupdf_reads_it(keyword: bytes) -> None:
    data = b"%PDF-1.7\n4 0 obj\n<< /Type /ObjStm /F 5 0 R /Length 1 >>\n" + keyword + b"x"
    assert raw_problem(data) is not None


def test_file_specification_is_not_refused() -> None:
    # Attachments, links and annotations use "/F" in dictionaries no stream follows.
    data = b"%PDF-1.7\n1 0 obj\n<< /EF << /F 5 0 R >> /Type /Filespec /F (a.txt) >>\nendobj\n"
    assert raw_problem(data) is None
    assert raw_problem(b"%PDF-1.7\n2 0 obj\n<< /Type /Annot /F 4 >>\nendobj\n") is None


def test_ordinary_pdfs_pass(raw_pdf: RawPdf) -> None:
    document = pymupdf.open()
    document.new_page().insert_text((72, 72), "Brotli is a bread, /Brioche too")
    assert raw_problem(document.tobytes(garbage=3, deflate=True)) is None
    assert raw_problem(raw_pdf(b"/Filter /FlateDecode")) is None
    assert raw_problem(raw_pdf(b"/Filter [/ASCIIHexDecode /FlateDecode]")) is None


def test_filter_keys_in_image_pixels() -> None:
    # In pixels "/Br" occurs by chance; there only a name after a filter key counts.
    noise = b"\x8f/Br \x00\x13#2fBr]\xfe/Brx /Br(" * 1000
    assert not scan(noise).brotli
    assert scan(b"BI /W 1 /H 1 /F /Br ID x EI").brotli
    assert scan(b"BI /W 1 /H 1 /F [ %]\n/Br] ID x EI").brotli
    assert scan(rb"BI /W 1 /H 1 /F [ (a\) ]) /Br] ID x EI").brotli
    assert scan(b"BI /W 1 /H 1 /F [/A#28 /Br] ID x EI").brotli
    assert not scan(b"/F#20 /Br /Fx /Br").brotli  # "F " and "Fx" are not filter keys


def test_random_binary_data_is_not_refused() -> None:
    # A large compressed file must not be refused by chance (review of PR #13).
    data = random.Random(43).randbytes(16 * 1024 * 1024)  # noqa: S311  (test data)
    assert raw_problem(b"%PDF-1.7\n" + data) is None


@pytest.mark.parametrize(
    "hostile",
    [
        b"%" * 200_000,
        b"/Filter [" * 50_000,
        b"/Filter " + b"% x\n" * 50_000,
        b"/Filter [" + b"1 " * 100_000,
        b"/F[(" * 100_000,
        b"/F[[" * 100_000,
        b"/Filter[%]\n" * 100_000,
    ],
    # Short IDs: pytest stores the test ID in an environment variable, capped on Windows.
    ids=[
        "percent-signs",
        "nested-arrays",
        "comment-lines",
        "long-array",
        "open-strings",
        "open-arrays",
        "commented-brackets",
    ],
)
def test_hostile_bytes_are_scanned_in_linear_time(hostile: bytes) -> None:
    # Backtracking patterns, or reading every open array to the end, could
    # stall for hours on such input; the work cap refuses instead.
    start = time.perf_counter()
    raw_problem(b"%PDF-1.7\n" + hostile)
    assert time.perf_counter() - start < 2.0
