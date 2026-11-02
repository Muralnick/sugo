"""Tests for PowerPoint presentations: reading order, lists, tables, hidden content, limits."""

import pytest
from tests.extractors.office.docx_files import docx, p
from tests.extractors.office.pptx_files import (
    DGM,
    MC,
    frame,
    group,
    para,
    pic,
    pptx,
    sp,
    table,
    tc,
    tr,
)

from sugo.core.constants import OFFICE_TABLE_MAX_ROWS
from sugo.core.models import BlockFlag, BlockType, Page
from sugo.extractors.office.package import powerpoint_presentation, word_document
from sugo.extractors.office.pptx_reader import read_pptx
from sugo.extractors.office.xml_reader import Refusal
from sugo.serializers.markdown import render

P14 = "http://schemas.microsoft.com/office/powerpoint/2010/main"
BULLET = '<a:buChar char="•"/>'
# A master whose body text has bullets on its first two levels, as PowerPoint's own.
BODY_STYLES = (
    f"<p:titleStyle><a:lvl1pPr><a:buNone/></a:lvl1pPr></p:titleStyle>"
    f"<p:bodyStyle><a:lvl1pPr>{BULLET}</a:lvl1pPr><a:lvl2pPr>{BULLET}</a:lvl2pPr></p:bodyStyle>"
    "<p:otherStyle><a:lvl1pPr/></p:otherStyle>"
)


def pages(*slides: str, **kwargs: object) -> list[Page]:
    count, page = read_pptx(pptx(*slides, **kwargs))  # type: ignore[arg-type]
    return [page(index) for index in range(count)]


def text(*slides: str, **kwargs: object) -> str:
    return "\n\n".join(render(page.blocks) for page in pages(*slides, **kwargs))


def visible(page: Page) -> str:
    return render(block for block in page.blocks if BlockFlag.HIDDEN not in block.flags)


def test_presentations_are_recognised_by_content() -> None:
    data = pptx(sp(para("Hello")))
    assert powerpoint_presentation(data)
    assert not word_document(data)
    assert not powerpoint_presentation(docx(p("Hello")))
    show = pptx(
        sp(para("Hi")),
        main_type="application/vnd.openxmlformats-officedocument.presentationml.slideshow.main+xml",
    )
    assert powerpoint_presentation(show)


def test_one_page_per_slide_with_title_bullets_and_levels() -> None:
    slide = sp(para("Agenda"), ph="title", at=(0.1, 0.05, 0.8, 0.1)) + sp(
        para("Goals"),
        para("Revenue", lvl=1),
        para("Costs", lvl=1),
        para("Risks"),
        ph="body",
        idx=1,
        at=(0.1, 0.2, 0.8, 0.6),
    )
    second = sp(para("Thanks"), ph="title")
    result = pages(slide, second, master_styles=BODY_STYLES)
    assert [render(page.blocks) for page in result] == [
        "# Agenda\n\n- Goals\n  - Revenue\n  - Costs\n- Risks",
        "# Thanks",
    ]
    items = [block for block in result[0].blocks if block.type is BlockType.LIST_ITEM]
    assert [block.list_level for block in items] == [0, 1, 1, 0]
    # Slides are measured in points, as PDF pages.
    assert (result[0].width, result[0].height) == (720.0, 540.0)


def test_numbered_paragraphs_keep_their_labels() -> None:
    number = '<a:buAutoNum type="{}"/>'
    body = sp(
        para("First", bullet=number.format("arabicPeriod")),
        para("Detail", lvl=1, bullet=number.format("alphaLcParenR")),
        para("More", lvl=1, bullet=number.format("alphaLcParenR")),
        para("Second", bullet=number.format("arabicPeriod")),
        para("Chapter", bullet='<a:buAutoNum type="romanUcPeriod" startAt="4"/>'),
        para("Plain", bullet="<a:buNone/>"),
        para("Again", bullet=number.format("arabicPeriod")),
        ph="body",
    )
    assert text(body, master_styles=BODY_STYLES) == (
        "- 1\\. First\n  - a) Detail\n  - b) More\n- 2\\. Second\n- IV. Chapter\n\n"
        "Plain\n\n- 1\\. Again"
    )


