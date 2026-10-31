"""Tests for the XML layout: outline lines, record tables, secrets and every XML attack refused."""

import pytest

from sugo.core.models import BlockFlag, BlockType, Page
from sugo.extractors.office import xml_reader
from sugo.extractors.office.xml_reader import Refusal, is_credential_name, lay_out, parse
from sugo.serializers.markdown import render


def page(xml: str) -> Page:
    return lay_out(parse(xml.encode("utf-8")))


def text(xml: str) -> str:
    return render(page(xml).blocks)


def refusal(data: bytes) -> str:
    with pytest.raises(Refusal) as caught:
        parse(data)
    return caught.value.code


def test_elements_become_an_indented_outline() -> None:
    xml = (
        '<a:root xmlns:a="urn:a" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        'xsi:schemaLocation="urn:a a.xsd" version="2">'
        "<head><title>  Annual\n report </title><empty/></head>"
        "<para>Mixed <b>bold</b> tail text</para>"
        "</a:root>"
    )
    assert text(xml) == (
        "root:\n"
        "  @version: 2\n"
        "  head:\n"
        "    title: Annual report\n"
        "  para: Mixed\n"
        "    b: bold\n"
        "    tail text"
    )


def test_three_simple_records_become_a_table_named_after_them() -> None:
    rows = "".join(f"<line><n>{n}</n><item>Item {n}</item></line>" for n in (1, 2, 3))
    xml = f"<invoice><number>7</number><body>{rows}<total>6</total></body></invoice>"
    blocks = page(xml).blocks
    assert [block.type for block in blocks] == [
        BlockType.PARAGRAPH,
        BlockType.TABLE,
        BlockType.PARAGRAPH,
    ]
    assert blocks[0].text == "invoice:\n  number: 7\n  body:\n    line:"
    table = blocks[1].table
    assert table is not None
    assert (table.n_rows, table.n_cols, table.header_rows) == (4, 2, 1)
    assert [cell.text for cell in table.cells[:4]] == ["n", "item", "1", "Item 1"]
    # The paragraph after the table starts again from the parent's line.
    assert blocks[2].text == "  body:\n    total: 6"


def test_two_records_or_uneven_records_stay_an_outline() -> None:
    two = "<r>" + "<x><a>1</a></x>" * 2 + "</r>"
    assert all(block.type is BlockType.PARAGRAPH for block in page(two).blocks)
    nested = "<r>" + "<x><a><b>1</b></a></x>" * 3 + "</r>"
    assert all(block.type is BlockType.PARAGRAPH for block in page(nested).blocks)
    repeated_field = "<r>" + "<x><a>1</a><a>2</a></x>" * 3 + "</r>"
    assert all(block.type is BlockType.PARAGRAPH for block in page(repeated_field).blocks)
    # Text between records keeps its place: no table would hold it.
    interrupted = "<r><x><a>1</a></x>note<x><a>2</a></x><x><a>3</a></x></r>"
    assert text(interrupted) == ("r:\n  x:\n    a: 1\n  note\n  x:\n    a: 2\n  x:\n    a: 3")


def test_records_with_attributes_and_missing_fields_fill_the_grid() -> None:
    # <x id="3"/> has no fields: not a record, so only two records remain.
    xml = '<r><x id="1"><a>A</a></x><x id="2"><b>B</b></x><x id="3"/></r>'
    assert all(block.table is None for block in page(xml).blocks)
    xml = '<r><x id="1"><a>A</a></x><x id="2"><b>B</b></x><x id="3"><a>C</a></x></r>'
    (table,) = [block.table for block in page(xml).blocks if block.table is not None]
    assert table.n_cols == 3
    assert [cell.text for cell in table.cells if cell.row == 0] == ["@id", "a", "b"]
    assert [cell.text for cell in table.cells if cell.row == 2] == ["2", "", "B"]


def test_long_tables_are_split_with_the_header_repeated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(xml_reader, "OFFICE_TABLE_MAX_ROWS", 2)
    xml = "<r>" + "".join(f"<x><a>{n}</a></x>" for n in range(5)) + "</r>"
    tables = [block.table for block in page(xml).blocks if block.table is not None]
    assert [table.n_rows for table in tables] == [3, 3, 2]
    assert all(table.cells[0].text == "a" for table in tables)


@pytest.mark.parametrize(
    "xml",
    [
        "<config><password>hunter2</password></config>",
        '<server host="h" Pass-Word="x"/>',
        '<p:conn xmlns:p="urn:p"><p:ConnectionString>x</p:ConnectionString></p:conn>',
        '<a><b cpassword="x">y</b></a>',
        "<r>" + "<u><name>a</name><api_key>k</api_key></u>" * 3 + "</r>",
    ],
)
def test_credential_names_flag_their_block_secret(xml: str) -> None:
    assert any(BlockFlag.SECRET in block.flags for block in page(xml).blocks)


def test_ordinary_names_are_not_secret() -> None:
    xml = "<s><token>the</token><key>A</key><keyword>x</keyword><passport>y</passport></s>"
    assert not any(BlockFlag.SECRET in block.flags for block in page(xml).blocks)
    assert is_credential_name("{urn:x}Client_Secret")
    assert not is_credential_name("secretary")


@pytest.mark.parametrize(
    "data",
    [
        pytest.param(b'<!DOCTYPE r [<!ENTITY e "x">]><r>&e;</r>', id="internal-entity"),
        pytest.param(b'<!DOCTYPE r [<!ENTITY e SYSTEM "file:///etc/passwd">]><r>&e;</r>', id="xxe"),
        pytest.param(
            b'<!DOCTYPE r [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;&a;">]><r>&b;</r>',
            id="billion-laughs",
        ),
        pytest.param(b'<!DOCTYPE r SYSTEM "http://example.com/r.dtd"><r/>', id="external-dtd"),
        pytest.param(b"<r><unclosed></r>", id="malformed"),
        pytest.param(b"", id="empty"),
        pytest.param(b"not xml at all", id="text"),
    ],
)
def test_xml_attacks_and_broken_files_are_refused(data: bytes) -> None:
    assert refusal(data) == "XML_INVALID"


def test_limits_are_enforced_while_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    assert refusal(b"<a>" * 300 + b"</a>" * 300) == "XML_INVALID"
    monkeypatch.setattr(xml_reader, "XML_MAX_ELEMENTS", 10)
    assert refusal(b"<r>" + b"<x/>" * 10 + b"</r>") == "XML_TOO_LARGE"
    monkeypatch.setattr(xml_reader, "MAX_XML_FILE_BYTES", 5)
    assert refusal(b"<r>x</r>") == "XML_TOO_LARGE"


def test_encodings_declared_by_the_file_are_honoured() -> None:
    latin = '<?xml version="1.0" encoding="ISO-8859-1"?><r>caff\xe8</r>'.encode("latin-1")
    assert render(lay_out(parse(latin)).blocks) == "r: caffè"
    utf16 = "<r>città</r>".encode("utf-16")
    assert render(lay_out(parse(utf16)).blocks) == "r: città"
