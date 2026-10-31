"""Tests for reading XML through the worker process: recognition, refusals and failures."""

import codecs
import sys

import pytest

from sugo.core.constants import OFFICE_MAX_WORKER_RESTARTS
from sugo.core.models import BlockFlag
from sugo.extractors.office import extract
from sugo.extractors.office.extract import (
    OfficeExtractionError,
    XmlError,
    XmlTooLargeError,
    extract_xml,
    is_failed_page,
    looks_like_xml,
)
from sugo.serializers.markdown import render


def fake_worker(body: str) -> tuple[str, ...]:
    """A worker that runs ``body`` with ``first`` (the first page), ``opened`` and ``page``."""
    prelude = (
        "import sys, time\n"
        "from sugo.core.models import Block, BlockType, Page, PageOrigin\n"
        "from sugo.extractors import worker as w\n"
        "from sugo.extractors.office import protocol as p\n"
        "first = int(sys.argv[2])\n"
        "out = sys.stdout.buffer\n"
        "def send(m): p.write_message(out, m)\n"
        "def opened(n): send(p.Opened(pages=n))\n"
        "def page(i, text, engine='xml'): send(p.PageRead(page=Page(index=i, width=1.0, "
        "height=1.0, origin=PageOrigin.NATIVE, blocks=(Block(id='b0', "
        "type=BlockType.PARAGRAPH, text=text, origin_engine=engine),))))\n"
    )
    return (sys.executable, "-I", "-c", prelude + body)


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (b'<?xml version="1.0"?><r/>', True),
        (b"  \n<root>x</root>", True),
        (b"<!-- note --><r/>", True),
        (b'<?xml-stylesheet type="text/xsl" href="a.xsl"?><r/>', True),
        (b"<_x/>", True),
        (codecs.BOM_UTF8 + b"<r/>", True),
        ("<r/>".encode("utf-16"), True),
        (b"<!DOCTYPE html><html></html>", False),
        (b"<1>", False),
        (b'{"a": 1}', False),
        (b"plain text", False),
        (b"", False),
    ],
)
def test_xml_is_recognised_by_its_content(data: bytes, expected: bool) -> None:
    assert looks_like_xml(data) is expected


def test_xml_is_read_through_the_worker() -> None:
    (page,) = list(extract_xml(b"<r><a>1</a></r>"))
    assert render(page.blocks) == "r:\n  a: 1"
    assert not is_failed_page(page)


def test_refusals_come_back_as_errors() -> None:
    with pytest.raises(XmlError, match="DTD"):
        list(extract_xml(b'<!DOCTYPE r [<!ENTITY e "x">]><r>&e;</r>'))


def test_too_large_files_are_refused_before_the_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(extract, "MAX_XML_FILE_BYTES", 5)
    with pytest.raises(XmlTooLargeError):
        extract_xml(b"<r>xx</r>", worker=fake_worker("sys.exit(1)"))


@pytest.mark.parametrize(
    "body",
    [
        pytest.param("sys.exit(1)", id="crash"),
        pytest.param("time.sleep(60)", id="stall"),
        pytest.param("w.write_frame(out, b'not json')", id="garbage"),
        pytest.param("out.write(b'\\xff\\xff\\xff\\xff'); out.flush()", id="huge-frame"),
    ],
)
def test_worker_failing_to_open_refuses_the_file(body: str) -> None:
    with pytest.raises(OfficeExtractionError, match="failed to open"):
        list(extract_xml(b"<r/>", worker=fake_worker(body), open_timeout=2))


@pytest.mark.parametrize(
    "body",
    [
        pytest.param("opened(1)\ntime.sleep(60)", id="stall"),
        pytest.param("opened(1)\npage(0, 'x', engine='pymupdf')", id="foreign-engine"),
        pytest.param("opened(1)\npage(5, 'x')", id="wrong-page"),
    ],
)
def test_page_the_worker_cannot_deliver_is_marked_illegible(body: str) -> None:
    (page,) = list(extract_xml(b"<r/>", worker=fake_worker(body), page_timeout=1))
    assert is_failed_page(page)
    assert [block.flags for block in page.blocks] == [(BlockFlag.ILLEGIBLE,)]


def test_file_that_keeps_crashing_the_worker_is_refused() -> None:
    worker = fake_worker(f"opened({OFFICE_MAX_WORKER_RESTARTS + 5})\nsys.exit(1)\n")
    with pytest.raises(OfficeExtractionError, match="keeps crashing"):
        list(extract_xml(b"<r/>", worker=worker, page_timeout=1))


def test_word_documents_are_read_through_the_worker() -> None:
    from tests.extractors.office.docx_files import docx, p

    data = docx(p("First") + '<w:p><w:r><w:br w:type="page"/></w:r></w:p>' + p("Second"))
    assert [render(page.blocks) for page in extract.extract_docx(data)] == ["First", "Second"]


def test_damaged_and_legacy_office_files_are_refused() -> None:
    with pytest.raises(extract.OfficeError) as caught:
        list(extract.extract_docx(b"PK\x03\x04 not a zip"))
    assert caught.value.code == "OFFICE_INVALID"
    with pytest.raises(extract.OfficeUnsupportedError):
        extract.check_legacy(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 100)
    extract.check_legacy(b"PK\x03\x04")
