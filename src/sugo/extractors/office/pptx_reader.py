"""PowerPoint presentations (PPTX) as IR pages (ADR-054). Runs only in the worker process.

One page per slide, in presentation order. A slide's shapes are put in
reading order by position, through the XY-cut shared with the image and PDF
extractors; group shapes are entered and their children placed on the slide.

- The title placeholder becomes a heading; footer, date and slide number
  placeholders become footer and page number blocks, which the edge
  cleaners remove when they repeat (ADR-044).
- Paragraphs with a bullet become list items with their level; numbered
  ones keep their label ("2."). Whether a paragraph has a bullet comes from
  the paragraph, then the shape, its layout and master placeholders, and the
  master's text styles, as PowerPoint decides it.
- Tables become tables, a merged cell's text in its first cell, split every
  ``OFFICE_TABLE_MAX_ROWS`` rows with the header row repeated; SmartArt
  becomes its nodes' text, nested as drawn; hyperlinks to outside addresses
  become Markdown links.

Layouts and masters are opened only for the positions and bullets their
placeholders give: text they show by themselves ("Click to add title") is
never read. External relationships are never followed.

What a reader does not see is kept but flagged ``hidden``, so the hidden text
cleaner removes it with a reason: hidden slides (every block), speaker notes,
comments, and shapes marked hidden or placed entirely outside the slide.
Pictures, charts, media, ink, equations and embedded objects are not
guessed: each becomes a block marked illegible ("not converted").

Every slide's tables are counted when the file is opened, so a table that
would make the serializer draw a huge grid refuses the file before its first
page. Each slide is then laid out when its page is asked for; a slide whose
parts turn out broken is reported as failed, never dropped.
"""

import math
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

from sugo.core.constants import (
    MAX_LIST_LEVEL,
    OFFICE_TABLE_MAX_ROWS,
    PPTX_DEFAULT_SLIDE_HEIGHT_EMU,
    PPTX_DEFAULT_SLIDE_WIDTH_EMU,
    PPTX_EMU_PER_POINT,
    PPTX_LINE_HEIGHT,
    PPTX_MAX_COORDINATE,
    PPTX_MAX_GRID_CELLS,
)
from sugo.core.models import (
    BBox,
    Block,
    BlockFlag,
    BlockType,
    Page,
    PageOrigin,
    Table,
)
from sugo.extractors.office.docx_reader import counter_text, table_grid
from sugo.extractors.office.package import (
    SAFE_LINK,
    LaidOut,
    Package,
    Relationship,
    chosen_content,
    embedded_image,
)
from sugo.extractors.office.xml_reader import Element, Refusal, local_name
from sugo.extractors.reading_order import text_rows, xy_cut
from sugo.i18n import N_

ENGINE_NAME = "pptx"
_P = frozenset(
    {
        "http://schemas.openxmlformats.org/presentationml/2006/main",
        "http://purl.oclc.org/ooxml/presentationml/main",
    }
)
_A = frozenset(
    {
        "http://schemas.openxmlformats.org/drawingml/2006/main",
        "http://purl.oclc.org/ooxml/drawingml/main",
    }
)
_R = frozenset(
    {
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
        "http://purl.oclc.org/ooxml/officeDocument/relationships",
    }
)
_DGM = frozenset(
    {
        "http://schemas.openxmlformats.org/drawingml/2006/diagram",
        "http://purl.oclc.org/ooxml/drawingml/diagram",
    }
)
# PowerPoint 2010's own elements, such as ink.
_P14 = frozenset({"http://schemas.microsoft.com/office/powerpoint/2010/main"})
_MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"
_DAMAGED = N_("the Office file is damaged, or too large to read safely")
_TOO_LARGE = N_("the Office file is too large to read safely")
_TRUE = frozenset({"1", "true", "on"})
_FALSE = frozenset({"0", "false", "off"})
_TITLES = frozenset({"title", "ctrTitle"})
_MARGINS = {
    "ftr": BlockType.FOOTER,
    "dt": BlockType.FOOTER,
    "hdr": BlockType.HEADER,
    "sldNum": BlockType.PAGE_NUMBER,
}
# Placeholders of a notes page that are not the notes themselves.
_NOT_NOTES = frozenset({"sldImg", *_MARGINS})
_BULLETS = frozenset({"buNone", "buChar", "buAutoNum", "buBlip"})
# "arabicPeriod" -> "1.", "alphaLcParenR" -> "a)", "romanUcParenBoth" -> "(I)".
_SCHEME = re.compile(r"(arabic|alpha|roman)(Lc|Uc)?(ParenBoth|ParenR|Period|Plain)")
_FORMATS = {
    ("arabic", ""): "decimal",
    ("alpha", "Lc"): "lowerLetter",
    ("alpha", "Uc"): "upperLetter",
    ("roman", "Lc"): "lowerRoman",
    ("roman", "Uc"): "upperRoman",
}


