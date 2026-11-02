"""Excel workbooks (XLSX) as IR pages (ADR-054). Runs only in the worker process.

One page per sheet, in workbook order, starting with the sheet's name as a
heading. Each sheet's cells become tables of at most ``OFFICE_TABLE_MAX_ROWS``
rows; when the first row holds only text it is the header, repeated in every
table. Empty rows and columns are left out, inside the sheet as well as
around it: they carry nothing, and a few cells far apart would otherwise make
a huge, empty grid.

Cells show the value Excel saved with the file: formulas are never evaluated
and their text is never output. Dates and times become ISO 8601; other
numbers are written with at most 15 significant digits, as Excel's "General"
format shows them.

Sheets are parsed piece by piece: each row is read, then dropped from the
tree, so a large sheet never sits whole in memory. Every sheet is first
scanned once, before the first page, to enforce the cell limits on the whole
workbook; the page itself is built when it is asked for.

What a reader does not see is kept but flagged ``hidden``, so the hidden text
cleaner removes it with a reason: hidden and very hidden sheets, hidden rows
and columns, and cell comments. Charts, pivot tables, images and chart sheets
are not guessed: each becomes a block marked illegible ("not converted").
"""

import math
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import partial
from typing import Protocol

from defusedxml import ElementTree as DefusedElementTree  # type: ignore[import-untyped]

from sugo.core.constants import (
    OFFICE_MAX_PART_ELEMENTS,
    OFFICE_TABLE_MAX_ROWS,
    XLSX_MAX_CELLS,
    XLSX_MAX_COLUMNS,
    XLSX_MAX_GRID_CELLS,
    XLSX_MAX_ROWS,
    XLSX_MAX_SHEET_CELLS,
    XLSX_MAX_SHEET_TEXT,
    XML_MAX_DEPTH,
)
from sugo.core.models import Block, BlockFlag, BlockType, Page, PageOrigin, Table, TableCell
from sugo.extractors.office.package import Package
from sugo.extractors.office.xml_reader import Element, Refusal, local_name
from sugo.i18n import N_

ENGINE_NAME = "xlsx"
_S = frozenset(
    {
        "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
        "http://purl.oclc.org/ooxml/spreadsheetml/main",
    }
)
_R = frozenset(
    {
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
        "http://purl.oclc.org/ooxml/officeDocument/relationships",
    }
)
_DAMAGED = N_("the Office file is damaged, or too large to read safely")
_TOO_LARGE = N_("the Office file is too large to read safely")
_TRUE = frozenset({"1", "true", "on"})
_CELL_REF = re.compile(r"([A-Za-z]{1,3})([0-9]{1,7})")

# Built-in number formats that show a date, a time or both (ECMA-376 18.8.30,
# with the East Asian date formats); 46 is elapsed time, a duration. 34, 35,
# 55 and 56 are times in Chinese and dates in Japanese and Korean: left as numbers.
_BUILT_IN = {
    **dict.fromkeys((14, 15, 16, 17, 27, 28, 29, 30, 31, 36), "date"),
    **dict.fromkeys((50, 51, 52, 53, 54, 57, 58), "date"),
    **dict.fromkeys((18, 19, 20, 21, 32, 33, 45, 47), "time"),
    22: "datetime",
}
# Quoted text, escaped characters, padding and fill characters of a format code.
_LITERALS = re.compile(r'"[^"]*"|\\.|_.|\*.')
_ELAPSED = re.compile(r"\[(?:h+|m+|s+)\]", re.IGNORECASE)
_BRACKETS = re.compile(r"\[[^\]]*\]")
_AM_PM = re.compile(r"am/pm|a/p", re.IGNORECASE)
# Serial numbers Excel can show as dates: up to 9999-12-31.
_LAST_SERIAL = 2_958_466
_SECONDS_PER_DAY = 86_400
# Number formats that hide a cell's value: ";;;" everything, ";;" numbers only.
_HIDE_ALL = "hide-all"
_HIDE_NUMBERS = "hide-numbers"
_NUMBER_SECTIONS = 3
# Rows are children of sheetData, itself a child of the worksheet.
_ROW_DEPTH = 3
# The 1900 date system counts a 29 February 1900 that never was (serial 60).
_FAKE_LEAP_DAY = 60


