"""Synthetic benchmark corpus: documents with exact ground truth, generated on demand.

Every document is built in memory from the text below, so nothing is stored
or downloaded (ARCHITECTURE.md: "corpus downloaded separately" is for the
EUR-Lex samples in ``corpus_eur_lex.py``, not these). Covers v0.1's in-scope
languages only (ROADMAP.md: Italian, Spanish, French, German, English;
Japanese and Chinese ship later) and its in-scope document kinds: a native
PDF with a running header, footer and page numbers; a two-column PDF page;
an XLSX table; and chat and code screenshots, one of them in dark mode.

The XLSX builder (``row``, ``xlsx``) is reused from the DOCX/XLSX reader's
own test fixtures (tests/extractors/office/xlsx_files.py) rather than
duplicated here.
"""

import io
import sys
from dataclasses import dataclass
from pathlib import Path

import pymupdf
from PIL import Image, ImageDraw, ImageFont

# The repository root, for the test fixture import below: this script runs
# as `benchmarks/corpus.py`, so only the `benchmarks/` folder is on sys.path.
_REPO_ROOT = str(Path(__file__).resolve().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from tests.extractors.office.xlsx_files import row, xlsx  # noqa: E402

LANGUAGES = ("it", "es", "fr", "de", "en")

# One sentence per language, reused as running body text (two-column page,
# report body) wherever the exact words only need to be plausible prose.
_SENTENCE = {
    "it": "Il contratto è già firmato, come concordato nella riunione di ieri.",
    "es": "El contrato ya está firmado, según lo acordado en la reunión de ayer.",
    "fr": "Le contrat est déjà signé, comme convenu lors de la réunion d'hier.",
    "de": "Der Vertrag ist bereits unterschrieben, wie gestern besprochen wurde.",
    "en": "The contract is already signed, as agreed in yesterday's meeting.",
}
_HEADER_TITLE = {
    "it": "ACME S.p.A. - Relazione annuale 2026",
    "es": "ACME S.A. - Informe anual 2026",
    "fr": "ACME S.A. - Rapport annuel 2026",
    "de": "ACME GmbH - Jahresbericht 2026",
    "en": "ACME Corporation - Annual Report 2026",
}
# Repeated verbatim on every page: the signal a header/footer cleaner looks for.
_FOOTER_CLAUSE = {
    "it": "Il fornitore è responsabile di tutti i danni causati da ritardi.",
    "es": "El proveedor es responsable de todos los daños causados por retrasos.",
    "fr": "Le fournisseur est responsable de tous les dommages causés par des retards.",
    "de": "Der Lieferant haftet für alle durch Verzögerungen verursachten Schäden.",
    "en": "The supplier is liable for all damages caused by delays.",
}
_TABLE_HEADER = {
    "it": ("Prodotto", "Prezzo"),
    "es": ("Producto", "Precio"),
    "fr": ("Produit", "Prix"),
    "de": ("Produkt", "Preis"),
    "en": ("Product", "Price"),
}
_TABLE_ROWS = {
    "it": (("Pane", "2,50"), ("Latte", "1,20"), ("Caffè", "4,80")),
    "es": (("Pan", "2,50"), ("Leche", "1,20"), ("Café", "4,80")),
    "fr": (("Pain", "2,50"), ("Lait", "1,20"), ("Café", "4,80")),
    "de": (("Brot", "2,50"), ("Milch", "1,20"), ("Kaffee", "4,80")),
    "en": (("Bread", "2.50"), ("Milk", "1.20"), ("Coffee", "4.80")),
}
# Three left messages, three right messages: above CHAT_MIN_MESSAGES (3) and
# CHAT_MIN_ALIGNED_SHARE (0.6), well inside CHAT_SIDE_MARGIN (0.15) of each edge.
_CHAT_MESSAGES = {
    "it": (
        ("left", "Ciao, ci vediamo domani?"),
        ("right", "Sì, alle 18"),
        ("left", "Perfetto, porto i documenti"),
        ("right", "Grazie!"),
        ("left", "A domani allora"),
        ("right", "A domani!"),
    ),
    "es": (
        ("left", "Hola, ¿nos vemos mañana?"),
        ("right", "Sí, a las 18"),
        ("left", "Perfecto, llevo los documentos"),
        ("right", "¡Gracias!"),
        ("left", "Hasta mañana entonces"),
        ("right", "¡Hasta mañana!"),
    ),
    "fr": (
        ("left", "Salut, on se voit demain ?"),
        ("right", "Oui, à 18h"),
        ("left", "Parfait, j'apporte les documents"),
        ("right", "Merci !"),
        ("left", "À demain alors"),
        ("right", "À demain !"),
    ),
    "de": (
        ("left", "Hallo, sehen wir uns morgen?"),
        ("right", "Ja, um 18 Uhr"),
        ("left", "Perfekt, ich bringe die Unterlagen mit"),
        ("right", "Danke!"),
        ("left", "Bis morgen dann"),
        ("right", "Bis morgen!"),
    ),
    "en": (
        ("left", "Hi, see you tomorrow?"),
        ("right", "Yes, at 6pm"),
        ("left", "Perfect, I'll bring the documents"),
        ("right", "Thanks!"),
        ("left", "See you tomorrow then"),
        ("right", "See you tomorrow!"),
    ),
}
# Real code: matches the detectors' signal regexes (def, return, brackets),
# which look at OCR'd text content, not the rendering font (detectors.py).
_CODE_LINES = (
    "def total(items):",
    "    result = 0",
    "    for item in items:",
    "        result += item.price",
    "    return result",
)


@dataclass(frozen=True)
class CorpusDocument:
    """One synthetic document: its bytes, and the ground truth to check output against.

    ``ground_truth`` is the substantive text only: for a native document
    (``needs_ocr`` False), the body, never the running header, footer or page
    numbers a cleaner is meant to remove (TESTING.md: noise removed is not
    content lost). For a screenshot (``needs_ocr`` True), it is every word
    drawn, in reading order, for a character-error-rate check.
    """

    name: str
    data: bytes
    ground_truth: tuple[str, ...]
    needs_ocr: bool


def report_pdf(language: str, pages: int = 5) -> CorpusDocument:
    """A native PDF with a running header, a repeated footer clause and page numbers."""
    header = _HEADER_TITLE[language]
    footer = _FOOTER_CLAUSE[language]
    document = pymupdf.open()
    body_lines: list[str] = []
    for n in range(pages):
        page = document.new_page()
        page.insert_text((72, 40), header, fontsize=9)
        lines = [
            f"Section {n + 1}: {_SENTENCE[language]}",
            # Distinct per page, not a repeat, and not a leading digit+dot
            # (escaped as an ordered-list marker, which would break a plain
            # substring check against this ground truth).
            f"Note {n + 1}: {_SENTENCE[language][::-1][:40]}",
        ]
        for row_index, line in enumerate(lines):
            page.insert_text((72, 120 + row_index * 18), line, fontsize=11)
        body_lines += lines
        page.insert_text((72, 780), footer, fontsize=8)
        page.insert_text((290, 815), str(n + 1), fontsize=9)
    return CorpusDocument(
        f"report_{language}.pdf", document.tobytes(), tuple(body_lines), needs_ocr=False
    )


def two_column_pdf(language: str) -> CorpusDocument:
    """A single native PDF page with two side-by-side text columns."""
    document = pymupdf.open()
    page = document.new_page()
    left = [f"L{i}: {_SENTENCE[language]}" for i in range(6)]
    right = [f"R{i}: {_SENTENCE[language][::-1][:30]}" for i in range(6)]
    for row_index, line in enumerate(left):
        page.insert_text((72, 100 + row_index * 60), line, fontsize=11)
    for row_index, line in enumerate(right):
        page.insert_text((320, 100 + row_index * 60), line, fontsize=11)
    return CorpusDocument(
        f"two_column_{language}.pdf", document.tobytes(), tuple(left + right), needs_ocr=False
    )


def table_xlsx(language: str) -> CorpusDocument:
    """A small XLSX price list: one header row, three data rows."""
    header = _TABLE_HEADER[language]
    rows = _TABLE_ROWS[language]
    sheet = row(*header) + "".join(row(*values) for values in rows)
    ground_truth = (*header, *(value for values in rows for value in values))
    return CorpusDocument(f"table_{language}.xlsx", xlsx(sheet), ground_truth, needs_ocr=False)


def chat_screenshot(language: str, *, dark: bool = False) -> CorpusDocument:
    """A rendered PNG of a two-sided chat, in light or dark mode."""
    size = (1080, 1920)
    background, foreground = ("#111111", "#f0f0f0") if dark else ("#ffffff", "#111111")
    image = Image.new("RGB", size, background)
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=36)
    messages = _CHAT_MESSAGES[language]
    texts = []
    for row_index, (side, text) in enumerate(messages):
        x = 60 if side == "left" else size[0] - 60 - draw.textlength(text, font=font)
        draw.text((x, 200 + row_index * 120), text, fill=foreground, font=font)
        texts.append(text)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    suffix = "_dark" if dark else ""
    return CorpusDocument(
        f"chat_{language}{suffix}.png", buffer.getvalue(), tuple(texts), needs_ocr=True
    )


def code_screenshot(language: str) -> CorpusDocument:
    """A rendered PNG of a short function, indented like a code editor."""
    size = (1080, 700)
    image = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=32)
    for row_index, line in enumerate(_CODE_LINES):
        draw.text((60, 60 + row_index * 50), line, fill="black", font=font)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return CorpusDocument(f"code_{language}.png", buffer.getvalue(), _CODE_LINES, needs_ocr=True)


def synthetic_documents() -> list[CorpusDocument]:
    """One of each document kind per language, plus one dark-mode chat screenshot."""
    documents = []
    for language in LANGUAGES:
        documents.append(report_pdf(language))
        documents.append(two_column_pdf(language))
        documents.append(table_xlsx(language))
        documents.append(chat_screenshot(language))
        documents.append(code_screenshot(language))
    documents.append(chat_screenshot("en", dark=True))
    return documents