def test_bullets_come_from_the_shape_layout_and_master_in_that_order() -> None:
    layout = sp(ph="subTitle", idx=2, styles="<a:lvl1pPr><a:buNone/></a:lvl1pPr>", at=None)
    slide = (
        sp(para("Body"), ph="body", idx=1, at=(0.1, 0.1, 0.8, 0.1))
        + sp(para("Subtitle"), ph="subTitle", idx=2, at=(0.1, 0.3, 0.8, 0.1))
        + sp(para("Text box"), at=(0.1, 0.5, 0.8, 0.1), text_box=True)
        + sp(
            para("Own bullet"),
            at=(0.1, 0.7, 0.8, 0.1),
            styles=f"<a:lvl1pPr>{BULLET}</a:lvl1pPr>",
            text_box=True,
        )
    )
    assert text(slide, layout=layout, master_styles=BODY_STYLES) == (
        "- Body\n\nSubtitle\n\nText box\n\n- Own bullet"
    )


def test_shapes_are_read_by_position_not_by_document_order() -> None:
    slide = (
        sp(para("Right column"), at=(0.55, 0.3, 0.4, 0.4))
        + sp(para("Left column"), at=(0.05, 0.3, 0.4, 0.4))
        + sp(para("Title"), ph="title", at=(0.05, 0.05, 0.9, 0.1))
    )
    assert text(slide) == "# Title\n\nLeft column\n\nRight column"


def test_placeholders_without_a_position_take_their_layouts() -> None:
    # The layout puts the title at the bottom and the body at the top.
    layout = sp(ph="title", at=(0.1, 0.8, 0.8, 0.1)) + sp(
        para("Click to add text"), ph="body", idx=1, at=(0.1, 0.1, 0.8, 0.5)
    )
    slide = sp(para("Low title"), ph="title", at=None) + sp(
        para("High body"), ph="body", idx=1, at=None
    )
    assert text(slide, layout=layout) == "High body\n\n# Low title"


def test_text_shown_only_by_layouts_and_masters_is_not_read() -> None:
    layout = sp(para("Click to add title"), ph="title")
    master = sp(para("Master prompt"), ph="body") + sp(para("Master logo text"))
    assert text(sp(para("Real"), ph="title"), layout=layout, master=master) == "# Real"


def test_groups_are_entered_and_their_children_placed_on_the_slide() -> None:
    # The group shrinks its children's frame into the right half of the slide.
    inner = sp(para("Inside the group"), at=(0.0, 0.0, 1.0, 0.5))
    slide = group(inner, at=(0.5, 0.0, 0.5, 0.5), child=(0.0, 0.0, 1.0, 1.0)) + sp(
        para("Left"), at=(0.0, 0.0, 0.4, 0.25)
    )
    [page] = pages(slide)
    assert render(page.blocks) == "Left\n\nInside the group"
    inside = page.blocks[1]
    assert inside.bbox is not None
    assert (inside.bbox.x0, inside.bbox.x1) == (0.5, 1.0)
    assert inside.bbox.y1 == pytest.approx(0.25)


def test_tables_keep_spans_merges_and_the_header_row() -> None:
    rows = [
        tr(tc("Name"), tc("Total")),
        tr(tc("All", ' gridSpan="2"'), tc("", ' hMerge="1"')),
        tr(tc("Rossi", ' rowSpan="2"'), tc("3")),
        tr(tc("Rossi", ' vMerge="1"'), tc("4")),
    ]
    [page] = pages(table(rows))
    [block] = page.blocks
    assert block.table is not None
    assert block.table.header_rows == 1
    assert [(cell.row, cell.col, cell.text, cell.col_span) for cell in block.table.cells] == [
        (0, 0, "Name", 1),
        (0, 1, "Total", 1),
        (1, 0, "All", 2),
        (2, 0, "Rossi", 1),
        (2, 1, "3", 1),
        (3, 0, "", 1),
        (3, 1, "4", 1),
    ]