def read_pptx(data: bytes) -> tuple[int, Callable[[int], Page]]:
    """Check a presentation and return its number of pages and a function that reads one.

    Raises:
        Refusal: OFFICE_TOO_LARGE or OFFICE_INVALID, here or from the page function.
    """
    count, laid_out = lay_out_pptx(data)
    return count, lambda index: laid_out(index)[0]


def lay_out_pptx(data: bytes) -> tuple[int, Callable[[int], LaidOut]]:
    """As ``read_pptx``, each page with the parts of its pictures.

    Raises:
        Refusal: OFFICE_TOO_LARGE or OFFICE_INVALID, here or from the page function.
    """
    deck = _Deck(Package(data))
    return max(1, len(deck.slides)), deck.page


def _ns(tag: str) -> str:
    return tag[1:].split("}", 1)[0] if tag.startswith("{") else ""


def _is(element: Element, namespaces: frozenset[str], name: str) -> bool:
    return local_name(element.tag) == name and _ns(element.tag) in namespaces


def _child(element: Element | None, namespaces: frozenset[str], name: str) -> Element | None:
    if element is None:
        return None
    return next((child for child in element if _is(child, namespaces, name)), None)


def _local_child(element: Element | None, name: str) -> Element | None:
    """The first child with this local name, in any namespace."""
    return next((child for child in _kids(element) if local_name(child.tag) == name), None)


def _kids(element: Element | None) -> list[Element]:
    """An element's children; none for a missing element (an element's truth value is not used)."""
    return [] if element is None else list(element)


def _path(element: Element | None, *steps: tuple[frozenset[str], str]) -> Element | None:
    for namespaces, name in steps:
        element = _child(element, namespaces, name)
    return element


def _rid(element: Element | None, name: str = "id") -> str | None:
    """A relationship id attribute (``r:id``, ``r:embed``, ``r:dm``)."""
    if element is None:
        return None
    for key, value in element.attrib.items():
        if local_name(key) == name and _ns(key) in _R:
            return value
    return None


def _int(value: str | None) -> int | None:
    try:
        return None if value is None else int(value)
    except ValueError:
        return None


def _is_alternate(element: Element) -> bool:
    return _ns(element.tag) == _MC and local_name(element.tag) == "AlternateContent"


def _texts(element: Element) -> Iterator[str]:
    """Text of every DrawingML ``a:t`` and PresentationML ``p:text`` inside, in order.

    Used only for comments, which are hidden whatever they hold.
    """
    stack = [element]
    while stack:
        current = stack.pop()
        if (_is(current, _A, "t") or _is(current, _P, "text")) and current.text:
            yield current.text
        stack.extend(list(current)[::-1])


@dataclass(frozen=True)
class _Box:
    """A position on the slide, in EMU."""

    x: float
    y: float
    width: float
    height: float


@dataclass(frozen=True)
class _Map:
    """Maps a group's child coordinates onto the slide."""

    dx: float = 0.0
    dy: float = 0.0
    sx: float = 1.0
    sy: float = 1.0

    def box(self, box: _Box) -> _Box:
        return _Box(
            self.dx + box.x * self.sx,
            self.dy + box.y * self.sy,
            box.width * self.sx,
            box.height * self.sy,
        )

    def into(self, transform: Element | None) -> "_Map":
        """The map for the children of a group with this ``a:xfrm``."""
        own = _offset_extent(transform)
        child = _offset_extent(transform, offset="chOff", extent="chExt")
        if own is None or child is None:
            return self
        sx = own.width / child.width if child.width > 0 else 1.0
        sy = own.height / child.height if child.height > 0 else 1.0
        return _Map(
            dx=self.dx + (own.x - child.x * sx) * self.sx,
            dy=self.dy + (own.y - child.y * sy) * self.sy,
            sx=self.sx * sx,
            sy=self.sy * sy,
        )


