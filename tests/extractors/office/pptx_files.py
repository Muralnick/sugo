"""Minimal PowerPoint presentations built in memory for the tests: only the parts a test needs."""

import io
import zipfile
from collections.abc import Iterable

P = "http://schemas.openxmlformats.org/presentationml/2006/main"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
DGM = "http://schemas.openxmlformats.org/drawingml/2006/diagram"
MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"
_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_MODERN_COMMENTS = "http://schemas.microsoft.com/office/2018/10/relationships/comments"
_RELS = "http://schemas.openxmlformats.org/package/2006/relationships"
MAIN = "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"
# The 4:3 slide every test uses unless it says otherwise.
WIDTH, HEIGHT = 9_144_000, 6_858_000
_DECLARED = f'xmlns:p="{P}" xmlns:a="{A}" xmlns:r="{R}" xmlns:dgm="{DGM}" xmlns:mc="{MC}"'


def pptx(
    *slides: str,
    layout: str = "",
    master: str = "",
    master_styles: str = "",
    notes: dict[int, str] | None = None,
    comments: dict[int, str] | None = None,
    modern_comments: dict[int, str] | None = None,
    hidden: Iterable[int] = (),
    links: dict[str, str] | None = None,
    parts: dict[str, str | bytes] | None = None,
    images: dict[str, str] | None = None,
    size: tuple[int, int] | None = (WIDTH, HEIGHT),
    slide_targets: list[str] | None = None,
    main_type: str = MAIN,
) -> bytes:
    """A PPTX whose slides hold the given shapes (the inside of ``p:spTree``).

    ``layout`` and ``master`` are the shapes of the one layout and master,
    ``master_styles`` the inside of the master's ``p:txStyles``. ``notes``,
    ``comments`` and ``modern_comments`` map a slide's index to the inside of
    its notes page's ``p:spTree`` or comment list. ``links`` maps relationship
    ids to external URLs, on every slide; ``parts`` adds parts by name
    (diagram data, rId "dm" on every slide points to ``ppt/diagrams/data1.xml``).
    ``slide_targets`` replaces the slide parts the presentation lists.
    ``images`` maps relationship ids to picture parts (``../media/x.png``), on
    every slide; their bytes go in ``parts``.
    """
    hidden = set(hidden)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            f'<Override PartName="/ppt/presentation.xml" ContentType="{main_type}"/></Types>',
        )
        archive.writestr("_rels/.rels", _rels({"rId1": ("officeDocument", "ppt/presentation.xml")}))
        targets = slide_targets or [f"slides/slide{n + 1}.xml" for n in range(len(slides))]
        archive.writestr(
            "ppt/_rels/presentation.xml.rels",
            _rels({f"s{n}": ("slide", target) for n, target in enumerate(targets)}),
        )
        ids = "".join(f'<p:sldId id="{256 + n}" r:id="s{n}"/>' for n in range(len(targets)))
        size_xml = "" if size is None else f'<p:sldSz cx="{size[0]}" cy="{size[1]}"/>'
        archive.writestr(
            "ppt/presentation.xml",
            f"<p:presentation {_DECLARED}><p:sldIdLst>{ids}</p:sldIdLst>{size_xml}"
            "</p:presentation>",
        )
        for n, shapes in enumerate(slides):
            rels: dict[str, tuple[str, str]] = {
                "lay": ("slideLayout", "../slideLayouts/slideLayout1.xml"),
                "dm": ("diagramData", "../diagrams/data1.xml"),
            }
            rels.update({rid: ("image", target) for rid, target in (images or {}).items()})
            if notes and n in notes:
                rels["notes"] = ("notesSlide", f"../notesSlides/notesSlide{n + 1}.xml")
                archive.writestr(
                    f"ppt/notesSlides/notesSlide{n + 1}.xml",
                    f"<p:notes {_DECLARED}><p:cSld><p:spTree>{notes[n]}</p:spTree></p:cSld>"
                    "</p:notes>",
                )
            if comments and n in comments:
                rels["cm"] = ("comments", f"../comments/comment{n + 1}.xml")
                archive.writestr(
                    f"ppt/comments/comment{n + 1}.xml",
                    f"<p:cmLst {_DECLARED}>{comments[n]}</p:cmLst>",
                )
            if modern_comments and n in modern_comments:
                rels["mcm"] = (_MODERN_COMMENTS, f"../comments/modernComment{n + 1}.xml")
                archive.writestr(
                    f"ppt/comments/modernComment{n + 1}.xml",
                    '<p188:cmLst xmlns:p188="http://schemas.microsoft.com/office/powerpoint/2018/8/main"'
                    f" {_DECLARED}>{modern_comments[n]}</p188:cmLst>",
                )
            show = ' show="0"' if n in hidden else ""
            archive.writestr(
                f"ppt/slides/slide{n + 1}.xml",
                f"<p:sld {_DECLARED}{show}><p:cSld><p:spTree>{shapes}</p:spTree></p:cSld></p:sld>",
            )
            archive.writestr(f"ppt/slides/_rels/slide{n + 1}.xml.rels", _rels(rels, links=links))
        archive.writestr(
            "ppt/slideLayouts/slideLayout1.xml",
            f"<p:sldLayout {_DECLARED}><p:cSld><p:spTree>{layout}</p:spTree></p:cSld>"
            "</p:sldLayout>",
        )
        archive.writestr(
            "ppt/slideLayouts/_rels/slideLayout1.xml.rels",
            _rels({"m": ("slideMaster", "../slideMasters/slideMaster1.xml")}),
        )
        archive.writestr(
            "ppt/slideMasters/slideMaster1.xml",
            f"<p:sldMaster {_DECLARED}><p:cSld><p:spTree>{master}</p:spTree></p:cSld>"
            f"<p:txStyles>{master_styles}</p:txStyles></p:sldMaster>",
        )
        for name, text in (parts or {}).items():
            archive.writestr(name, text)
    return output.getvalue()