def test_long_tables_are_split_with_the_header_repeated() -> None:
    rows = [tr(tc("Name"))] + [tr(tc(f"r{n}")) for n in range(OFFICE_TABLE_MAX_ROWS + 10)]
    [page] = pages(table(rows))
    tables = [block.table for block in page.blocks if block.table is not None]
    assert [t.n_rows for t in tables] == [OFFICE_TABLE_MAX_ROWS, 12]
    assert all(t.cells[0].text == "Name" and t.header_rows == 1 for t in tables)


def test_links_pictures_charts_and_alternate_content() -> None:
    link = '<a:rPr><a:hlinkClick r:id="{}"/></a:rPr>'
    body = sp(
        para("Site", run=link.format("web")),
        para("Script", run=link.format("js")),
        "<a:p><a:r>"
        + link.format("web")
        + "<a:t>Two </a:t></a:r><a:r>"
        + link.format("web")
        + "<a:t>runs</a:t></a:r></a:p>",
        at=(0.1, 0.1, 0.8, 0.3),
    )
    chart = frame("http://schemas.openxmlformats.org/drawingml/2006/chart", "<c:chart/>")
    chart = chart.replace("<c:chart/>", '<c:chart xmlns:c="urn:chart"/>')
    alternate = (
        f'<mc:AlternateContent xmlns:mc="{MC}" xmlns:p14="{P14}"><mc:Choice Requires="p14">'
        + sp(para("Chosen"), at=(0.1, 0.9, 0.3, 0.05))
        + "</mc:Choice><mc:Fallback>"
        + sp(para("Fallback"), at=(0.1, 0.9, 0.3, 0.05))
        + "</mc:Fallback></mc:AlternateContent>"
    )
    links = {"web": "https://example.com/a", "js": "javascript:alert(1)"}
    assert text(body + chart + pic() + alternate, links=links) == (
        "[Site](https://example.com/a)\n\nScript\n\n[Two runs](https://example.com/a)"
        "\n\n[illegible]\n\n[illegible]\n\nChosen"
    )


def test_smartart_becomes_nested_list_items() -> None:
    def point(model_id: str, text: str = "", kind: str = "") -> str:
        type_xml = f' type="{kind}"' if kind else ""
        body = f"<dgm:t><a:bodyPr/>{para(text)}</dgm:t>" if text else ""
        return f'<dgm:pt modelId="{model_id}"{type_xml}>{body}</dgm:pt>'

    def link(source: str, target: str, order: int) -> str:
        return f'<dgm:cxn modelId="c{target}" srcId="{source}" destId="{target}" srcOrd="{order}"/>'

    data = (
        '<dgm:dataModel xmlns:dgm="http://schemas.openxmlformats.org/drawingml/2006/diagram" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><dgm:ptLst>'
        + point("0", kind="doc")
        + point("2", "Second")
        + point("1", "First")
        + point("3", "Child")
        + point("9", "Transition", kind="parTrans")
        + "</dgm:ptLst><dgm:cxnLst>"
        + link("0", "2", 1)
        + link("0", "1", 0)
        + link("1", "3", 0)
        + link("3", "1", 0)  # A loop, as in a damaged file: read once.
        + "</dgm:cxnLst></dgm:dataModel>"
    )
    smartart = frame(
        "http://schemas.openxmlformats.org/drawingml/2006/diagram",
        '<dgm:relIds r:dm="dm" r:lo="lo" r:qs="qs" r:cs="cs"/>',
    )
    assert text(smartart, parts={"ppt/diagrams/data1.xml": data}) == (
        "- First\n  - Child\n- Second"
    )