def _offset_extent(
    transform: Element | None, *, offset: str = "off", extent: str = "ext"
) -> _Box | None:
    """A position from ``a:off`` and ``a:ext``; None without an offset.

    A missing size is no size: the shape is still where its offset says, on
    the slide or off it. Values beyond the standard's range are brought just
    past it, so a shape placed absurdly far stays off the slide.
    """
    position = _child(transform, _A, offset)
    if position is None:
        return None
    size = _child(transform, _A, extent)
    x, y = _int(position.attrib.get("x")), _int(position.attrib.get("y"))
    if x is None or y is None:
        return None
    width = 0 if size is None else _int(size.attrib.get("cx")) or 0
    height = 0 if size is None else _int(size.attrib.get("cy")) or 0
    limit = PPTX_MAX_COORDINATE + 1

    def bounded(value: int) -> float:
        return float(min(max(value, -limit), limit))

    return _Box(bounded(x), bounded(y), max(bounded(width), 0.0), max(bounded(height), 0.0))


@dataclass(frozen=True)
class _Placeholder:
    type: str
    idx: str | None
    box: _Box | None
    styles: Element | None  # the shape's a:lstStyle


@dataclass(frozen=True)
class _Template:
    """A layout or master: only its placeholders' positions and list styles are used."""

    placeholders: tuple[_Placeholder, ...]
    # Master only: title, body and other text styles (p:txStyles).
    text_styles: dict[str, Element]
    master: str | None  # a layout's master part

    def find(self, kind: str, idx: str | None) -> _Placeholder | None:
        """A layout's placeholder for a slide's: same index, else same type."""
        if idx is not None:
            for placeholder in self.placeholders:
                if placeholder.idx == idx:
                    return placeholder
        return next((p for p in self.placeholders if p.type == kind), None)

    def find_family(self, kind: str) -> _Placeholder | None:
        """A master's placeholder for a layout's: the title, the body, or one of the same type."""
        family = _family(kind)
        return next((p for p in self.placeholders if _family(p.type) == family), None)


def _family(kind: str) -> str:
    """The master placeholder a type inherits from: title, body, or its own type."""
    if kind in _TITLES:
        return "title"
    if kind in _MARGINS or kind == "sldImg":
        return kind
    return "body"


@dataclass
class _Pending:
    kind: BlockType
    text: str = ""
    flags: tuple[BlockFlag, ...] = ()
    heading_level: int | None = None
    list_level: int | None = None
    table: Table | None = None
    bbox: BBox | None = None
    # The part of a picture marked not converted, for OCR in Sugo's process.
    image: str | None = None


@dataclass
class _Item:
    """What one shape yields, and where it sits on the slide."""

    blocks: list[_Pending]
    bbox: BBox


@dataclass
class _Slide:
    """One slide being laid out."""

    rels: dict[str, Relationship]
    layout: _Template | None
    master: _Template | None
    width: float
    height: float
    placed: list[_Item] = field(default_factory=list)
    # Shapes whose position is unknown, in document order, after the placed ones.
    unplaced: list[list[_Pending]] = field(default_factory=list)


@dataclass
class _Paragraph:
    text: str
    level: int
    # None: no bullet; "": a bullet; "2.": a numbered paragraph's label.
    label: str | None
    # Equations in the paragraph, each marked not converted after its text.
    formulas: int = 0


