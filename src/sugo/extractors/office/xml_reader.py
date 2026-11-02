"""Generic XML as a compact outline (ADR-054). Runs only in the worker process.

The file is parsed with ``defusedxml``: no DTD, no entities, no external
references (THREAT_MODEL, XXE). Depth and element count are checked while
parsing, before the tree can grow past the limits.

Every element becomes one line, ``name: text``, indented two spaces per
level; attributes become ``@name: value`` lines under it; namespace prefixes
are dropped. Elements with neither text, attributes nor children carry no
content and are left out. Three or more sibling records with simple fields,
such as invoice lines, become a table under a line with their name, cheaper
than repeating every field name. A paragraph that resumes after a table starts with its parent's
line again, so the indentation that follows still reads as nested.

An element or attribute whose name says it holds credentials flags its block
``secret`` (ADR-053); the text stays, for the person converting their file.
"""

import io
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from defusedxml import ElementTree as DefusedElementTree  # type: ignore[import-untyped]

from sugo.core.constants import (
    MAX_XML_FILE_BYTES,
    OFFICE_TABLE_MAX_ROWS,
    XML_CREDENTIAL_NAMES,
    XML_MAX_DEPTH,
    XML_MAX_ELEMENTS,
    XML_MIN_TABLE_RECORDS,
    XML_SCHEMA_INSTANCE_NS,
    XML_SCHEMA_LOCATION_ATTRIBUTES,
)
from sugo.core.models import Block, BlockFlag, BlockType, Page, PageOrigin, Table, TableCell
from sugo.i18n import N_

ENGINE_NAME = "xml"
_INDENT = "  "
_INVALID = N_("the file is not well-formed XML, or it uses a DTD or entities")


class Element(Protocol):
    """What the reader uses of a parsed element (stdlib ElementTree, through defusedxml)."""

    tag: str
    text: str | None
    tail: str | None
    attrib: Mapping[str, str]

    def __iter__(self) -> Iterator["Element"]: ...