def test_hidden_slides_shapes_notes_and_comments_are_flagged() -> None:
    slide = (
        sp(para("Seen"), at=(0.1, 0.1, 0.5, 0.1))
        + sp(para("Marked hidden"), hidden=True)
        + sp(para("Off the slide"), at=(1.2, 0.1, 0.3, 0.1))
        + group(sp(para("In a hidden group")), at=(0, 0, 1, 1), child=(0, 0, 1, 1), hidden=True)
        + pic(hidden=True)
    )
    notes = sp(para("1"), ph="sldNum") + sp(para("Say this aloud"), ph="body", idx=1)
    comments = '<p:cm authorId="0"><p:text>Old comment</p:text></p:cm>'
    modern = (
        '<p188:cm id="1"><p188:txBody><a:bodyPr/>'
        + para("New comment")
        + "</p188:txBody><p188:replyLst><p188:reply><p188:txBody><a:bodyPr/>"
        + para("Reply")
        + "</p188:txBody></p188:reply></p188:replyLst></p188:cm>"
    )
    first, second = pages(
        slide,
        sp(para("Secret slide")),
        notes={0: notes},
        comments={0: comments},
        modern_comments={0: modern},
        hidden=[1],
    )
    assert visible(first) == "Seen"
    concealed = [b.text for b in first.blocks if BlockFlag.HIDDEN in b.flags]
    assert concealed == [
        "Marked hidden",
        "Off the slide",
        "In a hidden group",
        "",
        "Say this aloud",
        "Old comment",
        "New comment Reply",
    ]
    assert all(BlockFlag.HIDDEN in block.flags for block in second.blocks)
    assert visible(second) == ""


def test_footers_and_slide_numbers_are_typed_for_the_edge_cleaners() -> None:
    slide = (
        sp(para("Body"), at=(0.1, 0.2, 0.8, 0.5))
        + sp(para("ACME confidential"), ph="ftr", at=(0.3, 0.93, 0.4, 0.05))
        + sp(para("7"), ph="sldNum", at=(0.9, 0.93, 0.05, 0.05))
    )
    [page] = pages(slide)
    kinds = [(block.type, block.text) for block in page.blocks]
    assert kinds == [
        (BlockType.PARAGRAPH, "Body"),
        (BlockType.FOOTER, "ACME confidential"),
        (BlockType.PAGE_NUMBER, "7"),
    ]
    assert all(block.bbox is not None and block.bbox.y0 > 0.9 for block in page.blocks[1:])


def test_a_presentation_without_slides_is_one_empty_page() -> None:
    assert [page.blocks for page in pages()] == [()]


def test_a_missing_size_falls_back_to_widescreen() -> None:
    [page] = pages(sp(para("x")), size=None)
    assert (page.width, page.height) == (960.0, 540.0)


@pytest.mark.parametrize(
    "targets",
    [
        ["slides/slide1.xml", "slides/slide1.xml"],  # One part listed twice.
        ["slides/missing.xml"],
    ],
)
def test_slide_lists_that_powerpoint_never_writes_are_refused(targets: list[str]) -> None:
    data = pptx(sp(para("x")), slide_targets=targets)
    with pytest.raises(Refusal) as caught:
        read_pptx(data)
    assert caught.value.code == "OFFICE_INVALID"


def test_a_broken_slide_is_refused_only_when_its_page_is_read() -> None:
    data = pptx(sp(para("fine")), "<p:sp><broken></p:sp>")
    count, page = read_pptx(data)
    assert count == 2
    assert render(page(0).blocks) == "fine"
    with pytest.raises(Refusal):
        page(1)


def test_a_cell_spanning_a_huge_grid_refuses_the_file_before_any_page() -> None:
    huge = tr(tc("Wide", ' gridSpan="1000000000"'))
    data = pptx(sp(para("fine")), table([huge]))
    with pytest.raises(Refusal) as caught:
        read_pptx(data)
    assert caught.value.code == "OFFICE_TOO_LARGE"


def test_tables_count_towards_one_limit_for_the_whole_presentation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sugo.extractors.office import pptx_reader

    two_by_two = table([tr(tc("a"), tc("b")), tr(tc("c"), tc("d"))])
    monkeypatch.setattr(pptx_reader, "PPTX_MAX_GRID_CELLS", 8)
    assert len(pages(two_by_two, two_by_two)) == 2
    monkeypatch.setattr(pptx_reader, "PPTX_MAX_GRID_CELLS", 7)
    with pytest.raises(Refusal):
        read_pptx(pptx(two_by_two, two_by_two))