class _Deck:
    def __init__(self, package: Package) -> None:
        self._package = package
        main = package.main_part()
        self._rels = package.relationships(main)
        presentation = package.xml(main)
        size = _child(presentation, _P, "sldSz")
        width = _int(None if size is None else size.attrib.get("cx"))
        height = _int(None if size is None else size.attrib.get("cy"))
        if not (width and 0 < width <= PPTX_MAX_COORDINATE):
            width = PPTX_DEFAULT_SLIDE_WIDTH_EMU
        if not (height and 0 < height <= PPTX_MAX_COORDINATE):
            height = PPTX_DEFAULT_SLIDE_HEIGHT_EMU
        self._width, self._height = float(width), float(height)
        self.slides: list[str] = []
        seen: set[str] = set()
        for slide_id in _kids(_path(presentation, (_P, "sldIdLst"))):
            if not _is(slide_id, _P, "sldId"):
                continue
            relationship = self._rels.get(_rid(slide_id) or "")
            if (
                relationship is None
                or relationship.external
                or not package.has(relationship.target)
                # PowerPoint never lists a slide twice; a repeated part would
                # be laid out again and again from one copy of its bytes.
                or relationship.target.casefold() in seen
            ):
                raise Refusal("OFFICE_INVALID", _DAMAGED)
            seen.add(relationship.target.casefold())
            self.slides.append(relationship.target)
        self._templates: dict[str, _Template] = {}
        self._check_tables()

    def _check_tables(self) -> None:
        """Refuse the file, before its first page, if its tables would draw too many cells.

        A slide that turns out broken here is left to its page, which is
        then marked illegible.

        Raises:
            Refusal: OFFICE_TOO_LARGE.
        """
        cells = 0
        for part in self.slides:
            try:
                root = self._package.xml(part)
            except Refusal as refusal:
                if refusal.code == "OFFICE_TOO_LARGE":
                    raise
                continue
            stack = [root]
            while stack:
                element = stack.pop()
                if _is(element, _A, "tbl"):
                    cells += _grid_size(*_table_cells(element))
                    if cells > PPTX_MAX_GRID_CELLS:
                        raise Refusal("OFFICE_TOO_LARGE", _TOO_LARGE)
                else:
                    stack.extend(element)

    # --- Layouts and masters ------------------------------------------------

    def _template(self, part: str, *, master: bool) -> _Template:
        cached = self._templates.get(part.casefold())
        if cached is not None:
            return cached
        root = self._package.xml(part)
        placeholders = []
        for shape in _kids(_path(root, (_P, "cSld"), (_P, "spTree"))):
            if not _is(shape, _P, "sp"):
                continue
            ph = _path(shape, (_P, "nvSpPr"), (_P, "nvPr"), (_P, "ph"))
            if ph is None:
                continue
            placeholders.append(
                _Placeholder(
                    type=ph.attrib.get("type", "obj"),
                    idx=ph.attrib.get("idx"),
                    box=_offset_extent(_path(shape, (_P, "spPr"), (_A, "xfrm"))),
                    styles=_path(shape, (_P, "txBody"), (_A, "lstStyle")),
                )
            )
        text_styles: dict[str, Element] = {}
        if master:
            for style in _kids(_child(root, _P, "txStyles")):
                text_styles[local_name(style.tag)] = style
        parent = None
        if not master:
            parent = self._related(part, "/slideMaster")
        template = _Template(tuple(placeholders), text_styles, parent)
        self._templates[part.casefold()] = template
        return template

    def _related(
        self, part: str, kind: str, rels: dict[str, Relationship] | None = None
    ) -> str | None:
        """The first internal part this part relates to with a relationship of this kind."""
        for relationship in (
            rels if rels is not None else self._package.relationships(part)
        ).values():
            if (
                relationship.type.endswith(kind)
                and not relationship.external
                and self._package.has(relationship.target)
            ):
                return relationship.target
        return None

    # --- Slides -------------------------------------------------------------

    def page(self, index: int) -> LaidOut:
        """Lay out one slide as a page, with the parts of its pictures.

        Raises:
            Refusal: OFFICE_INVALID or OFFICE_TOO_LARGE if the slide's parts are broken.
        """
        if not self.slides:
            return self._page(index, [])
        part = self.slides[index]
        rels = self._package.relationships(part)
        root = self._package.xml(part)
        layout_part = self._related(part, "/slideLayout", rels)
        layout = None if layout_part is None else self._template(layout_part, master=False)
        master = None
        if layout is not None and layout.master is not None:
            master = self._template(layout.master, master=True)
        slide = _Slide(rels, layout, master, self._width, self._height)
        tree = _path(root, (_P, "cSld"), (_P, "spTree"))
        if tree is not None:
            self._shapes(slide, tree, _Map(), hidden=False)
        blocks = _in_reading_order(slide)
        notes = self._related(part, "/notesSlide", rels)
        if notes is not None:
            text = self._notes(notes)
            if text:
                blocks.append(_Pending(BlockType.PARAGRAPH, text, (BlockFlag.HIDDEN,)))
        for relationship in rels.values():
            if (
                relationship.type.endswith("/comments")
                and not relationship.external
                and self._package.has(relationship.target)
            ):
                blocks.extend(
                    _Pending(BlockType.PARAGRAPH, comment, (BlockFlag.HIDDEN,))
                    for comment in self._comments(relationship.target)
                )
        if root.attrib.get("show", "1").casefold() in _FALSE:
            for block in blocks:
                block.flags = (*block.flags, BlockFlag.HIDDEN)
        return self._page(index, blocks)

    def _page(self, index: int, pending: list[_Pending]) -> LaidOut:
        blocks = tuple(
            Block(
                id=f"b{number}",
                type=item.kind,
                text="" if BlockFlag.ILLEGIBLE in item.flags else item.text,
                heading_level=item.heading_level,
                list_level=item.list_level,
                table=item.table,
                bbox=item.bbox,
                reading_order=number,
                origin_engine=ENGINE_NAME,
                flags=item.flags,
            )
            for number, item in enumerate(pending)
        )
        page = Page(
            index=index,
            width=self._width / PPTX_EMU_PER_POINT,
            height=self._height / PPTX_EMU_PER_POINT,
            origin=PageOrigin.NATIVE,
            blocks=blocks,
        )
        images = {f"b{n}": item.image for n, item in enumerate(pending) if item.image is not None}
        return page, images

    def _shapes(self, slide: _Slide, tree: Element, mapping: _Map, *, hidden: bool) -> None:
        for shape in tree:
            if _is_alternate(shape):
                choice = chosen_content(shape)
                if choice is not None:
                    self._shapes(slide, choice, mapping, hidden=hidden)
                continue
            name = local_name(shape.tag)
            if name == "contentPart" and _ns(shape.tag) in _P | _P14:
                # Ink. PowerPoint 2010 writes it in its own namespace.
                info = _local_child(shape, "nvContentPartPr")
                box = _offset_extent(_local_child(shape, "xfrm"))
                ink = _Pending(BlockType.IMAGE, flags=(BlockFlag.ILLEGIBLE,))
                _place(
                    slide, [ink], box, mapping, hidden=hidden or _marked_hidden(info, local=True)
                )
                continue
            if _ns(shape.tag) not in _P:
                continue
            if name == "sp":
                self._shape(slide, shape, mapping, hidden=hidden)
            elif name == "grpSp":
                properties = _child(shape, _P, "grpSpPr")
                concealed = hidden or _marked_hidden(_child(shape, _P, "nvGrpSpPr"))
                inner = mapping.into(_child(properties, _A, "xfrm"))
                self._shapes(slide, shape, inner, hidden=concealed)
            elif name == "graphicFrame":
                self._frame(slide, shape, mapping, hidden=hidden)
            elif name == "pic":
                info = _child(shape, _P, "nvPicPr")
                box = _offset_extent(_path(shape, (_P, "spPr"), (_A, "xfrm")))
                fill = _child(shape, _P, "blipFill")
                part = None if fill is None else embedded_image(fill, slide.rels, self._package)
                image = _Pending(BlockType.IMAGE, flags=(BlockFlag.ILLEGIBLE,), image=part)
                _place(slide, [image], box, mapping, hidden=hidden or _marked_hidden(info))

    def _shape(self, slide: _Slide, shape: Element, mapping: _Map, *, hidden: bool) -> None:
        info = _child(shape, _P, "nvSpPr")
        ph = _path(info, (_P, "nvPr"), (_P, "ph"))
        body = _child(shape, _P, "txBody")
        box = _offset_extent(_path(shape, (_P, "spPr"), (_A, "xfrm")))
        styles = [_child(body, _A, "lstStyle")]
        kind = None if ph is None else ph.attrib.get("type", "obj")
        if ph is not None and kind is not None:
            idx = ph.attrib.get("idx")
            layout = None if slide.layout is None else slide.layout.find(kind, idx)
            inherited = kind if layout is None else layout.type
            master = None if slide.master is None else slide.master.find_family(inherited)
            for template in (layout, master):
                if template is not None:
                    box = box or template.box
                    styles.append(template.styles)
        if slide.master is not None:
            style = "otherStyle"
            if kind is not None:
                style = "titleStyle" if _family(kind) == "title" else "bodyStyle"
            styles.append(slide.master.text_styles.get(style))
        if body is None:
            return
        paragraphs = self._paragraphs(body, styles, slide.rels)
        if not paragraphs:
            return
        blocks: list[_Pending] = []
        if kind in _TITLES:
            text = " ".join(" ".join(p.text.split()) for p in paragraphs if p.text)
            if text:
                blocks.append(_Pending(BlockType.HEADING, text, heading_level=1))
        elif kind in _MARGINS:
            text = "\n".join(p.text for p in paragraphs if p.text)
            if text:
                blocks.append(_Pending(_MARGINS[kind], text))
        if blocks or kind in _TITLES or kind in _MARGINS:
            blocks.extend(_formula() for p in paragraphs for _ in range(p.formulas))
        else:
            # Each paragraph's equations follow its text.
            for paragraph in paragraphs:
                if paragraph.text:
                    blocks.append(_paragraph_block(paragraph))
                blocks.extend(_formula() for _ in range(paragraph.formulas))
        _place(slide, blocks, box, mapping, hidden=hidden or _marked_hidden(info))

    def _frame(self, slide: _Slide, frame: Element, mapping: _Map, *, hidden: bool) -> None:
        """A table, SmartArt, or something drawn that is marked not converted."""
        info = _child(frame, _P, "nvGraphicFramePr")
        box = _offset_extent(_child(frame, _P, "xfrm"))
        data = _path(frame, (_A, "graphic"), (_A, "graphicData"))
        blocks: list[_Pending] = []
        table = _child(data, _A, "tbl")
        relations = _child(data, _DGM, "relIds")
        if table is not None:
            blocks = self._table(table, slide.rels)
        elif relations is not None:
            relationship = slide.rels.get(_rid(relations, "dm") or "")
            if (
                relationship is not None
                and not relationship.external
                and self._package.has(relationship.target)
            ):
                blocks = self._diagram(relationship.target)
        if not blocks and table is None:
            blocks = [_Pending(BlockType.IMAGE, flags=(BlockFlag.ILLEGIBLE,))]
        _place(slide, blocks, box, mapping, hidden=hidden or _marked_hidden(info))

    # --- Text ---------------------------------------------------------------

    def _paragraphs(
        self, body: Element, styles: list[Element | None], rels: dict[str, Relationship]
    ) -> list[_Paragraph]:
        paragraphs: list[_Paragraph] = []
        # Level -> (scheme, last number) of the numbered paragraphs above.
        counters: dict[int, tuple[str, int]] = {}
        for paragraph in body:
            if not _is(paragraph, _A, "p"):
                continue
            properties = _child(paragraph, _A, "pPr")
            level = _int(None if properties is None else properties.attrib.get("lvl")) or 0
            level = min(max(level, 0), MAX_LIST_LEVEL)
            text = _run_text(paragraph, rels)
            # PowerPoint writes an equation as alternate content (a14:m, with
            # a picture of it as the fallback); neither is text.
            formulas = sum(1 for item in paragraph if _is_alternate(item))
            if not text.strip():
                if formulas:
                    paragraphs.append(_Paragraph("", level, None, formulas))
                continue
            bullet = _bullet(properties, level, styles)
            for deeper in [key for key in counters if key > level]:
                del counters[deeper]
            label: str | None = None
            if bullet is None or local_name(bullet.tag) == "buNone":
                counters.pop(level, None)
            elif local_name(bullet.tag) == "buAutoNum":
                scheme = bullet.attrib.get("type", "arabicPeriod")
                previous = counters.get(level)
                start = _int(bullet.attrib.get("startAt")) or 1
                number = previous[1] + 1 if previous and previous[0] == scheme else start
                counters[level] = (scheme, number)
                label = _label(scheme, number)
            else:
                counters.pop(level, None)
                label = ""
            paragraphs.append(_Paragraph(text, level, label, formulas))
        return paragraphs

    def _table(self, table: Element, rels: dict[str, Relationship]) -> list[_Pending]:
        header, cells_by_row = _table_cells(table)
        rows: list[list[tuple[str, int]]] = []
        for cells in cells_by_row:
            row: list[tuple[str, int]] = []
            for cell, span in cells:
                body = _child(cell, _A, "txBody")
                lines = [_run_text(p, rels) for p in _kids(body) if _is(p, _A, "p")]
                text = " ".join(" ".join(lines).split())
                if cell.attrib.get("vMerge", "").casefold() in _TRUE:
                    text = ""  # Its text is in the first cell of the merge.
                row.append((text, span))
            rows.append(row)
        if not any(text for cells in rows for text, _ in cells):
            return []
        width = max(sum(span for _, span in cells) for cells in rows)
        head, body_rows = rows[:header], rows[header:]
        size = max(1, OFFICE_TABLE_MAX_ROWS - len(head))
        parts = [body_rows[start : start + size] for start in range(0, len(body_rows), size)]
        return [
            _Pending(BlockType.TABLE, table=table_grid(head + part, width, len(head)))
            for part in parts or [[]]
        ]

    def _diagram(self, part: str) -> list[_Pending]:
        """SmartArt as list items: each node's text, nested as its parent-child links say."""
        root = self._package.xml(part)
        texts: dict[str, str] = {}
        documents: list[str] = []
        for point in _kids(_child(root, _DGM, "ptLst")):
            if not _is(point, _DGM, "pt"):
                continue
            model_id = point.attrib.get("modelId")
            if model_id is None:
                continue
            kind = point.attrib.get("type", "node")
            if kind == "doc":
                documents.append(model_id)
            elif kind in ("node", "asst"):
                body = _child(point, _DGM, "t")
                if body is not None:
                    # Only the runs, as for shapes: text in extensions is never shown.
                    lines = (_run_text(p, {}) for p in body if _is(p, _A, "p"))
                    text = " ".join(" ".join(lines).split())
                    if text:
                        texts[model_id] = text
                    else:
                        texts.setdefault(model_id, "")
        children: dict[str, list[tuple[int, str]]] = {}
        for link in _kids(_child(root, _DGM, "cxnLst")):
            if not _is(link, _DGM, "cxn") or link.attrib.get("type", "parOf") != "parOf":
                continue
            source, target = link.attrib.get("srcId"), link.attrib.get("destId")
            if source is not None and target is not None:
                order = _int(link.attrib.get("srcOrd")) or 0
                children.setdefault(source, []).append((order, target))
        blocks: list[_Pending] = []
        seen: set[str] = set()
        # Depth-first from the document point; a node reached twice (a loop in
        # a damaged file) is read once.
        stack = [(node, 0) for node in reversed(documents)]
        while stack:
            node, depth = stack.pop()
            if node in seen:
                continue
            seen.add(node)
            shown = texts.get(node)
            if shown:
                level = min(depth, MAX_LIST_LEVEL)
                blocks.append(_Pending(BlockType.LIST_ITEM, shown, list_level=level))
            below = depth + 1 if node in texts else depth
            for _, child in sorted(children.get(node, []), reverse=True):
                stack.append((child, below))
        # Nodes no link reaches still hold text a person sees.
        blocks.extend(
            _Pending(BlockType.LIST_ITEM, text, list_level=0)
            for node, text in texts.items()
            if text and node not in seen
        )
        return blocks

    def _notes(self, part: str) -> str:
        """The speaker notes: text of the notes page's own shapes, a line per paragraph."""
        root = self._package.xml(part)
        lines: list[str] = []
        stack = _kids(_path(root, (_P, "cSld"), (_P, "spTree")))[::-1]
        while stack:
            shape = stack.pop()
            if _is(shape, _P, "grpSp"):
                stack.extend(list(shape)[::-1])
                continue
            if _is_alternate(shape):
                choice = chosen_content(shape)
                stack.extend(_kids(choice)[::-1])
                continue
            if not _is(shape, _P, "sp"):
                continue
            ph = _path(shape, (_P, "nvSpPr"), (_P, "nvPr"), (_P, "ph"))
            if ph is not None and ph.attrib.get("type", "obj") in _NOT_NOTES:
                continue
            body = _child(shape, _P, "txBody")
            for paragraph in _kids(body):
                if _is(paragraph, _A, "p"):
                    line = " ".join(_run_text(paragraph, {}).split())
                    if line:
                        lines.append(line)
        return "\n".join(lines)

    def _comments(self, part: str) -> list[str]:
        """Each comment's text, replies included, as one line."""
        comments = []
        for comment in self._package.xml(part):
            text = " ".join(" ".join(_texts(comment)).split())
            if text:
                comments.append(text)
        return comments