def _rels(rels: dict[str, tuple[str, str]], *, links: dict[str, str] | None = None) -> str:
    items = [
        f'<Relationship Id="{rid}" Type="{kind if "://" in kind else f"{_REL}/{kind}"}" '
        f'Target="{target}"/>'
        for rid, (kind, target) in rels.items()
    ]
    items += [
        f'<Relationship Id="{rid}" Type="{_REL}/hyperlink" Target="{url}" TargetMode="External"/>'
        for rid, url in (links or {}).items()
    ]
    return f'<Relationships xmlns="{_RELS}">{"".join(items)}</Relationships>'


def xfrm(at: tuple[float, float, float, float], tag: str = "a:xfrm", child: str = "") -> str:
    """A position given as fractions of the slide: x, y, width, height."""
    x, y, w, h = at
    return (
        f'<{tag}><a:off x="{round(x * WIDTH)}" y="{round(y * HEIGHT)}"/>'
        f'<a:ext cx="{round(w * WIDTH)}" cy="{round(h * HEIGHT)}"/>{child}</{tag}>'
    )


def para(text: str, *, lvl: int | None = None, bullet: str = "", run: str = "") -> str:
    """A paragraph with one run; ``bullet`` is a bullet element, ``run`` run properties."""
    level = "" if lvl is None else f' lvl="{lvl}"'
    properties = f"<a:pPr{level}>{bullet}</a:pPr>" if level or bullet else ""
    return f"<a:p>{properties}<a:r>{run}<a:t>{text}</a:t></a:r></a:p>"


def sp(
    *paragraphs: str,
    ph: str | None = None,
    idx: int | None = None,
    at: tuple[float, float, float, float] | None = (0.1, 0.1, 0.8, 0.1),
    hidden: bool = False,
    styles: str = "",
    text_box: bool = False,
) -> str:
    """A shape with a text body; ``ph`` makes it a placeholder of that type ("" for "obj")."""
    placeholder = ""
    if ph is not None:
        type_xml = f' type="{ph}"' if ph else ""
        idx_xml = "" if idx is None else f' idx="{idx}"'
        placeholder = f"<p:ph{type_xml}{idx_xml}/>"
    hide = ' hidden="1"' if hidden else ""
    box = ' txBox="1"' if text_box else ""
    return (
        f'<p:sp><p:nvSpPr><p:cNvPr id="2" name="s"{hide}/><p:cNvSpPr{box}/>'
        f"<p:nvPr>{placeholder}</p:nvPr></p:nvSpPr>"
        f"<p:spPr>{'' if at is None else xfrm(at)}</p:spPr>"
        f"<p:txBody><a:bodyPr/><a:lstStyle>{styles}</a:lstStyle>{''.join(paragraphs)}</p:txBody>"
        "</p:sp>"
    )


def group(
    *shapes: str,
    at: tuple[float, float, float, float],
    child: tuple[float, float, float, float],
    hidden: bool = False,
) -> str:
    """A group shape placed ``at`` on the slide whose children use the ``child`` frame."""
    x, y, w, h = child
    child_xml = (
        f'<a:chOff x="{round(x * WIDTH)}" y="{round(y * HEIGHT)}"/>'
        f'<a:chExt cx="{round(w * WIDTH)}" cy="{round(h * HEIGHT)}"/>'
    )
    hide = ' hidden="1"' if hidden else ""
    return (
        f'<p:grpSp><p:nvGrpSpPr><p:cNvPr id="3" name="g"{hide}/><p:cNvGrpSpPr/><p:nvPr/>'
        f"</p:nvGrpSpPr><p:grpSpPr>{xfrm(at, child=child_xml)}</p:grpSpPr>"
        f"{''.join(shapes)}</p:grpSp>"
    )


def table(
    rows: list[str],
    *,
    first_row: bool = True,
    at: tuple[float, float, float, float] = (0.1, 0.3, 0.8, 0.5),
) -> str:
    """A table frame whose rows are ``a:tr`` elements (see ``tr`` and ``tc``)."""
    header = ' firstRow="1"' if first_row else ""
    return (
        '<p:graphicFrame><p:nvGraphicFramePr><p:cNvPr id="4" name="t"/><p:cNvGraphicFramePr/>'
        f"<p:nvPr/></p:nvGraphicFramePr>{xfrm(at, tag='p:xfrm')}<a:graphic>"
        '<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/table">'
        f"<a:tbl><a:tblPr{header}/><a:tblGrid/>{''.join(rows)}</a:tbl>"
        "</a:graphicData></a:graphic></p:graphicFrame>"
    )


def tr(*cells: str) -> str:
    return f'<a:tr h="100">{"".join(cells)}</a:tr>'


def tc(text: str, attributes: str = "") -> str:
    return f"<a:tc{attributes}><a:txBody><a:bodyPr/>{para(text)}</a:txBody></a:tc>"


def frame(
    uri: str, inner: str, at: tuple[float, float, float, float] = (0.1, 0.5, 0.3, 0.3)
) -> str:
    """A graphic frame of another kind: a chart, SmartArt, an embedded object."""
    return (
        '<p:graphicFrame><p:nvGraphicFramePr><p:cNvPr id="5" name="f"/><p:cNvGraphicFramePr/>'
        f"<p:nvPr/></p:nvGraphicFramePr>{xfrm(at, tag='p:xfrm')}<a:graphic>"
        f'<a:graphicData uri="{uri}">{inner}</a:graphicData></a:graphic></p:graphicFrame>'
    )


def pic(
    at: tuple[float, float, float, float] = (0.6, 0.6, 0.2, 0.2), *, hidden: bool = False
) -> str:
    hide = ' hidden="1"' if hidden else ""
    return (
        f'<p:pic><p:nvPicPr><p:cNvPr id="6" name="p"{hide}/><p:cNvPicPr/><p:nvPr/></p:nvPicPr>'
        f'<p:blipFill><a:blip r:embed="img"/></p:blipFill><p:spPr>{xfrm(at)}</p:spPr></p:pic>'
    )