def test_a_broken_slide_does_not_stop_the_table_check() -> None:
    count, page = read_pptx(pptx("<p:sp><broken></p:sp>", table([tr(tc("ok"))])))
    assert count == 2
    assert page(1).blocks[0].table is not None


def test_shapes_placed_out_of_range_are_hidden() -> None:
    far = sp(para("Far"), at=None).replace(
        "<p:spPr></p:spPr>",
        '<p:spPr><a:xfrm><a:off x="1' + "0" * 400 + '" y="0"/><a:ext cx="1" cy="1"/>'
        "</a:xfrm></p:spPr>",
    )
    # Nested groups that each scale by a large factor overflow to infinity.
    shape = sp(para("Scaled"), at=(0.5, 0.5, 0.1, 0.1))
    for _ in range(60):
        shape = group(shape, at=(0, 0, 1, 1), child=(0, 0, 1e-6, 1e-6))
    [page] = pages(sp(para("Top"), at=(0.1, 0.1, 0.5, 0.1)) + far + shape)
    assert visible(page) == "Top"
    assert [b.text for b in page.blocks if BlockFlag.HIDDEN in b.flags] == ["Far", "Scaled"]


def test_equations_are_marked_not_converted_after_their_paragraph() -> None:
    equation = (
        f'<mc:AlternateContent xmlns:mc="{MC}"><mc:Choice Requires="a14">'
        '<a14:m xmlns:a14="http://schemas.microsoft.com/office/drawing/2010/main"/>'
        "</mc:Choice><mc:Fallback><a:r><a:t>E = mc2 picture</a:t></a:r></mc:Fallback>"
        "</mc:AlternateContent>"
    )
    body = sp(
        "<a:p><a:r><a:t>Energy:</a:t></a:r>" + equation + "</a:p>",
        "<a:p>" + equation + "</a:p>",
        para("After"),
    )
    [page] = pages(body)
    assert [(b.type, b.text) for b in page.blocks] == [
        (BlockType.PARAGRAPH, "Energy:"),
        (BlockType.FORMULA, ""),
        (BlockType.FORMULA, ""),
        (BlockType.PARAGRAPH, "After"),
    ]
    assert render(page.blocks) == "Energy:\n\n[illegible]\n\n[illegible]\n\nAfter"


def test_ink_is_marked_not_converted_where_it_is_drawn() -> None:
    p14 = "http://schemas.microsoft.com/office/powerpoint/2010/main"
    ink = (
        f'<p14:contentPart xmlns:p14="{p14}" r:id="ink">'
        '<p14:nvContentPartPr><p14:cNvPr id="7" name="ink"{}/><p14:cNvContentPartPr/>'
        "<p14:nvPr/></p14:nvContentPartPr>"
        '<p14:xfrm><a:off x="0" y="0"/><a:ext cx="100" cy="100"/></p14:xfrm></p14:contentPart>'
    )
    slide = sp(para("Below"), at=(0.1, 0.5, 0.5, 0.1)) + ink.format("")
    [page] = pages(slide)
    assert [(b.type, b.bbox is not None) for b in page.blocks] == [
        (BlockType.IMAGE, True),
        (BlockType.PARAGRAPH, True),
    ]
    [hidden] = pages(ink.format(' hidden="1"'))
    assert BlockFlag.HIDDEN in hidden.blocks[0].flags


def test_a_shape_of_no_size_at_the_slide_edge_is_visible() -> None:
    [page] = pages(sp(para("Anchored"), at=(0.0, 0.0, 0.0, 0.0)))
    assert visible(page) == "Anchored"


def test_a_slide_size_out_of_range_falls_back_to_the_default() -> None:
    [page] = pages(sp(para("x")), size=(10**400, 6_858_000))
    assert (page.width, page.height) == (960.0, 540.0)