def _marked_hidden(info: Element | None, *, local: bool = False) -> bool:
    """Whether a shape's non-visual properties (``p:cNvPr``) mark it hidden.

    ``local`` finds them whatever their namespace, as for PowerPoint 2010's ink.
    """
    properties = _local_child(info, "cNvPr") if local else _child(info, _P, "cNvPr")
    return properties is not None and properties.attrib.get("hidden", "").casefold() in _TRUE


def _place(
    slide: _Slide, blocks: list[_Pending], box: _Box | None, mapping: _Map, *, hidden: bool
) -> None:
    """Put a shape's blocks on the slide; hidden if marked so or entirely outside the slide."""
    if not blocks:
        return
    if box is not None:
        box = mapping.box(box)
    if box is not None and not all(
        math.isfinite(value) for value in (box.x, box.y, box.width, box.height)
    ):
        # Scaled out of range by nested groups: nowhere a person can see.
        box, hidden = None, True
    if box is not None:
        # A shape of no size still shows its text where it is anchored.
        outside = (
            box.x + max(box.width, 1.0) <= 0
            or box.y + max(box.height, 1.0) <= 0
            or box.x >= slide.width
            or box.y >= slide.height
        )
        hidden = hidden or outside
    if hidden:
        for block in blocks:
            block.flags = (*block.flags, BlockFlag.HIDDEN)
    if box is None or hidden:
        slide.unplaced.append(blocks)
        return

    def unit(value: float, total: float) -> float:
        return min(max(value / total, 0.0), 1.0)

    bbox = BBox(
        x0=unit(box.x, slide.width),
        y0=unit(box.y, slide.height),
        x1=unit(box.x + box.width, slide.width),
        y1=unit(box.y + box.height, slide.height),
    )
    for block in blocks:
        block.bbox = bbox
    slide.placed.append(_Item(blocks, bbox))