def read_xlsx(data: bytes) -> tuple[int, Callable[[int], Page]]:
    """Check a workbook and return its number of pages and a function that reads one.

    Every sheet is scanned here, so the limits refuse the file before its
    first page; each page is laid out only when asked for.

    Raises:
        Refusal: OFFICE_TOO_LARGE or OFFICE_INVALID, here or from the page function.
    """
    book = _Book(Package(data))
    return len(book.sheets), book.page


class _Node(Element, Protocol):
    """A parsed element whose children can be dropped once read."""

    def remove(self, child: Element) -> None: ...


@dataclass(frozen=True)
class _Sheet:
    name: str
    hidden: bool
    # The worksheet part, or None for a chart sheet or another kind not read.
    part: str | None


@dataclass
class _Grid:
    """The cells of one worksheet, as it is read row by row."""

    hidden_columns: set[int] = field(default_factory=set)
    rows_hidden_by_default: bool = False
    column_ranges: int = 0
    # Row -> column -> (text, whether the value is text).
    rows: dict[int, dict[int, tuple[str, bool]]] = field(default_factory=dict)
    concealed: list[str] = field(default_factory=list)


def _ns(tag: str) -> str:
    return tag[1:].split("}", 1)[0] if tag.startswith("{") else ""


def _is_s(element: Element, name: str) -> bool:
    return local_name(element.tag) == name and _ns(element.tag) in _S


def _child(element: Element, name: str) -> Element | None:
    return next((child for child in element if _is_s(child, name)), None)


def _rid(element: Element) -> str | None:
    for key, value in element.attrib.items():
        if local_name(key) == "id" and _ns(key) in _R:
            return value
    return None


def _rich_text(element: Element) -> str:
    """The text of a string item (``si``, ``is``, comment ``text``): its runs, no phonetic guide."""
    parts: list[str] = []
    for child in element:
        if _is_s(child, "t"):
            parts.append(child.text or "")
        elif _is_s(child, "r"):
            parts.extend(t.text or "" for t in child if _is_s(t, "t"))
    return "".join(parts)


def _true(value: str | None) -> bool:
    return value is not None and value.strip().casefold() in _TRUE


def _zero(value: str | None) -> bool:
    """A row height or column width of zero: the row or column cannot be seen."""
    try:
        return value is not None and float(value) <= 0
    except ValueError:
        return False


