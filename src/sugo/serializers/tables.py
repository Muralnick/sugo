"""Render a table in the cheapest of two formats that keeps its structure (ADR-002).

Candidates, the first preferred when they cost the same:

- **Compact table:** pipe table without padding or outer pipes
  (``Name|Age`` / ``-|-`` / ``Anna|30``). Always possible. Outer pipes are
  added when a row starts or ends with an empty cell, which would otherwise
  be lost, and for one-column tables. A table without header rows has no
  delimiter row.
- **Row sentences:** ``label: value; label: value`` per row, empty cells
  omitted, for tables with a header; cheap for wide, sparse tables.

A format is only a candidate when the table can be read back from it without
ambiguity; otherwise it is skipped. Cells spanning several rows or columns
repeat their text in every cell they cover; header rows are merged per column
as ``Top / Sub``. Line breaks inside a cell, of any kind, become ``<br>``;
spaces around a cell's text are dropped, as Markdown tables do. The choice is
measured with the o200k_base tokenizer (ADR-003, ADR-042). A ``key: value``
format for two-column tables was measured and dropped: it cost one or two
tokens more than the compact table.
"""

import re
from collections.abc import Callable

from sugo.core.models import Table
from sugo.metrics.tokenizer import count_tokens
from sugo.serializers.escape import escape_line_start, escape_marker

Grid = list[list[str]]

# Backslashes ending a cell or before a "|" would escape the pipe after them
# and merge two cells; doubled, they stay literal.
_PIPE_BACKSLASHES = re.compile(r"\\+(?=\||$)")
# A row of dash cells (":--", "-:") reads as a delimiter row and would turn
# the row above it into a header.
_DELIMITER_CELL = re.compile(r":?-+:?")


def render_table(table: Table, counter: Callable[[str], int] = count_tokens) -> str:
    """Render a table in its cheapest faithful format."""
    grid = _grid(table)
    labels = _header_labels(grid, table.header_rows)
    body = grid[table.header_rows :]
    sentences = _sentences(labels, body)
    candidates = [_compact(labels, body)] + ([sentences] if sentences is not None else [])
    # min() keeps the first of equal costs, so ties follow the order above.
    return min(candidates, key=counter)


def _grid(table: Table) -> Grid:
    grid = [[""] * table.n_cols for _ in range(table.n_rows)]
    for cell in table.cells:
        # Every line boundary, a lone "\r" or U+2028 too: any of them would break
        # the row in two for some readers.
        text = escape_marker("<br>".join(cell.text.strip().splitlines()))
        for row in range(cell.row, cell.row + cell.row_span):
            for col in range(cell.col, cell.col + cell.col_span):
                grid[row][col] = text
    return grid


def _header_labels(grid: Grid, header_rows: int) -> list[str] | None:
    if header_rows == 0:
        return None
    labels = []
    for col in range(len(grid[0])):
        parts: list[str] = []
        for row in range(header_rows):
            text = grid[row][col]
            # A header cell spanning rows repeats; keep it once.
            if text and (not parts or parts[-1] != text):
                parts.append(text)
        labels.append(" / ".join(parts))
    return labels


def _compact(labels: list[str] | None, body: Grid) -> str:
    rows = ([labels] if labels is not None else []) + body
    n_cols = len(rows[0])
    outer = n_cols == 1 or any(row[0] == "" or row[-1] == "" for row in rows)

    def line(cells: list[str]) -> str:
        escaped = [_escape_cell(cell) for cell in cells]
        if outer:
            if all(_DELIMITER_CELL.fullmatch(cell) for cell in escaped):
                escaped[0] = "\\" + escaped[0]
            return f"|{'|'.join(escaped)}|"
        return escape_line_start("|".join(escaped))

    lines = [line(row) for row in body]
    if labels is not None:
        delimiter = "|".join(["-"] * n_cols)
        lines[:0] = [line(labels), f"|{delimiter}|" if outer else delimiter]
    return "\n".join(lines)


def _escape_cell(cell: str) -> str:
    doubled = _PIPE_BACKSLASHES.sub(lambda m: m[0] * 2, cell)
    return doubled.replace("|", "\\|")


def _sentences(labels: list[str] | None, body: Grid) -> str | None:
    if labels is None or not body:
        return None
    if len(set(labels)) != len(labels) or any(
        not label or ":" in label or ";" in label or label.endswith("\\") for label in labels
    ):
        return None
    lines = []
    for row in body:
        # A value ending with "\" would escape the "; " after it.
        if any(";" in value or value.endswith("\\") for value in row):
            return None
        parts = [f"{label}: {value}" for label, value in zip(labels, row, strict=True) if value]
        # An empty row would vanish without a trace; the compact table keeps it.
        if not parts:
            return None
        lines.append(escape_line_start("; ".join(parts)))
    return "\n".join(lines)
