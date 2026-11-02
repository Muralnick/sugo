"""Minimal Word documents built in memory for the tests: only the parts a test needs."""

import io
import zipfile

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_MAIN = "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
_PARTS = {
    "styles": "word/styles.xml",
    "numbering": "word/numbering.xml",
    "footnotes": "word/footnotes.xml",
    "endnotes": "word/endnotes.xml",
    "comments": "word/comments.xml",
    "header": "word/header1.xml",
    "footer": "word/footer1.xml",
}


def docx(
    body: str,
    *,
    parts: dict[str, str] | None = None,
    links: dict[str, str] | None = None,
    main_type: str = _MAIN,
) -> bytes:
    """A DOCX whose body is ``body``; ``parts`` adds styles, notes, header (rId "h1")...

    Every part's text is wrapped in its root element with the ``w`` and ``r``
    namespaces declared. ``links`` maps relationship ids to external URLs.
    """
    parts = parts or {}
    roots = {
        "styles": "styles",
        "numbering": "numbering",
        "footnotes": "footnotes",
        "endnotes": "endnotes",
        "comments": "comments",
        "header": "hdr",
        "footer": "ftr",
    }
    declared = f'xmlns:w="{W}" xmlns:r="{R}"'
    rels = [
        f'<Relationship Id="p{name}" Type="{_REL}/{name}" Target="{_PARTS[name][5:]}"/>'
        for name in parts
    ]
    rels += [
        f'<Relationship Id="{rid}" Type="{_REL}/hyperlink" Target="{url}" TargetMode="External"/>'
        for rid, url in (links or {}).items()
    ]
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            f'<Override PartName="/word/document.xml" ContentType="{main_type}"/></Types>',
        )
        archive.writestr(
            "_rels/.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'<Relationship Id="rId1" Type="{_REL}/officeDocument" Target="word/document.xml"/>'
            "</Relationships>",
        )
        archive.writestr(
            "word/_rels/document.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            + "".join(rels)
            + "</Relationships>",
        )
        archive.writestr(
            "word/document.xml", f"<w:document {declared}><w:body>{body}</w:body></w:document>"
        )
        for name, text in parts.items():
            root = roots[name]
            archive.writestr(_PARTS[name], f"<w:{root} {declared}>{text}</w:{root}>")
    return output.getvalue()


def p(text: str, *, style: str | None = None, run: str = "", props: str = "") -> str:
    """A paragraph with one run; ``run`` adds run properties, ``props`` paragraph ones."""
    style_xml = f'<w:pStyle w:val="{style}"/>' if style else ""
    run_props = f"<w:rPr>{run}</w:rPr>" if run else ""
    return (
        f"<w:p><w:pPr>{style_xml}{props}</w:pPr>"
        f'<w:r>{run_props}<w:t xml:space="preserve">{text}</w:t></w:r></w:p>'
    )
