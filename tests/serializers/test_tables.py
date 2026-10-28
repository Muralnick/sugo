"""Tests for adaptive tables: the cheapest format that keeps the structure (ADR-002)."""

from sugo.core.models import Table, TableCell
from sugo.serializers.tables import render_table


def table(rows: list[list[str]], header_rows: int = 0) -> Table:
    cells = tuple(
        TableCell(row=r, col=c, text=text)
        for r, row in enumerate(rows)
        for c, text in enumerate(row)
    )
    return Table(n_rows=len(rows), n_cols=len(rows[0]), header_rows=header_rows, cells=cells)


def length(text: str) -> int:
    return len(text)


def flat(_: str) -> int:
    # Every format costs the same, so the first candidate in preference order wins.
    return 1


class TestCompact:
    # With a header, the compact table is the first candidate; ``flat`` selects it.

    def test_header_table(self) -> None:
        t = table([["Nome", "Età"], ["Anna", "30"], ["Marco", "41"]], header_rows=1)
        assert render_table(t) == "Nome|Età\n-|-\nAnna|30\nMarco|41"

    def test_pipes_in_cells_are_escaped(self) -> None:
        t = table([["a", "b"], ["x|y", "z"]], header_rows=1)
        assert render_table(t, counter=flat) == "a|b\n-|-\nx\\|y|z"

    def test_empty_edge_cell_gets_outer_pipes(self) -> None:
        # Without outer pipes "|30" would read as a single cell.
        t = table([["Nome", "Età"], ["", "30"]], header_rows=1)
        assert render_table(t, counter=flat) == "|Nome|Età|\n|-|-|\n||30|"

    def test_single_column(self) -> None:
        t = table([["Voce"], ["uno"], ["due"]], header_rows=1)
        assert render_table(t, counter=flat) == "|Voce|\n|-|\n|uno|\n|due|"

    def test_spans_repeat_text_and_headers_merge(self) -> None:
        t = Table(
            n_rows=3,
            n_cols=3,
            header_rows=2,
            cells=(
                TableCell(row=0, col=0, text="Item", row_span=2),
                TableCell(row=0, col=1, text="Price", col_span=2),
                TableCell(row=1, col=1, text="Net"),
                TableCell(row=1, col=2, text="Gross"),
                TableCell(row=2, col=0, text="Pen"),
                TableCell(row=2, col=1, text="1"),
                TableCell(row=2, col=2, text="1.22"),
            ),
        )
        assert render_table(t, counter=flat).splitlines()[0] == "Item|Price / Net|Price / Gross"

    def test_line_breaks_in_cells_become_br(self) -> None:
        t = table([["a", "b"], ["one\ntwo", "z"]], header_rows=1)
        assert "one<br>two" in render_table(t, counter=flat)

    def test_first_cell_cannot_open_structure(self) -> None:
        t = table([["a", "b"], ["# x", "y"]], header_rows=1)
        assert render_table(t, counter=flat).splitlines()[2] == "\\# x|y"


def test_two_columns_without_header_stay_a_compact_table() -> None:
    t = table([["IBAN", "IT60X0542811101000000123456"], ["Scadenza", "31/12/2026"]])
    assert render_table(t) == "IBAN|IT60X0542811101000000123456\nScadenza|31/12/2026"


class TestSentences:
    def test_sparse_wide_table_uses_sentences(self) -> None:
        header = ["Name", "Phone", "Email", "City", "Notes"]
        rows = [header, ["Anna", "", "", "Rome", ""], ["Marco", "", "m@x.it", "", ""]]
        assert render_table(table(rows, header_rows=1)) == (
            "Name: Anna; City: Rome\nName: Marco; Email: m@x.it"
        )

    def test_duplicate_labels_are_not_sentences(self) -> None:
        rows = [["A", "A"], ["", "x"]]
        assert "A: x" not in render_table(table(rows, header_rows=1), counter=length)

    def test_semicolon_in_value_is_not_sentences(self) -> None:
        rows = [["Name", "Notes", "Extra", "More"], ["Anna", "a; b", "", ""]]
        assert render_table(table(rows, header_rows=1), counter=length).startswith("|Name|Notes")

    def test_empty_row_keeps_compact_table(self) -> None:
        rows = [["Name", "City", "Email", "Notes"], ["", "", "", ""], ["Anna", "", "", ""]]
        assert render_table(table(rows, header_rows=1)).startswith("|Name|")


def test_cheapest_format_wins() -> None:
    t = table([["Nome", "Età"], ["Anna", "30"]], header_rows=1)
    assert render_table(t, counter=lambda text: 0 if ";" in text or ": " in text else 1) == (
        "Nome: Anna; Età: 30"
    )


def test_illegible_marker_in_a_cell_is_escaped() -> None:
    t = table([["a", "b"], ["[illegible]", "y"]], header_rows=1)
    assert "\\[illegible]" in render_table(t)