def alternate(choice: str, fallback: str, requires: str, declared: str = "") -> str:
    return (
        f'<mc:AlternateContent xmlns:mc="{MC}" {declared}><mc:Choice Requires="{requires}">'
        f"{choice}</mc:Choice><mc:Fallback>{fallback}</mc:Fallback></mc:AlternateContent>"
    )


@pytest.mark.parametrize(
    ("requires", "declared", "shown"),
    [
        ("p14", f'xmlns:p14="{P14}"', "Choice text"),
        # A namespace Office does not know: Office shows the fallback.
        ("x", 'xmlns:x="urn:attacker"', "Fallback text"),
        # A prefix bound to nothing cannot be understood either.
        ("p14", "", "Fallback text"),
        # A known prefix name bound to a made-up namespace.
        ("p14", 'xmlns:p14="urn:attacker"', "Fallback text"),
        ("p14 x", f'xmlns:p14="{P14}" xmlns:x="urn:attacker"', "Fallback text"),
    ],
)
def test_alternate_content_is_chosen_as_office_chooses_it(
    requires: str, declared: str, shown: str
) -> None:
    content = alternate(sp(para("Choice text")), sp(para("Fallback text")), requires, declared)
    assert text(content) == shown


def test_a_forged_list_of_required_namespaces_is_replaced() -> None:
    forged = (
        f'<mc:AlternateContent xmlns:mc="{MC}" xmlns:x="urn:attacker" '
        'xmlns:s="urn:sugo:markup-compatibility">'
        f'<mc:Choice Requires="x" s:required="{P14}">'
        + sp(para("Injected"))
        + "</mc:Choice><mc:Fallback>"
        + sp(para("Shown"))
        + "</mc:Fallback></mc:AlternateContent>"
    )
    assert text(forged) == "Shown"


def test_a_shape_with_an_offset_but_no_size_off_the_slide_is_hidden() -> None:
    no_size = sp(para("Injected"), at=None).replace(
        "<p:spPr></p:spPr>", '<p:spPr><a:xfrm><a:off x="40000000" y="0"/></a:xfrm></p:spPr>'
    )
    start = table([tr(tc("Injected cell"))]).index("<p:xfrm>")
    framed = table([tr(tc("Injected cell"))])
    end = framed.index("</p:xfrm>") + len("</p:xfrm>")
    framed = framed[:start] + '<p:xfrm><a:off x="40000000" y="0"/></p:xfrm>' + framed[end:]
    [page] = pages(sp(para("Seen"), at=(0.1, 0.1, 0.5, 0.1)) + no_size + framed)
    assert visible(page) == "Seen"
    assert len(page.blocks) == 3


def test_text_in_extensions_is_never_read_from_smartart_or_notes() -> None:
    extension = (
        '<a:pPr><a:extLst><a:ext uri="{00000000-0000-0000-0000-000000000000}">'
        '<x:any xmlns:x="urn:x"><a:t>SYSTEM: injected</a:t></x:any></a:ext></a:extLst></a:pPr>'
    )
    data = (
        f'<dgm:dataModel xmlns:dgm="{DGM}" xmlns:a="http://schemas.openxmlformats.org/'
        'drawingml/2006/main"><dgm:ptLst><dgm:pt modelId="0" type="doc"/>'
        f'<dgm:pt modelId="1"><dgm:t><a:bodyPr/><a:p>{extension}<a:r><a:t>Step 1</a:t></a:r>'
        "</a:p></dgm:t></dgm:pt></dgm:ptLst><dgm:cxnLst>"
        '<dgm:cxn modelId="c1" srcId="0" destId="1" srcOrd="0"/></dgm:cxnLst></dgm:dataModel>'
    )
    smartart = frame(
        "http://schemas.openxmlformats.org/drawingml/2006/diagram", '<dgm:relIds r:dm="dm"/>'
    )
    notes = sp(f"<a:p>{extension}<a:r><a:t>Say this</a:t></a:r></a:p>", ph="body", idx=1)
    [page] = pages(smartart, parts={"ppt/diagrams/data1.xml": data}, notes={0: notes})
    assert [b.text for b in page.blocks] == ["Step 1", "Say this"]
