"""EUR-Lex benchmark documents: real legal text, typeset into native PDFs.

The text itself is not generated: it is Regulation (EC) No 261/2004's
official text in each language, fetched once from EUR-Lex and kept outside
the repository (ARCHITECTURE.md: "corpus downloaded separately"), at
``../sugo-corpus/eur-lex`` next to the checkout, with a manifest recording
its source, licence and checksums. Reuse is permitted under Commission
Decision 2011/833/EU (see the manifest).

EUR-Lex's own PDF could not be fetched directly in this run (its download
link only resolves inside a full browser session), so this module typesets
the authentic text itself into a plain multi-page PDF with a running header
and page numbers, giving the same native-PDF extraction path as
``corpus.report_pdf`` with an exact, controllable ground truth.
"""

import json
from pathlib import Path

import pymupdf
from corpus import CorpusDocument

# Sibling to the repository checkout, never inside it.
CORPUS_DIR = Path(__file__).resolve().parent.parent.parent / "sugo-corpus" / "eur-lex"

_TITLES = {
    "en": "Regulation (EC) No 261/2004 - EUR-Lex",
    "it": "Regolamento (CE) n. 261/2004 - EUR-Lex",
    "es": "Reglamento (CE) no 261/2004 - EUR-Lex",
    "fr": "Règlement (CE) no 261/2004 - EUR-Lex",
    "de": "Verordnung (EG) Nr. 261/2004 - EUR-Lex",
}
_MARGIN = 72
_PAGE_WIDTH = 595  # PyMuPDF's default new_page() size (A4, points).
_PAGE_HEIGHT = 842
_FONT = pymupdf.Font("helv")
_FONT_SIZE = 10
_LEADING = 14


def eur_lex_documents() -> list[CorpusDocument]:
    """One typeset PDF per language the manifest lists, or an empty list if not fetched."""
    manifest_path = CORPUS_DIR / "manifest.json"
    if not manifest_path.exists():
        return []
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    documents = []
    for entry in manifest["files"]:
        text_path = CORPUS_DIR / entry["text_file"]
        text = text_path.read_text(encoding="utf-8")
        documents.append(_eur_lex_pdf(entry["language"], text))
    return documents


def _eur_lex_pdf(language: str, text: str) -> CorpusDocument:
    header = _TITLES[language]
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    document = pymupdf.open()
    page, y = _new_page(document, header, 1)
    for paragraph in paragraphs:
        for line in _wrap(paragraph):
            if y + _LEADING > _PAGE_HEIGHT - _MARGIN:
                page, y = _new_page(document, header, document.page_count + 1)
            page.insert_text((_MARGIN, y), line, fontsize=_FONT_SIZE, fontname="helv")
            y += _LEADING
        y += _LEADING  # a blank line between paragraphs
    return CorpusDocument(
        f"eur_lex_261_2004_{language}.pdf", document.tobytes(), tuple(paragraphs), needs_ocr=False
    )


def _new_page(
    document: "pymupdf.Document", header: str, number: int
) -> tuple["pymupdf.Page", float]:
    page = document.new_page()
    page.insert_text((_MARGIN, 40), header, fontsize=9)
    page.insert_text((_PAGE_WIDTH / 2 - 10, _PAGE_HEIGHT - 30), str(number), fontsize=9)
    return page, float(_MARGIN + 30)


def _wrap(paragraph: str) -> list[str]:
    width = _PAGE_WIDTH - 2 * _MARGIN
    words = paragraph.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if _FONT.text_length(candidate, fontsize=_FONT_SIZE) <= width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines
