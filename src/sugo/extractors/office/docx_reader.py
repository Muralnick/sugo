"""Word documents (DOCX) as IR pages (ADR-054). Runs only in the worker process.

Read from the package's own parts, never through external relationships:

- paragraphs, with headings from outline levels or the built-in heading and
  title styles, and list items from numbering, numbered ones with their
  label ("2.1.") so the structure survives without list levels in the IR;
- tables, a merged cell's text in its first cell, split every
  ``OFFICE_TABLE_MAX_ROWS`` rows with the header rows repeated;
- hyperlinks to outside addresses as Markdown links; text boxes after the
  paragraph that holds them; fields as their displayed result;
- footnotes after the page that cites them, endnotes at the end, each with
  its number; each section's header at the start of its first page and its
  footer at the end of its last page.

A new page starts at every explicit page break and section break: these are
not Word's printed pages, which only Word's layout knows.

What a reader does not see is kept but flagged ``hidden``, so the hidden
text cleaner removes it with a reason: runs set to vanish (directly or by
style), text under 2 pt, white text without shading or highlight, deleted
and moved-away revisions (the output shows changes accepted), and comments.
Equations, images and embedded objects are not guessed: each becomes a
block marked illegible ("not converted").
"""

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field

from sugo.core.constants import (
    DOCX_MIN_VISIBLE_HALF_POINTS,
    MAX_HEADING_LEVEL,
    OFFICE_TABLE_MAX_ROWS,
)
from sugo.core.models import Block, BlockFlag, BlockType, Page, PageOrigin, Table, TableCell
from sugo.extractors.office.package import Package, Relationship
from sugo.extractors.office.xml_reader import Element, local_name

ENGINE_NAME = "docx"
_W = frozenset(
    {
        "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
        "http://purl.oclc.org/ooxml/wordprocessingml/main",
    }
)
_R = frozenset(
    {
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
        "http://purl.oclc.org/ooxml/officeDocument/relationships",
    }
)
_MATH = frozenset(
    {
        "http://schemas.openxmlformats.org/officeDocument/2006/math",
        "http://purl.oclc.org/ooxml/officeDocument/math",
    }
)
_MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"
# Containers whose children are read as if they stood in their place.
_TRANSPARENT = frozenset(
    {"ins", "smartTag", "customXml", "fldSimple", "sdt", "sdtContent", "moveTo", "dir", "bdo"}
)
_HIDDEN_CONTAINERS = frozenset({"del", "moveFrom"})
_HEADING_STYLE = re.compile(r"heading\s*([1-9])")
# Only these outside addresses become Markdown links; anything else (javascript:,
# file:, white space or brackets that would break the link) stays plain text.
_LINK = re.compile(r"(?:https?://|mailto:)[^\s()<>\[\]]+", re.IGNORECASE)
_FALSE = frozenset({"0", "false", "off"})
_WHITE = "FFFFFF"
# Roman numerals stop at 3 999; larger counters are written as decimals.
_ROMAN_LIMIT = 4000


def read_docx(data: bytes) -> list[Page]:
    """Lay out a Word document as pages.

    Raises:
        Refusal: OFFICE_TOO_LARGE or OFFICE_INVALID.
    """
    package = Package(data)
    main = package.main_part()
    return _Reader(package, main).pages()


def _ns(tag: str) -> str:
    return tag[1:].split("}", 1)[0] if tag.startswith("{") else ""


def _is_w(element: Element, name: str) -> bool:
    return local_name(element.tag) == name and _ns(element.tag) in _W


def _children(element: Element, name: str) -> Iterator[Element]:
    return (child for child in element if _is_w(child, name))


def _child(element: Element | None, name: str) -> Element | None:
    return None if element is None else next(_children(element, name), None)


def _val(element: Element | None, name: str = "val") -> str | None:
    """A WordprocessingML attribute (``w:val`` by default), whatever its prefix."""
    if element is None:
        return None
    for key, value in element.attrib.items():
        if local_name(key) == name and _ns(key) in _W | {""}:
            return value
    return None


def _rid(element: Element, name: str = "id") -> str | None:
    """A relationship id attribute (``r:id``, ``r:embed``)."""
    for key, value in element.attrib.items():
        if local_name(key) == name and _ns(key) in _R:
            return value
    return None


def _on(element: Element | None) -> bool | None:
    """A toggle property: None if absent, else whether it is on."""
    if element is None:
        return None
    value = _val(element)
    return value is None or value.casefold() not in _FALSE


def _int(value: str | None) -> int | None:
    try:
        return None if value is None else int(value)
    except ValueError:
        return None


def _descendants(element: Element, name: str) -> Iterator[Element]:
    stack = list(element)[::-1]
    while stack:
        current = stack.pop()
        if _is_w(current, name):
            yield current
        else:
            stack.extend(list(current)[::-1])


@dataclass(frozen=True)
class _RunLook:
    """What decides whether a run can be seen."""

    vanish: bool | None = None
    half_points: int | None = None
    color: str | None = None
    marked: bool | None = None  # highlight or shading behind the text

    def over(self, base: "_RunLook") -> "_RunLook":
        return _RunLook(
            vanish=base.vanish if self.vanish is None else self.vanish,
            half_points=base.half_points if self.half_points is None else self.half_points,
            color=base.color if self.color is None else self.color,
            marked=base.marked if self.marked is None else self.marked,
        )

    def hidden(self, *, shaded: bool) -> bool:
        """Whether the run cannot be seen; white text counts only on an unshaded paragraph."""
        return bool(
            self.vanish
            or (self.half_points is not None and self.half_points < DOCX_MIN_VISIBLE_HALF_POINTS)
            or (
                self.color is not None
                and self.color.upper() == _WHITE
                and not self.marked
                and not shaded
            )
        )


def _run_look(properties: Element | None) -> _RunLook:
    if properties is None:
        return _RunLook()
    highlight = _val(_child(properties, "highlight"))
    shading = _val(_child(properties, "shd"), "fill")
    marked: bool | None = None
    if highlight is not None or shading is not None:
        marked = (highlight not in (None, "none")) or (
            shading is not None and shading.upper() not in ("AUTO", _WHITE)
        )
    return _RunLook(
        vanish=_on(_child(properties, "vanish")),
        half_points=_int(_val(_child(properties, "sz"))),
        color=_val(_child(properties, "color")),
        marked=marked,
    )


@dataclass(frozen=True)
class _Style:
    based_on: str | None
    outline: int | None
    numbering: tuple[str, int] | None
    look: _RunLook
    heading: int | None


@dataclass(frozen=True)
class _Level:
    format: str
    text: str
    start: int


@dataclass
class _Paragraph:
    """What one paragraph yields, in order."""

    visible: list[str] = field(default_factory=list)
    hidden: list[str] = field(default_factory=list)
    comments: list[str] = field(default_factory=list)
    not_converted: int = 0
    # Text boxes to lay out after the paragraph, and whether they are hidden
    # (anchored in a hidden or deleted run): hidden boxes stay hidden.
    boxes: list[tuple[Element, bool]] = field(default_factory=list)
    page_break: bool = False
    # Drawn on a shaded paragraph or in a table, whose cell or table style may
    # colour the background: white text there is not taken for hidden.
    shaded: bool = False

    def text(self, hidden: bool, piece: str) -> None:
        (self.hidden if hidden else self.visible).append(piece)


@dataclass
class _Pending:
    kind: BlockType
    text: str = ""
    flags: tuple[BlockFlag, ...] = ()
    heading_level: int | None = None
    table: Table | None = None


class _Reader:
    def __init__(self, package: Package, main: str) -> None:
        self._package = package
        self._rels = package.relationships(main)
        self._document = package.xml(main)
        self._styles = self._read_styles()
        self._levels, self._nums = self._read_numbering()
        self._counters: dict[str, list[int]] = {}
        self._footnotes = self._read_notes("footnotes", "footnote")
        self._endnotes = self._read_notes("endnotes", "endnote")
        self._comments = self._read_comments()
        self._note_number = 0
        self._page_notes: list[str] = []
        self._end_notes: list[str] = []
        self._pages: list[list[_Pending]] = [[]]
        self._section_start = 0

    # --- Parts ------------------------------------------------------------

    def _part(self, kind: str) -> Element | None:
        for relationship in self._rels.values():
            if (
                relationship.type.endswith(f"/{kind}")
                and not relationship.external
                and self._package.has(relationship.target)
            ):
                return self._package.xml(relationship.target)
        return None

    def _read_styles(self) -> dict[str, _Style]:
        root = self._part("styles")
        styles: dict[str, _Style] = {}
        if root is None:
            return styles
        for style in _children(root, "style"):
            style_id = _val(style, "styleId")
            if style_id is None:
                continue
            paragraph = _child(style, "pPr")
            numbering = _child(paragraph, "numPr")
            num_id = _val(_child(numbering, "numId"))
            name = (_val(_child(style, "name")) or "").casefold()
            match = _HEADING_STYLE.fullmatch(name)
            styles[style_id] = _Style(
                based_on=_val(_child(style, "basedOn")),
                outline=_int(_val(_child(paragraph, "outlineLvl"))),
                numbering=None
                if num_id is None
                else (num_id, _int(_val(_child(numbering, "ilvl"))) or 0),
                look=_run_look(_child(style, "rPr")),
                heading=1 if name == "title" else (int(match.group(1)) if match else None),
            )
        return styles

    def _chain(self, style_id: str | None) -> Iterator[_Style]:
        seen: set[str] = set()
        while style_id is not None and style_id not in seen and style_id in self._styles:
            seen.add(style_id)
            style = self._styles[style_id]
            yield style
            style_id = style.based_on

    def _look(self, style_id: str | None) -> _RunLook:
        look = _RunLook()
        for style in self._chain(style_id):
            look = look.over(style.look)
        return look

    def _read_numbering(self) -> tuple[dict[str, dict[int, _Level]], dict[str, str]]:
        root = self._part("numbering")
        abstract: dict[str, dict[int, _Level]] = {}
        nums: dict[str, str] = {}
        if root is None:
            return abstract, nums
        for definition in _children(root, "abstractNum"):
            levels: dict[int, _Level] = {}
            for level in _children(definition, "lvl"):
                index = _int(_val(level, "ilvl"))
                if index is not None:
                    levels[index] = _Level(
                        format=_val(_child(level, "numFmt")) or "decimal",
                        text=_val(_child(level, "lvlText")) or "",
                        start=_int(_val(_child(level, "start"))) or 1,
                    )
            key = _val(definition, "abstractNumId")
            if key is not None:
                abstract[key] = levels
        for num in _children(root, "num"):
            num_id, key = _val(num, "numId"), _val(_child(num, "abstractNumId"))
            if num_id is not None and key is not None:
                nums[num_id] = key
        return abstract, nums

    def _read_notes(self, part: str, name: str) -> dict[str, Element]:
        root = self._part(part)
        if root is None:
            return {}
        return {
            note_id: note
            for note in _children(root, name)
            if (note_id := _val(note, "id")) is not None
            and _val(note, "type") not in ("separator", "continuationSeparator")
        }

    def _read_comments(self) -> dict[str, Element]:
        root = self._part("comments")
        if root is None:
            return {}
        return {
            comment_id: comment
            for comment in _children(root, "comment")
            if (comment_id := _val(comment, "id")) is not None
        }

    # --- Body ---------------------------------------------------------------

    def pages(self) -> list[Page]:
        body = _child(self._document, "body")
        if body is None:
            return [self._page(0, [])]
        self._body(body, top=True)
        # Endnotes close the document, before the last section's footer.
        self._page_notes.extend(self._end_notes)
        self._end_section(_child(body, "sectPr"))
        self._close_notes()
        pages = [blocks for blocks in self._pages if blocks] or [[]]
        return [self._page(index, blocks) for index, blocks in enumerate(pages)]

    def _body(self, container: Element, *, top: bool = False, hidden: bool = False) -> None:
        for element in container:
            if _is_w(element, "p"):
                self._paragraph(element, top=top, hidden=hidden)
            elif _is_w(element, "tbl"):
                self._table(element, hidden=hidden)
            elif _is_w(element, "sdt"):
                content = _child(element, "sdtContent")
                if content is not None:
                    self._body(content, top=top, hidden=hidden)
            elif _ns(element.tag) == _MC and local_name(element.tag) == "AlternateContent":
                choice = next((c for c in element if local_name(c.tag) == "Choice"), None)
                if choice is not None:
                    self._body(choice, top=top, hidden=hidden)

    def _paragraph(self, paragraph: Element, *, top: bool, hidden: bool = False) -> None:
        properties = _child(paragraph, "pPr")
        style_id = _val(_child(properties, "pStyle"))
        if top and _on(_child(properties, "pageBreakBefore")):
            self._new_page()
        parts = _Paragraph(shaded=_shaded(properties))
        self._inline(paragraph, parts, self._look(style_id), hidden=hidden)
        text = "".join(parts.visible)
        if text.strip():
            self._add_paragraph(text, properties, style_id)
        concealed = "".join(parts.hidden)
        if concealed.strip():
            self._add(_Pending(BlockType.PARAGRAPH, concealed, (BlockFlag.HIDDEN,)))
        for comment in parts.comments:
            self._add(_Pending(BlockType.PARAGRAPH, comment, (BlockFlag.HIDDEN,)))
        for _ in range(parts.not_converted):
            self._add(_Pending(BlockType.IMAGE, flags=(BlockFlag.ILLEGIBLE,)))
        for box, box_hidden in parts.boxes:
            self._body(box, hidden=box_hidden)
        if top and (parts.page_break or _child(properties, "sectPr") is not None):
            section = _child(properties, "sectPr")
            if section is not None:
                self._end_section(section)
            self._new_page()

    def _add_paragraph(self, text: str, properties: Element | None, style_id: str | None) -> None:
        outline = _int(_val(_child(properties, "outlineLvl")))
        heading: int | None = None
        numbering: tuple[str, int] | None = None
        numbering_element = _child(properties, "numPr")
        if numbering_element is not None:
            num_id = _val(_child(numbering_element, "numId"))
            if num_id is not None:
                numbering = (num_id, _int(_val(_child(numbering_element, "ilvl"))) or 0)
        for style in self._chain(style_id):
            outline = style.outline if outline is None else outline
            heading = style.heading if heading is None else heading
            numbering = style.numbering if numbering is None else numbering
        if outline is not None and 0 <= outline < MAX_HEADING_LEVEL:
            heading = outline + 1
        if heading is not None:
            level = min(heading, MAX_HEADING_LEVEL)
            self._add(_Pending(BlockType.HEADING, text, heading_level=level))
            return
        if numbering is not None and numbering[0] != "0":
            label = self._label(*numbering)
            if label is not None:
                self._add(_Pending(BlockType.LIST_ITEM, f"{label} {text}" if label else text))
                return
        self._add(_Pending(BlockType.PARAGRAPH, text))

    def _label(self, num_id: str, level: int) -> str | None:
        """The item's label: "" for a bullet, "2.1." for a numbered item, None if unknown."""
        levels = self._levels.get(self._nums.get(num_id, ""), {})
        definition = levels.get(level)
        if definition is None:
            return None
        if definition.format in ("bullet", "none"):
            return ""
        counters = self._counters.setdefault(num_id, [])
        while len(counters) <= level:
            counters.append(levels.get(len(counters), definition).start - 1)
        counters[level] += 1
        for deeper in range(level + 1, len(counters)):
            counters[deeper] = levels.get(deeper, definition).start - 1
        label = definition.text
        for index in range(level + 1):
            number_format = levels.get(index, definition).format
            label = label.replace(f"%{index + 1}", _number(counters[index], number_format))
        return label.strip()

    def _inline(self, element: Element, parts: _Paragraph, look: _RunLook, *, hidden: bool) -> None:
        for child in element:
            namespace, name = _ns(child.tag), local_name(child.tag)
            if namespace in _MATH:
                if name in ("oMath", "oMathPara"):
                    parts.not_converted += 1
                continue
            if namespace == _MC and name == "AlternateContent":
                choice = next((c for c in child if local_name(c.tag) == "Choice"), None)
                if choice is not None:
                    self._inline(choice, parts, look, hidden=hidden)
                continue
            if namespace not in _W:
                continue
            if name == "r":
                self._run(child, parts, look, hidden=hidden)
            elif name == "hyperlink":
                self._hyperlink(child, parts, look, hidden=hidden)
            elif name in _HIDDEN_CONTAINERS:
                self._inline(child, parts, look, hidden=True)
            elif name in _TRANSPARENT:
                self._inline(child, parts, look, hidden=hidden)

    def _run(self, run: Element, parts: _Paragraph, base: _RunLook, *, hidden: bool) -> None:
        properties = _child(run, "rPr")
        look = _run_look(properties).over(self._look(_val(_child(properties, "rStyle"))))
        look = look.over(base)
        concealed = hidden or look.hidden(shaded=parts.shaded)
        for item in run:
            if _ns(item.tag) == _MC and local_name(item.tag) == "AlternateContent":
                choice = next((c for c in item if local_name(c.tag) == "Choice"), None)
                if choice is not None:
                    self._drawing(choice, parts, hidden=concealed)
                continue
            if _ns(item.tag) not in _W:
                continue
            name = local_name(item.tag)
            if name in ("t", "delText"):
                parts.text(concealed or name == "delText", item.text or "")
            elif name == "tab":
                parts.text(concealed, "\t")
            elif name == "br":
                if _val(item, "type") == "page":
                    parts.page_break = True
                else:
                    parts.text(concealed, "\n")
            elif name == "cr":
                parts.text(concealed, "\n")
            elif name == "noBreakHyphen":
                parts.text(concealed, "-")
            elif name in ("footnoteReference", "endnoteReference"):
                self._note(item, parts, concealed, footnote=name == "footnoteReference")
            elif name == "commentReference":
                comment = self._comments.get(_val(item, "id") or "")
                if comment is not None:
                    parts.comments.append(self._plain(comment))
            elif name in ("drawing", "pict", "object"):
                self._drawing(item, parts, hidden=concealed)

    def _drawing(self, item: Element, parts: _Paragraph, *, hidden: bool) -> None:
        """A text box is read; anything else drawn is marked not converted."""
        boxes = list(_descendants(item, "txbxContent"))
        if boxes:
            parts.boxes.extend((box, hidden) for box in boxes)
        else:
            parts.not_converted += 1

    def _hyperlink(self, link: Element, parts: _Paragraph, look: _RunLook, *, hidden: bool) -> None:
        inner = _Paragraph(shaded=parts.shaded)
        self._inline(link, inner, look, hidden=hidden)
        text = "".join(inner.visible)
        rid = _rid(link)
        target: Relationship | None = None if rid is None else self._rels.get(rid)
        if (
            text.strip()
            and target is not None
            and target.external
            and _LINK.fullmatch(target.target)
        ):
            parts.text(False, f"[{text}]({target.target})")
        else:
            parts.visible.extend(inner.visible)
        parts.hidden.extend(inner.hidden)
        parts.comments.extend(inner.comments)
        parts.not_converted += inner.not_converted
        parts.boxes.extend(inner.boxes)
        parts.page_break |= inner.page_break

    def _note(self, item: Element, parts: _Paragraph, hidden: bool, *, footnote: bool) -> None:
        notes = self._footnotes if footnote else self._endnotes
        note = notes.get(_val(item, "id") or "")
        if note is None:
            return
        self._note_number += 1
        marker = f"[^{self._note_number}]"
        parts.text(hidden, marker)
        if not hidden:
            (self._page_notes if footnote else self._end_notes).append(
                f"{marker}: {self._plain(note)}"
            )

    def _plain(self, container: Element) -> str:
        """The visible text of a note, comment, header or footer, one line per paragraph."""
        lines = []
        for paragraph in _descendants(container, "p"):
            parts = _Paragraph()
            self._inline(paragraph, parts, self._look(_paragraph_style(paragraph)), hidden=False)
            line = " ".join("".join(parts.visible).split())
            if line:
                lines.append(line)
        return "\n".join(lines)

    # --- Tables -------------------------------------------------------------

    def _table(self, table: Element, *, hidden: bool = False) -> None:
        rows: list[list[tuple[str, int]]] = []
        header_rows = 0
        concealed: list[str] = []
        not_converted = 0
        boxes: list[tuple[Element, bool]] = []
        for row in _children(table, "tr"):
            row_properties = _child(row, "trPr")
            if _on(_child(row_properties, "tblHeader")) and header_rows == len(rows):
                header_rows += 1
            cells: list[tuple[str, int]] = []
            for cell in _children(row, "tc"):
                cell_properties = _child(cell, "tcPr")
                span = max(1, _int(_val(_child(cell_properties, "gridSpan"))) or 1)
                merge = _child(cell_properties, "vMerge")
                continued = merge is not None and _val(merge) in (None, "continue")
                parts = _Paragraph(shaded=True)
                for paragraph in _descendants(cell, "p"):
                    style = _paragraph_style(paragraph)
                    before = len(parts.visible)
                    self._inline(paragraph, parts, self._look(style), hidden=hidden)
                    if len(parts.visible) > before:
                        parts.visible.append(" ")
                text = " ".join("".join(parts.visible).split())
                cells.append(("" if continued else text, span))
                concealed.extend(parts.hidden + parts.comments)
                not_converted += parts.not_converted
                boxes.extend(parts.boxes)
            if cells:
                rows.append(cells)
        # A table with no visible text (all hidden, or inside a hidden box) is
        # not drawn: its text is in the hidden block below.
        if any(text for cells in rows for text, _ in cells):
            self._table_blocks(rows, header_rows)
        if any(text.strip() for text in concealed):
            text = "\n".join(text for text in concealed if text.strip())
            self._add(_Pending(BlockType.PARAGRAPH, text, (BlockFlag.HIDDEN,)))
        for _ in range(not_converted):
            self._add(_Pending(BlockType.IMAGE, flags=(BlockFlag.ILLEGIBLE,)))
        for box, box_hidden in boxes:
            self._body(box, hidden=box_hidden)

    def _table_blocks(self, rows: list[list[tuple[str, int]]], header_rows: int) -> None:
        """The table, split every ``OFFICE_TABLE_MAX_ROWS`` rows with its header rows repeated."""
        width = max(sum(span for _, span in cells) for cells in rows)
        header = rows[:header_rows]
        body = rows[header_rows:]
        size = max(1, OFFICE_TABLE_MAX_ROWS - len(header))
        parts_of_body = [body[start : start + size] for start in range(0, len(body), size)] or [[]]
        for part in parts_of_body:
            self._add(_Pending(BlockType.TABLE, table=_grid(header + part, width, len(header))))

    # --- Pages and sections -------------------------------------------------

    def _add(self, pending: _Pending) -> None:
        if pending.kind is BlockType.PARAGRAPH and not pending.text and not pending.flags:
            return
        self._pages[-1].append(pending)

    def _new_page(self) -> None:
        self._close_notes()
        if self._pages[-1]:
            self._pages.append([])

    def _close_notes(self) -> None:
        for note in self._page_notes:
            self._pages[-1].append(_Pending(BlockType.FOOTNOTE, note))
        self._page_notes = []

    def _end_section(self, section: Element | None) -> None:
        """Put the section's header on its first page and its footer on its last."""
        self._close_notes()
        if section is not None:
            header = self._margin(section, "headerReference")
            footer = self._margin(section, "footerReference")
            if header:
                self._pages[self._section_start].insert(0, _Pending(BlockType.HEADER, header))
            if footer:
                self._pages[-1].append(_Pending(BlockType.FOOTER, footer))
        # The next section starts on the next page that gets content.
        self._section_start = len(self._pages) if self._pages[-1] else len(self._pages) - 1

    def _margin(self, section: Element, reference: str) -> str:
        references = {_val(ref, "type") or "default": ref for ref in _children(section, reference)}
        chosen = references.get("default")
        if chosen is None:
            chosen = references.get("first")
        rid = None if chosen is None else _rid(chosen)
        relationship = None if rid is None else self._rels.get(rid)
        if (
            relationship is None
            or relationship.external
            or not self._package.has(relationship.target)
        ):
            return ""
        return self._plain(self._package.xml(relationship.target))

    def _page(self, index: int, pending: Iterable[_Pending]) -> Page:
        blocks = tuple(
            Block(
                id=f"b{number}",
                type=item.kind,
                text="" if BlockFlag.ILLEGIBLE in item.flags else item.text,
                heading_level=item.heading_level,
                table=item.table,
                reading_order=number,
                origin_engine=ENGINE_NAME,
                flags=item.flags,
            )
            for number, item in enumerate(pending)
        )
        return Page(index=index, width=1.0, height=1.0, origin=PageOrigin.NATIVE, blocks=blocks)


def _shaded(properties: Element | None) -> bool:
    """Whether a paragraph has a background colour of its own."""
    fill = _val(_child(properties, "shd"), "fill")
    return fill is not None and fill.upper() not in ("AUTO", _WHITE)


def _paragraph_style(paragraph: Element) -> str | None:
    return _val(_child(_child(paragraph, "pPr"), "pStyle"))


def _grid(rows: list[list[tuple[str, int]]], width: int, header_rows: int) -> Table:
    cells: list[TableCell] = []
    for row_index, row in enumerate(rows):
        column = 0
        for text, span in row:
            span = min(span, width - column)
            if span < 1:
                break
            cells.append(TableCell(row=row_index, col=column, text=text, col_span=span))
            column += span
    return Table(n_rows=len(rows), n_cols=width, header_rows=header_rows, cells=tuple(cells))


def _number(value: int, number_format: str) -> str:
    """A list counter in Word's number formats; unknown formats as decimals."""
    if number_format in ("lowerLetter", "upperLetter") and value > 0:
        letters = ""
        while value > 0:
            value, rest = divmod(value - 1, 26)
            letters = chr(ord("a") + rest) + letters
        return letters if number_format == "lowerLetter" else letters.upper()
    if number_format in ("lowerRoman", "upperRoman") and 0 < value < _ROMAN_LIMIT:
        roman = _roman(value)
        return roman if number_format == "lowerRoman" else roman.upper()
    return str(value)


def _roman(value: int) -> str:
    numerals = (
        (1000, "m"), (900, "cm"), (500, "d"), (400, "cd"), (100, "c"), (90, "xc"),
        (50, "l"), (40, "xl"), (10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i"),
    )  # fmt: skip
    text = ""
    for number, numeral in numerals:
        while value >= number:
            text += numeral
            value -= number
    return text