def _in_reading_order(slide: _Slide) -> list[_Pending]:
    """The slide's blocks: placed shapes by position, then the others in document order."""
    blocks: list[_Pending] = []
    for leaf in xy_cut(slide.placed, PPTX_LINE_HEIGHT):
        for row in text_rows(leaf):
            for item in row:
                blocks.extend(item.blocks)
    for unplaced in slide.unplaced:
        blocks.extend(unplaced)
    return blocks


def _bullet(properties: Element | None, level: int, styles: list[Element | None]) -> Element | None:
    """The bullet that applies: the paragraph's own, else the first list style setting one."""
    sources = [properties]
    sources += [_child(style, _A, f"lvl{level + 1}pPr") for style in styles]
    for source in sources:
        for child in _kids(source):
            if _ns(child.tag) in _A and local_name(child.tag) in _BULLETS:
                return child
    return None


def _label(scheme: str, number: int) -> str:
    """A numbered paragraph's label; schemes Sugo does not know are written "1."."""
    match = _SCHEME.fullmatch(scheme)
    if match is None:
        return f"{number}."
    kind, case, punctuation = match.groups()
    text = counter_text(number, _FORMATS.get((kind, case or ""), "decimal"))
    if punctuation == "ParenBoth":
        return f"({text})"
    if punctuation == "ParenR":
        return f"{text})"
    return text if punctuation == "Plain" else f"{text}."