class _Book:
    def __init__(self, package: Package) -> None:
        self._package = package
        main = package.main_part()
        workbook = package.xml(main)
        if not _is_s(workbook, "workbook"):
            raise Refusal("OFFICE_INVALID", _DAMAGED)
        properties = _child(workbook, "workbookPr")
        self._date1904 = properties is not None and _true(properties.attrib.get("date1904"))
        rels = package.relationships(main)
        self.sheets: list[_Sheet] = []
        listed = _child(workbook, "sheets")
        for sheet in [] if listed is None else listed:
            if not _is_s(sheet, "sheet"):
                continue
            rid = _rid(sheet)
            relationship = None if rid is None else rels.get(rid)
            part = None
            if (
                relationship is not None
                and relationship.type.endswith("/worksheet")
                and not relationship.external
                and package.has(relationship.target)
            ):
                part = relationship.target
            self.sheets.append(
                _Sheet(
                    name=sheet.attrib.get("name", "").strip(),
                    hidden=sheet.attrib.get("state", "visible").strip().casefold() != "visible",
                    part=part,
                )
            )
        if not self.sheets:
            raise Refusal("OFFICE_INVALID", _DAMAGED)
        parts = [sheet.part for sheet in self.sheets if sheet.part is not None]
        # Two sheets on one part would read it twice for free (the total counts
        # a part once): Excel never writes that.
        if len(parts) != len(set(parts)):
            raise Refusal("OFFICE_INVALID", _DAMAGED)
        self._strings: list[str] = []
        self._styles: list[str | None] = []
        # Only the first of each: a part read again does not count towards the total.
        strings = next(self._related(main, "/sharedStrings"), None)
        if strings is not None:
            self._walk(strings, 2, self._shared_string)
        styles = next(self._related(main, "/styles"), None)
        if styles is not None:
            self._styles = _date_styles(package.xml(styles))
        # Per worksheet part: hidden columns, and whether rows are hidden by default.
        self._layouts: dict[str, tuple[frozenset[int], bool]] = {}
        self._survey()

    # --- Parsing ------------------------------------------------------------

    def _walk(self, part: str, depth: int, handle: Callable[[int, Element, Element], None]) -> None:
        """Parse a part piece by piece: ``handle`` sees each element down to ``depth``
        once it is complete, with its parent, then the element is dropped from the tree.

        At most ``OFFICE_MAX_PART_ELEMENTS`` elements are held at once.
        """
        stack: list[_Node] = []
        marks: list[int] = []
        held = 0
        try:
            with self._package.stream(part) as source:
                events = DefusedElementTree.iterparse(
                    source, events=("start", "end"), forbid_dtd=True
                )
                for event, element in events:
                    if event == "start":
                        if len(stack) < depth:
                            marks.append(held)
                        stack.append(element)
                        held += 1
                        if len(stack) > XML_MAX_DEPTH:
                            raise Refusal("OFFICE_INVALID", _DAMAGED)
                        if held > OFFICE_MAX_PART_ELEMENTS:
                            raise Refusal("OFFICE_TOO_LARGE", _TOO_LARGE)
                        continue
                    stack.pop()
                    level = len(stack) + 1
                    if level > depth:
                        continue
                    mark = marks.pop()
                    if level > 1:
                        handle(level, element, stack[-1])
                        stack[-1].remove(element)
                        held = mark
        # ParseError is a SyntaxError; defusedxml's refusals and unknown encodings
        # are ValueError and LookupError. Their text may quote the document.
        except (SyntaxError, ValueError, LookupError):
            raise Refusal("OFFICE_INVALID", _DAMAGED) from None

    def _shared_string(self, level: int, element: Element, parent: Element) -> None:
        if _is_s(element, "si"):
            # Stripped once here, not again for every cell that uses it.
            self._strings.append(_rich_text(element).strip())

    # --- Limits -------------------------------------------------------------

    def _survey(self) -> None:
        """Count the cells with a value, their text and the grid they span, over all
        sheets; note each sheet's hidden columns and default row height."""
        self._cells_read = 0
        grid = 0
        for sheet in self.sheets:
            if sheet.part is None:
                continue
            before = self._cells_read
            self._text = 0
            survey = _Grid()
            rows: set[int] = set()
            columns: set[int] = set()
            last_row = [0]
            count = partial(self._count, survey, rows=rows, columns=columns, last_row=last_row)
            self._walk(sheet.part, _ROW_DEPTH, count)
            self._layouts[sheet.part] = (
                frozenset(survey.hidden_columns),
                survey.rows_hidden_by_default,
            )
            # The header repeated in every table adds at most one row in 199.
            grid += (len(rows) + len(rows) // (OFFICE_TABLE_MAX_ROWS - 1) + 1) * len(columns)
            if grid > XLSX_MAX_GRID_CELLS or self._cells_read - before > XLSX_MAX_SHEET_CELLS:
                raise Refusal("OFFICE_TOO_LARGE", _TOO_LARGE)

    def _count(
        self,
        survey: _Grid,
        level: int,
        element: Element,
        parent: Element,
        *,
        rows: set[int],
        columns: set[int],
        last_row: list[int],
    ) -> None:
        if _layout(survey, level, element, parent) or not _is_row(level, element, parent):
            return
        for column, cell in _cells(element, last_row):
            inline = _child(cell, "is")
            value = _child(cell, "v")
            if inline is None and value is None:
                continue
            self._cells_read += 1
            rows.add(last_row[0])
            columns.add(column)
            # A cell's text, counted so that one long shared string used by many
            # cells cannot fill the worker's memory or the page message.
            if inline is not None:
                self._text += len(_rich_text(inline))
            elif value is not None and cell.attrib.get("t") == "s":
                number = _int(value.text)
                if number is not None and 0 <= number < len(self._strings):
                    self._text += len(self._strings[number])
            elif value is not None:
                self._text += len(value.text or "")
        if self._cells_read > XLSX_MAX_CELLS or self._text > XLSX_MAX_SHEET_TEXT:
            raise Refusal("OFFICE_TOO_LARGE", _TOO_LARGE)

    # --- Pages --------------------------------------------------------------

    def page(self, index: int) -> Page:
        """Lay out one sheet as a page.

        Raises:
            Refusal: OFFICE_INVALID or OFFICE_TOO_LARGE if the sheet's parts are broken.
        """
        sheet = self.sheets[index]
        blocks: list[tuple[BlockType, str, Table | None, tuple[BlockFlag, ...]]] = []
        if sheet.name:
            blocks.append((BlockType.HEADING, sheet.name, None, ()))
        if sheet.part is None:
            blocks.append((BlockType.IMAGE, "", None, (BlockFlag.ILLEGIBLE,)))
        else:
            hidden_columns, rows_hidden = self._layouts[sheet.part]
            grid = _Grid(hidden_columns=set(hidden_columns), rows_hidden_by_default=rows_hidden)
            last_row = [0]
            read = partial(self._read, grid, last_row=last_row)
            self._walk(sheet.part, _ROW_DEPTH, read)
            blocks.extend((BlockType.TABLE, "", table, ()) for table in _tables(grid))
            concealed = grid.concealed + self._comments(sheet.part)
            if concealed:
                blocks.append(
                    (BlockType.PARAGRAPH, "\n".join(concealed), None, (BlockFlag.HIDDEN,))
                )
            not_converted = self._not_converted(sheet.part)
            blocks.extend([(BlockType.IMAGE, "", None, (BlockFlag.ILLEGIBLE,))] * not_converted)
        if sheet.hidden:
            blocks = [
                (kind, text, table, (*flags, BlockFlag.HIDDEN))
                for kind, text, table, flags in blocks
            ]
        return Page(
            index=index,
            width=1.0,
            height=1.0,
            origin=PageOrigin.NATIVE,
            blocks=tuple(
                Block(
                    id=f"b{number}",
                    type=kind,
                    text=text,
                    heading_level=1 if kind is BlockType.HEADING else None,
                    table=table,
                    reading_order=number,
                    origin_engine=ENGINE_NAME,
                    flags=flags,
                )
                for number, (kind, text, table, flags) in enumerate(blocks)
            ),
        )

    def _read(
        self, grid: _Grid, level: int, element: Element, parent: Element, *, last_row: list[int]
    ) -> None:
        """Take in one complete row of a worksheet."""
        if not _is_row(level, element, parent):
            return
        values = {column: self._value(cell) for column, cell in _cells(element, last_row)}
        values = {column: value for column, value in values.items() if value[0]}
        if not values:
            return
        custom = _true(element.attrib.get("customHeight"))
        hidden = (
            _true(element.attrib.get("hidden"))
            or _zero(element.attrib.get("ht"))
            or (grid.rows_hidden_by_default and not custom)
        )
        unseen = {c for c, v in values.items() if hidden or c in grid.hidden_columns or v[2]}
        concealed = [values[c][0] for c in sorted(unseen)]
        if concealed:
            grid.concealed.append(" | ".join(concealed))
        seen = {c: (v[0], v[1]) for c, v in values.items() if c not in unseen}
        if seen:
            grid.rows.setdefault(last_row[0], {}).update(seen)

    def _value(self, cell: Element) -> tuple[str, bool, bool]:
        """A cell's saved value as text, whether it is text (not a number, date,
        truth value or error), and whether its number format hides it (``;;;``)."""
        kind = cell.attrib.get("t", "n")
        style = _int(cell.attrib.get("s")) or 0
        shown = self._styles[style] if 0 <= style < len(self._styles) else None
        concealed = shown == _HIDE_ALL or (
            shown == _HIDE_NUMBERS and kind not in ("inlineStr", "s", "str")
        )
        if kind == "inlineStr":
            inline = _child(cell, "is")
            return ("" if inline is None else _rich_text(inline).strip()), True, concealed
        value_element = _child(cell, "v")
        value = None if value_element is None else value_element.text
        if value is None:
            return "", False, False
        if kind == "s":
            number = _int(value)
            if number is not None and 0 <= number < len(self._strings):
                return self._strings[number], True, concealed
            return "", True, concealed
        if kind == "str":
            return value.strip(), True, concealed
        if kind == "b":
            return ("TRUE" if value.strip() == "1" else "FALSE"), False, concealed
        if kind in ("e", "d"):
            return value.strip(), False, concealed
        return _number(value.strip(), shown, date1904=self._date1904), False, concealed

    def _related(self, part: str, suffix: str) -> Iterator[str]:
        for relationship in self._package.relationships(part).values():
            if (
                relationship.type.endswith(suffix)
                and not relationship.external
                and self._package.has(relationship.target)
            ):
                yield relationship.target

    def _comments(self, part: str) -> list[str]:
        found: list[str] = []
        for target in self._related(part, "/comments"):
            comments = self._package.xml(target)
            listed = _child(comments, "commentList")
            for comment in [] if listed is None else listed:
                text = _child(comment, "text") if _is_s(comment, "comment") else None
                if text is not None and (content := _rich_text(text).strip()):
                    found.append(content)
        return found

    def _not_converted(self, part: str) -> int:
        """Charts, images and pivot tables of a sheet: one block each, never guessed."""
        count = sum(1 for _ in self._related(part, "/pivotTable"))
        for drawing in self._related(part, "/drawing"):
            count += sum(1 for _ in self._related(drawing, "/chart"))
            count += sum(1 for _ in self._related(drawing, "/image"))
        return count


def _is_row(level: int, element: Element, parent: Element) -> bool:
    return level == _ROW_DEPTH and _is_s(element, "row") and _is_s(parent, "sheetData")


def _layout(grid: _Grid, level: int, element: Element, parent: Element) -> bool:
    """Note a hidden column range or the default row height; whether ``element`` was one.

    Read in the scan before the first page, so their place in the part does not matter.

    Raises:
        Refusal: OFFICE_INVALID for more column ranges than Excel has columns.
    """
    if level == _ROW_DEPTH - 1 and _is_s(element, "sheetFormatPr"):
        grid.rows_hidden_by_default = _true(element.attrib.get("zeroHeight"))
        return True
    if level != _ROW_DEPTH or not _is_s(element, "col") or not _is_s(parent, "cols"):
        return False
    grid.column_ranges += 1
    if grid.column_ranges > XLSX_MAX_COLUMNS:
        raise Refusal("OFFICE_INVALID", _DAMAGED)
    first, last = _int(element.attrib.get("min")), _int(element.attrib.get("max"))
    if (
        first is not None
        and last is not None
        and (_true(element.attrib.get("hidden")) or _zero(element.attrib.get("width")))
    ):
        grid.hidden_columns.update(range(max(first, 1), min(last, XLSX_MAX_COLUMNS) + 1))
    return True


def _int(value: str | None) -> int | None:
    try:
        return None if value is None else int(value)
    except ValueError:
        return None


def _cells(row: Element, last_row: list[int]) -> Iterator[tuple[int, Element]]:
    """The cells of a row with their column (1-based); updates ``last_row``.

    A row or cell without a reference follows the one before it.

    Raises:
        Refusal: OFFICE_INVALID for a reference outside Excel's grid.
    """
    number = _int(row.attrib.get("r"))
    last_row[0] = last_row[0] + 1 if number is None else number
    if not 1 <= last_row[0] <= XLSX_MAX_ROWS:
        raise Refusal("OFFICE_INVALID", _DAMAGED)
    column = 0
    for cell in row:
        if not _is_s(cell, "c"):
            continue
        match = _CELL_REF.fullmatch(cell.attrib.get("r", ""))
        column = column + 1 if match is None else _column(match.group(1))
        if not 1 <= column <= XLSX_MAX_COLUMNS:
            raise Refusal("OFFICE_INVALID", _DAMAGED)
        yield column, cell


def _column(letters: str) -> int:
    number = 0
    for letter in letters.upper():
        number = number * 26 + ord(letter) - ord("A") + 1
    return number


def _date_styles(styles: Element) -> list[str | None]:
    """For each cell style, in order: "date", "time", "datetime", a format
    that hides the value, or None (a number)."""
    custom: dict[int, str] = {}
    formats = _child(styles, "numFmts")
    for number_format in [] if formats is None else formats:
        number = _int(number_format.attrib.get("numFmtId"))
        if _is_s(number_format, "numFmt") and number is not None:
            custom[number] = number_format.attrib.get("formatCode", "")
    kinds: list[str | None] = []
    cell_styles = _child(styles, "cellXfs")
    for style in [] if cell_styles is None else cell_styles:
        if not _is_s(style, "xf"):
            continue
        number = _int(style.attrib.get("numFmtId")) or 0
        kinds.append(_format_kind(custom[number]) if number in custom else _BUILT_IN.get(number))
    return kinds


def _format_kind(code: str) -> str | None:
    """Whether a custom format code shows a date, a time or both.

    Only the first section counts (positive numbers); quoted text, escapes
    and colours are ignored; elapsed time such as ``[h]:mm`` is a duration.
    """
    sections = _LITERALS.sub("", code).split(";")
    # ";;;" shows nothing; ";;" hides numbers but shows text.
    if len(sections) >= _NUMBER_SECTIONS and not any(part.strip() for part in sections[:3]):
        empty_text = len(sections) > _NUMBER_SECTIONS and not sections[3].strip()
        return _HIDE_ALL if empty_text else _HIDE_NUMBERS
    section = sections[0]
    if _ELAPSED.search(section):
        return None
    section = _AM_PM.sub("", _BRACKETS.sub("", section)).casefold()
    time = "h" in section or "s" in section
    date = "d" in section or "y" in section or ("m" in section and not time)
    if date and time:
        return "datetime"
    return "date" if date else ("time" if time else None)


def _number(value: str, date_kind: str | None, *, date1904: bool) -> str:
    """A saved number as Excel shows it: ISO 8601 for a date or time, else
    at most 15 significant digits."""
    try:
        number = float(value)
    except ValueError:
        return value
    if not math.isfinite(number):
        return value
    if date_kind in ("date", "time", "datetime") and 0 <= number < _LAST_SERIAL:
        moment = _iso(number, date_kind, date1904=date1904)
        if moment is not None:
            return moment
    text = f"{number:.15g}"
    return "0" if text == "-0" else text


def _iso(serial: float, kind: str, *, date1904: bool) -> str | None:
    seconds = round(serial * _SECONDS_PER_DAY)
    if kind == "time":
        return _clock(seconds)
    if date1904:
        epoch = datetime(1904, 1, 1)
    elif serial < 1:
        # Day 0 of the 1900 system, "1900-01-00": not a date.
        return None
    elif int(serial) == _FAKE_LEAP_DAY:
        if kind == "date":
            return "1900-02-29"
        return "1900-02-29T" + _clock(seconds)
    else:
        # Before the fake leap day, serial 1 is 1900-01-01.
        day = 31 if serial < _FAKE_LEAP_DAY else 30
        epoch = datetime(1899, 12, day)
    try:
        moment = epoch + timedelta(seconds=seconds)
    except OverflowError:
        # Past 9999-12-31, as the 1904 system or rounding can reach.
        return None
    if kind == "date":
        return moment.date().isoformat()
    return moment.isoformat(timespec="seconds")


def _clock(seconds: int) -> str:
    """The time of day of a moment counted in seconds, as ``hh:mm:ss``."""
    seconds %= _SECONDS_PER_DAY
    return f"{seconds // 3600:02d}:{seconds // 60 % 60:02d}:{seconds % 60:02d}"


def _tables(grid: _Grid) -> list[Table]:
    """The visible cells as tables of at most ``OFFICE_TABLE_MAX_ROWS`` rows,
    without empty rows and columns, the header repeated."""
    rows = [grid.rows[row] for row in sorted(grid.rows)]
    if not rows:
        return []
    columns = {column: index for index, column in enumerate(sorted(set().union(*rows)))}
    first = rows[0]
    header = rows[:1] if len(rows) > 1 and all(is_text for _, is_text in first.values()) else []
    body = rows[len(header) :]
    size = OFFICE_TABLE_MAX_ROWS - len(header)
    tables: list[Table] = []
    for start in range(0, len(body), size):
        part = header + body[start : start + size]
        tables.append(
            Table(
                n_rows=len(part),
                n_cols=len(columns),
                header_rows=len(header),
                cells=tuple(
                    TableCell(row=row_index, col=columns[column], text=text)
                    for row_index, row in enumerate(part)
                    for column, (text, _) in sorted(row.items())
                ),
            )
        )
    return tables