class Refusal(Exception):  # noqa: N818  (a refusal, not a failure of Sugo)
    """The file is refused; ``code`` is a stable error code, ``message`` a fixed sentence."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def lay_out(root: Element) -> Page:
    """The parsed file as one page of outline and table blocks."""
    return _Layout().page(root)


def parse(data: bytes, *, max_bytes: int | None = None, max_elements: int | None = None) -> Element:
    """Parse with every XML attack refused and the size limits enforced.

    The limits default to those of a generic XML file; Office parts pass their own.

    Raises:
        Refusal: XML_TOO_LARGE or XML_INVALID.
    """
    max_bytes = MAX_XML_FILE_BYTES if max_bytes is None else max_bytes
    max_elements = XML_MAX_ELEMENTS if max_elements is None else max_elements
    if len(data) > max_bytes:
        raise Refusal("XML_TOO_LARGE", N_("the XML file is too large"))
    root: Element | None = None
    depth = elements = 0
    try:
        events = DefusedElementTree.iterparse(
            io.BytesIO(data), events=("start", "end"), forbid_dtd=True
        )
        for event, element in events:
            if event == "end":
                depth -= 1
                continue
            root = element if root is None else root
            depth += 1
            elements += 1
            if depth > XML_MAX_DEPTH:
                raise Refusal("XML_INVALID", N_("the XML nests too deeply"))
            if elements > max_elements:
                raise Refusal("XML_TOO_LARGE", N_("the XML has too many elements"))
    # ParseError is a SyntaxError; defusedxml's refusals and unknown encodings
    # are ValueError and LookupError. Their text may quote the document.
    except (SyntaxError, ValueError, LookupError):
        raise Refusal("XML_INVALID", _INVALID) from None
    if root is None:
        raise Refusal("XML_INVALID", _INVALID)
    return root


def local_name(name: str) -> str:
    """The name without its namespace: ``{uri}name`` and ``prefix:name`` give ``name``."""
    return name.rsplit("}", 1)[-1].rsplit(":", 1)[-1]


def is_credential_name(name: str) -> bool:
    """Whether an element or attribute name says it holds credentials (ADR-053)."""
    key = local_name(name).casefold()
    return key.replace("-", "").replace("_", "").replace(".", "") in XML_CREDENTIAL_NAMES


@dataclass
class _Layout:
    """Builds the blocks of one page from the outline lines and tables."""

    blocks: list[Block] = field(default_factory=list)
    _lines: list[str] = field(default_factory=list)
    _secret: bool = False
    # Lines of the elements being laid out, by depth, to resume after a table.
    _open: list[str] = field(default_factory=list)
    _resumed: bool = False

    def page(self, root: Element) -> Page:
        self._element(root, 0)
        self._flush()
        return Page(
            index=0, width=1.0, height=1.0, origin=PageOrigin.NATIVE, blocks=tuple(self.blocks)
        )

    def _element(self, element: Element, depth: int) -> None:
        name = local_name(element.tag)
        self._secret |= is_credential_name(name)
        attributes = _attributes(element)
        self._secret |= any(is_credential_name(key) for key, _ in attributes)
        text = _clean(element.text)
        children = list(element)
        if not children and not attributes:
            if text:
                self._line(depth, f"{name}: {text}")
            return
        line = f"{name}: {text}" if text else f"{name}:"
        self._line(depth, line)
        self._open.append(line)
        for key, value in attributes:
            self._line(depth + 1, f"@{key}: {value}" if value else f"@{key}:")
        index = 0
        while index < len(children):
            run = _record_run(children, index)
            if run >= XML_MIN_TABLE_RECORDS:
                self._table(children[index : index + run], depth + 1)
            else:
                self._element(children[index], depth + 1)
                run = 1
            for child in children[index : index + run]:
                tail = _clean(child.tail)
                if tail:
                    self._line(depth + 1, tail)
            index += run
        self._open.pop()

    def _line(self, depth: int, text: str) -> None:
        if self._resumed and not self._lines and 0 < depth <= len(self._open):
            # The first line of a paragraph loses its indentation (ADR-042):
            # the parent's line comes first, so its children read as nested.
            self._lines.append(_INDENT * (depth - 1) + self._open[depth - 1])
        self._resumed = False
        self._lines.append(_INDENT * depth + text)

    def _table(self, records: Sequence[Element], depth: int) -> None:
        # The records' name, as the line the table belongs to.
        self._line(depth, f"{local_name(records[0].tag)}:")
        self._flush()
        columns: list[str] = []
        rows: list[dict[str, str]] = []
        for record in records:
            self._secret |= is_credential_name(local_name(record.tag))
            row = {f"@{key}": value for key, value in _attributes(record)}
            row |= {local_name(child.tag): _clean(child.text) for child in record}
            for column in row:
                self._secret |= is_credential_name(column.lstrip("@"))
                if column not in columns:
                    columns.append(column)
            rows.append(row)
        for start in range(0, len(rows), OFFICE_TABLE_MAX_ROWS):
            part = rows[start : start + OFFICE_TABLE_MAX_ROWS]
            cells = [TableCell(row=0, col=col, text=name) for col, name in enumerate(columns)]
            cells += [
                TableCell(row=row + 1, col=col, text=values.get(name, ""))
                for row, values in enumerate(part)
                for col, name in enumerate(columns)
            ]
            table = Table(
                n_rows=len(part) + 1, n_cols=len(columns), header_rows=1, cells=tuple(cells)
            )
            self._add(BlockType.TABLE, table=table)
        self._secret = False
        self._resumed = True

    def _flush(self) -> None:
        if self._lines:
            self._add(BlockType.PARAGRAPH, text="\n".join(self._lines))
            self._lines = []
            self._secret = False

    def _add(self, kind: BlockType, *, text: str = "", table: Table | None = None) -> None:
        number = len(self.blocks)
        self.blocks.append(
            Block(
                id=f"b{number}",
                type=kind,
                text=text,
                table=table,
                reading_order=number,
                origin_engine=ENGINE_NAME,
                flags=(BlockFlag.SECRET,) if self._secret else (),
            )
        )


def _attributes(element: Element) -> list[tuple[str, str]]:
    """Attributes by local name, without those that only point at schemas."""
    return [
        (local_name(key), _clean(value))
        for key, value in element.attrib.items()
        if not (
            key.startswith(f"{{{XML_SCHEMA_INSTANCE_NS}}}")
            and local_name(key).casefold() in XML_SCHEMA_LOCATION_ATTRIBUTES
        )
    ]


def _record_run(children: Sequence[Element], start: int) -> int:
    """How many siblings from ``start`` are records of one name with simple fields.

    Text between two records ends the run: a table would move it away.
    """
    first = children[start]
    if not _is_record(first):
        return 0
    end = start + 1
    while (
        end < len(children)
        and not _clean(children[end - 1].tail)
        and children[end].tag == first.tag
        and _is_record(children[end])
    ):
        end += 1
    return end - start


def _is_record(element: Element) -> bool:
    """Text-free, with distinct leaf fields that have no attributes of their own."""
    fields = list(element)
    if not fields or _clean(element.text) or any(_clean(child.tail) for child in fields):
        return False
    names = [local_name(child.tag) for child in fields]
    return len(set(names)) == len(names) and all(
        not list(child) and not child.attrib for child in fields
    )


def _clean(text: str | None) -> str:
    """Text with XML's insignificant white space collapsed."""
    return " ".join(text.split()) if text else ""