def _table_cells(table: Element) -> tuple[int, list[list[tuple[Element, int]]]]:
    """A table's header rows and, row by row, its cells with the columns each spans.

    A cell covered by the span of one to its left is left out; rows without
    cells are dropped.
    """
    properties = _child(table, _A, "tblPr")
    first_row = properties is not None and properties.attrib.get("firstRow", "").casefold()
    rows: list[list[tuple[Element, int]]] = []
    for row in table:
        if not _is(row, _A, "tr"):
            continue
        cells = [
            (cell, max(1, _int(cell.attrib.get("gridSpan")) or 1))
            for cell in row
            if _is(cell, _A, "tc") and cell.attrib.get("hMerge", "").casefold() not in _TRUE
        ]
        if cells:
            rows.append(cells)
    header = 1 if first_row in _TRUE and rows else 0
    return header, rows


def _grid_size(header: int, rows: list[list[tuple[Element, int]]]) -> int:
    """Cells the serializer draws for a table: its rows, the header repeated, times its width."""
    if not rows:
        return 0
    width = max(sum(span for _, span in cells) for cells in rows)
    body = len(rows) - header
    parts = max(1, -(-body // max(1, OFFICE_TABLE_MAX_ROWS - header)))
    return (body + parts * header) * width


def _formula() -> _Pending:
    """An equation, marked not converted: never guessed from its picture."""
    return _Pending(BlockType.FORMULA, flags=(BlockFlag.ILLEGIBLE,))


def _paragraph_block(paragraph: _Paragraph) -> _Pending:
    if paragraph.label is None:
        return _Pending(BlockType.PARAGRAPH, paragraph.text)
    text = f"{paragraph.label} {paragraph.text}" if paragraph.label else paragraph.text
    return _Pending(BlockType.LIST_ITEM, text, list_level=paragraph.level)


def _run_text(paragraph: Element, rels: dict[str, Relationship]) -> str:
    """A paragraph's text: runs, fields and line breaks, links to outside addresses in Markdown."""
    pieces: list[tuple[str, str | None]] = []  # (text, link target)
    for item in paragraph:
        if _ns(item.tag) not in _A:
            continue
        name = local_name(item.tag)
        if name in ("r", "fld"):
            text = "".join(t.text or "" for t in item if _is(t, _A, "t"))
            link = _rid(_path(item, (_A, "rPr"), (_A, "hlinkClick")))
            relationship = None if link is None else rels.get(link)
            target = None
            if (
                relationship is not None
                and relationship.external
                and SAFE_LINK.fullmatch(relationship.target)
            ):
                target = relationship.target
            pieces.append((text, target))
        elif name == "br":
            pieces.append(("\n", None))
    # Runs of one link (split by a change of font, say) become one link.
    merged: list[tuple[str, str | None]] = []
    for text, target in pieces:
        if merged and target is not None and merged[-1][1] == target:
            merged[-1] = (merged[-1][0] + text, target)
        else:
            merged.append((text, target))
    return "".join(
        f"[{text}]({target})" if target is not None and text.strip() else text
        for text, target in merged
    )
