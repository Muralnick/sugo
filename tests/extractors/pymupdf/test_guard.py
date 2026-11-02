"""Tests for the Brotli guard: every way of naming Brotli is refused, real PDFs pass."""

import random
import time
from collections.abc import Callable

import pymupdf
import pytest

from sugo.extractors.pymupdf.guard import UNCHECKED_REFUSAL, raw_problem, scan

RawPdf = Callable[..., bytes]


@pytest.mark.parametrize(
    "entry",
    [
        b"/Filter /BrotliDecode",
        b"/Filter /Br#6ftliDecode",
        b"/Filter [/FlateDecode /BrotliDecode]",
        b"/F#69lter /Br",
        # Arrays are read as MuPDF reads them: no "]" in a comment or string
        # ends them, and no amount of whitespace hides a name.
        b"/Filter [ %]\n /Br]",
        b"/Filter [ (]) /Br]",
        b"/Filter [ ( ] (()) ) /Br ]",
        b"/Filter [" + b" " * 600 + b"/Br]",
        b"/Filter [ [/FlateDecode] /Br]",
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
        # MuPDF's lexer accepts a sign before each number.
        b"/Filter +5 0 R",
        b"/Filter 5 -0 R",
        b"/Filter [ %]\n 5 0 R]",
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
    assert scan(b"BI /W 1 /H 1 /F /Br ID x EI").brotli
    assert scan(b"BI /F [/AHx /Br] ID").brotli
    assert not scan(b"/Brioche /Bread /BR").brotli


@pytest.mark.parametrize(
    "hostile",
    [
        b"%" * 200_000,
        b"/Filter [" * 50_000,
        b"/Filter " + b"% x\n" * 50_000,
        b"/Filter [" + b"1 " * 100_000,
    ],
    # Short IDs: pytest stores the test ID in an environment variable, capped on Windows.
    ids=["percent-signs", "nested-arrays", "comment-lines", "long-array"],
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
    assert not scan(noise).brotli
    assert scan(b"/F /Br ").brotli
    assert scan(b"/Filter[/AHx/Br]").brotli


def test_random_binary_data_is_not_refused() -> None:
    # A large compressed file must not be refused by chance (review of PR #13).
    data = random.Random(43).randbytes(16 * 1024 * 1024)  # noqa: S311  (test data)
    assert raw_problem(b"%PDF-1.7\n" + data) is None


@pytest.mark.parametrize("entry", [b"/F 5 0 R", b"/F [/FlateDecode 5 0 R]", b"/F +5 0 R"])
def test_short_key_reference_in_a_stream_dictionary_is_refused(
    raw_pdf: RawPdf, entry: bytes
) -> None:
    # MuPDF decodes object streams while opening the file, before the worker
    # can check anything, so the raw layer must refuse these itself.
    problem = raw_problem(raw_pdf(entry, extra=b"/FlateDecode"))
    assert problem is not None
    assert "indirectly" in problem


def test_file_specification_reference_is_not_refused() -> None:
    # Attachments and links write "/F 5 0 R" in dictionaries no stream follows.
    data = b"%PDF-1.7\n1 0 obj\n<< /EF << /F 5 0 R >> /Type /Filespec /F (a.txt) >>\nendobj\n"
    assert raw_problem(data) is None
    assert scan(data).other_references == {5}


@pytest.mark.parametrize(
    "entry",
    [b"/Filter [/A#28 /Br]", b"/Filter [/A#5D /Br]", b"/Filter [/A#25 /Br]", b"/F [/A#28/Br]"],
    ids=["paren", "bracket", "percent", "short-key"],
)
def test_escaped_delimiter_stays_inside_its_name(raw_pdf: RawPdf, entry: bytes) -> None:
    # MuPDF reads "/A#28" as the name "A(", not as a name and an open string.
    problem = raw_problem(raw_pdf(entry))
    assert problem is not None
    assert "Brotli" in problem


def test_inline_image_array_tricks_are_seen_in_decoded_content() -> None:
    assert scan(b"BI /W 1 /H 1 /F [ %]\n/Br] ID x EI").brotli
    assert scan(rb"BI /W 1 /H 1 /F [ (a\) ]) /Br] ID x EI").brotli
    assert scan(b"BI /W 1 /H 1 /F [/A#28 /Br] ID x EI").brotli
    assert scan(b"BI /F 7 0 R ID x EI").references == {7}
    assert not scan(b"/F#20 /Br /Fx /Br").brotli  # "F " and "Fx" are not filter keys


@pytest.mark.parametrize(
    "hostile",
    [b"/F[(" * 100_000, b"/F[[" * 100_000, b"/Filter[%]\n" * 100_000],
    ids=["open-strings", "open-arrays", "commented-brackets"],
)
def test_scans_that_never_end_are_cut_and_refused(hostile: bytes) -> None:
    # Every array here stays open to the end of the file; reading each one to
    # the end would take quadratic time, so the scan is cut and refuses.
    start = time.perf_counter()
    problem = raw_problem(b"%PDF-1.7\n" + hostile)
    assert time.perf_counter() - start < 2.0
    assert problem == UNCHECKED_REFUSAL


@pytest.mark.parametrize(
    "entry",
    [b"/Filter 5+0R", b"/Filter 5-0 R", b"/Filter [5 0R]", b"/Filter [5+0R]", b"/Filter --5 0 R"],
)
def test_reference_written_without_spaces_is_refused(raw_pdf: RawPdf, entry: bytes) -> None:
    # MuPDF's lexer ends a number at a sign or a letter: "5+0R" is "5 0 R".
    problem = raw_problem(raw_pdf(entry, extra=b"/FlateDecode"))
    assert problem is not None
    assert "indirectly" in problem


@pytest.mark.parametrize("keyword", [b"stream \n", b"stream\t", b"stream%\n", b"stream<"])
def test_stream_keyword_is_recognised_as_mupdf_reads_it(keyword: bytes) -> None:
    data = b"%PDF-1.7\n4 0 obj\n<< /Type /ObjStm /F 5 0 R /Length 1 >>\n" + keyword + b"x"
    assert raw_problem(data) is not None
    assert scan(b"BI /W 1 /F 6+0R ID x EI").references == {6}
