"""Minimal Excel workbooks built in memory for the tests: only the parts a test needs."""

import io
import zipfile

S = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG = "http://schemas.openxmlformats.org/package/2006/relationships"
_MAIN = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"


def row(*values: str, r: int | None = None, attrs: str = "") -> str:
    """A row of cells: plain text is an inline string, ``=n`` a number, ``<...`` raw cell XML."""
    cells = []
    for value in values:
        if value.startswith("<"):
            cells.append(value)
        elif value.startswith("="):
            cells.append(f"<c><v>{value[1:]}</v></c>")
        else:
            cells.append(f'<c t="inlineStr"><is><t>{value}</t></is></c>')
    number = "" if r is None else f' r="{r}"'
    return f"<row{number}{attrs}>{''.join(cells)}</row>"


def xlsx(
    *sheets: str,
    names: list[str] | None = None,
    states: dict[int, str] | None = None,
    head: dict[int, str] | None = None,
    strings: list[str] | None = None,
    styles: str | None = None,
    workbook_pr: str = "",
    sheet_parts: dict[int, dict[str, tuple[str, str]]] | None = None,
    extra: dict[str, bytes] | None = None,
    namespace: str = S,
) -> bytes:
    """A workbook with one worksheet per ``sheets`` item (the rows of its ``sheetData``).

    ``head`` puts XML before ``sheetData`` (``cols``, ``sheetFormatPr``);
    ``sheet_parts`` maps a sheet to {relationship type: (part name, XML)}
    for comments, drawings and pivot tables; ``extra`` adds or replaces raw entries.
    """
    names = names or [f"Sheet{index + 1}" for index in range(len(sheets))]
    states = states or {}
    head = head or {}
    sheet_parts = sheet_parts or {}
    entries: dict[str, bytes] = {
        "[Content_Types].xml": (
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            f'<Override PartName="/xl/workbook.xml" ContentType="{_MAIN}"/></Types>'
        ).encode(),
        "_rels/.rels": (
            f'<Relationships xmlns="{_PKG}"><Relationship Id="rId1" '
            f'Type="{_REL}/officeDocument" Target="xl/workbook.xml"/></Relationships>'
        ).encode(),
    }
    listed = "".join(
        f'<sheet name="{name}" sheetId="{index + 1}" r:id="s{index + 1}"'
        + (f' state="{states[index]}"' if index in states else "")
        + "/>"
        for index, name in enumerate(names)
    )
    entries["xl/workbook.xml"] = (
        f'<workbook xmlns="{namespace}" xmlns:r="{R}">{workbook_pr}'
        f"<sheets>{listed}</sheets></workbook>"
    ).encode()
    rels = [
        f'<Relationship Id="s{index + 1}" Type="{_REL}/worksheet" '
        f'Target="worksheets/sheet{index + 1}.xml"/>'
        for index in range(len(sheets))
    ]
    if strings is not None:
        items = "".join(f"<si><t>{text}</t></si>" for text in strings)
        entries["xl/sharedStrings.xml"] = f'<sst xmlns="{namespace}">{items}</sst>'.encode()
        rels.append(
            f'<Relationship Id="ss" Type="{_REL}/sharedStrings" Target="sharedStrings.xml"/>'
        )
    if styles is not None:
        entries["xl/styles.xml"] = f'<styleSheet xmlns="{S}">{styles}</styleSheet>'.encode()
        rels.append(f'<Relationship Id="st" Type="{_REL}/styles" Target="styles.xml"/>')
    entries["xl/_rels/workbook.xml.rels"] = (
        f'<Relationships xmlns="{_PKG}">{"".join(rels)}</Relationships>'
    ).encode()
    for index, body in enumerate(sheets):
        entries[f"xl/worksheets/sheet{index + 1}.xml"] = (
            f'<worksheet xmlns="{namespace}" xmlns:r="{R}">{head.get(index, "")}'
            f"<sheetData>{body}</sheetData></worksheet>"
        ).encode()
        parts = sheet_parts.get(index, {})
        if parts:
            links = "".join(
                f'<Relationship Id="p{number}" Type="{_REL}/{kind}" Target="../{name}"/>'
                for number, (kind, (name, _)) in enumerate(parts.items())
            )
            entries[f"xl/worksheets/_rels/sheet{index + 1}.xml.rels"] = (
                f'<Relationships xmlns="{_PKG}">{links}</Relationships>'
            ).encode()
            for name, content in parts.values():
                entries[f"xl/{name}"] = content.encode()
    entries.update(extra or {})
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return buffer.getvalue()
