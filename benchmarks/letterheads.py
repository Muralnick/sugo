"""Scanned letterhead benchmark (ADR-064): repeated letterheads and look-alike body text.

Builds image-only PDFs in memory, as a scanner would: a letterhead of
coloured logo marks and small captions on every page, and different body
text on each page, with per-page noise and blur so the OCR reads the
captions differently each time. Control documents have no letterhead, but
every page starts and ends with formulaic text in the same language, the
body text most likely to be mistaken for a letterhead.

The gate (ADR-064 section 3): at least two thirds of the letterhead tokens
after page 1 are removed, no body text is lost, and nothing is removed from
the control documents. Nothing is stored or downloaded; run from the
repository root:

    uv run python benchmarks/letterheads.py
"""

import io
import json
import random
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pymupdf
from PIL import Image, ImageDraw, ImageFilter, ImageFont

_REPO_ROOT = str(Path(__file__).resolve().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

PAGE_SIZE = (1654, 2339)  # A4 at 200 dpi
INK = (25, 25, 25)

_CAPTIONS = (
    ("Regional Training Consortium", (30, 90, 170)),
    ("Technical Institute of Industry", (170, 40, 40)),
    ("Funded by the European Union", (20, 60, 150)),
    ("Learning enriches life", (40, 120, 60)),
)
_NOTE_WORDS = ("deliveries", "payments", "notices", "warranties", "disputes", "records")
_TOPICS = (
    "The supplier shall deliver the goods within thirty days of the order.",
    "The buyer shall pay each invoice within sixty days of its receipt.",
    "Either party may end this agreement with three months of written notice.",
    "The warranty covers defects of materials and workmanship for two years.",
    "Disputes shall be settled by the courts of the city where the buyer is based.",
    "The parties shall keep confidential every document exchanged under this contract.",
)


@dataclass(frozen=True)
class Document:
    """One scanned document: its PDF bytes, its body lines and its letterhead captions."""

    name: str
    pdf: bytes
    body: tuple[str, ...]
    captions: tuple[str, ...]
    pages: int


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    return ImageFont.load_default(size=size)


def _scan(image: Image.Image, rng: random.Random) -> bytes:
    """Make a page look scanned: a slight rotation, blur and noise, then JPEG compression."""
    image = image.rotate(
        rng.uniform(-0.4, 0.4), resample=Image.Resampling.BICUBIC, fillcolor="white"
    )
    image = image.filter(ImageFilter.GaussianBlur(rng.uniform(0.6, 1.1)))
    noise = Image.effect_noise(image.size, rng.uniform(18, 30)).convert("RGB")
    image = Image.blend(image, noise, 0.08)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=rng.randint(55, 75))
    return buffer.getvalue()


def _letterhead(draw: ImageDraw.ImageDraw) -> None:
    x = 120
    for caption, colour in _CAPTIONS:
        draw.ellipse((x, 70, x + 90, 160), outline=colour, width=8)
        draw.rectangle((x + 30, 100, x + 60, 130), fill=colour)
        draw.text((x - 10, 180), caption, fill=colour, font=_font(20))
        x += 370


def _page(
    lines: list[str],
    rng: random.Random,
    *,
    letterhead: bool,
    footer: str,
    notes: tuple[str, ...] = (),
    title: str = "",
) -> bytes:
    image = Image.new("RGB", PAGE_SIZE, "white")
    draw = ImageDraw.Draw(image)
    if letterhead:
        _letterhead(draw)
    if title:
        # A small running title that changes on every page: content, not a letterhead.
        draw.text((160, 90), title, fill=INK, font=_font(20))
    top = 300 if letterhead else 170
    for line in lines:
        draw.text((160, top), line, fill=INK, font=_font(30))
        top += 54
    draw.text((160, 2180), footer, fill=INK, font=_font(30))
    # Footnotes in small print at the bottom: formulaic, different on each page.
    for index, note in enumerate(notes):
        draw.text((160, 2010 + index * 32), note, fill=INK, font=_font(20))
    return _scan(image, rng)


def _pdf(scans: list[bytes]) -> bytes:
    document = pymupdf.open()
    for scan in scans:
        page = document.new_page(width=595.2, height=841.7)
        page.insert_image(page.rect, stream=scan)
    return document.tobytes()


def document(
    name: str,
    pages: int,
    seed: int,
    *,
    letterhead: bool,
    footnotes: bool = False,
    titles: bool = False,
) -> Document:
    rng = random.Random(seed)  # noqa: S311 - reproducible drawings, not secrets
    scans: list[bytes] = []
    body: list[str] = []
    for n in range(pages):
        lines = [f"Article {n + 1}. {_TOPICS[(n + k) % len(_TOPICS)]}" for k in range(3)]
        footer = f"Signed in Bergamo, record {n + 1} of the meeting held on 31 March 2026."
        notes = (
            (
                f"{n + 1}. See the annex of the regulation for the rules on {_NOTE_WORDS[n % 6]}.",
                f"{n + 2}. The same rules apply to the {_NOTE_WORDS[(n + 3) % 6]} of each member.",
            )
            if footnotes
            else ()
        )
        title = f"Supply agreement, section {n + 1}: {_NOTE_WORDS[n % 6]}" if titles else ""
        scans.append(
            _page(lines, rng, letterhead=letterhead, footer=footer, notes=notes, title=title)
        )
        body += [*lines, footer, *notes, *([title] if title else [])]
    captions = tuple(caption for caption, _ in _CAPTIONS) if letterhead else ()
    return Document(name, _pdf(scans), tuple(body), captions, pages)


def documents() -> list[Document]:
    return [
        document("letterhead_3_pages", 3, 1, letterhead=True),
        document("letterhead_6_pages", 6, 2, letterhead=True),
        document("control_3_pages", 3, 3, letterhead=False),
        document("control_6_pages", 6, 4, letterhead=False),
        document("control_footnotes_6_pages", 6, 5, letterhead=False, footnotes=True),
        document("letterhead_footnotes_6_pages", 6, 6, letterhead=True, footnotes=True),
        document("control_running_titles_6_pages", 6, 7, letterhead=False, titles=True),
    ]


def _words(text: str) -> list[str]:
    return text.casefold().split()


def _check(doc: Document, markdown: str, removed: list[str]) -> dict[str, object]:
    from sugo.metrics.tokenizer import count_tokens

    words = set(_words(markdown))
    # A body line counts as kept when nearly all its words survive OCR.
    lost = [
        line for line in doc.body if sum(w in words for w in _words(line)) < 0.8 * len(_words(line))
    ]
    removed_body = [
        text
        for text in removed
        if any(w in _words(text) for w in ("article", "signed", "shall", "see", "rules", "section"))
    ]
    letterhead_tokens = sum(count_tokens(text) for text in removed if text not in removed_body)
    row: dict[str, object] = {
        "document": doc.name,
        "pages": doc.pages,
        "removed_blocks": len(removed),
        "removed_letterhead_tokens": letterhead_tokens,
        "removed_body": removed_body,
        "body_lost": lost,
    }
    if doc.captions:
        # Tokens of the captions on every page after the first, as drawn.
        expected = (doc.pages - 1) * sum(count_tokens(caption) for caption in doc.captions)
        row["letterhead_tokens_after_page_1"] = expected
        row["ok"] = letterhead_tokens >= 2 / 3 * expected and not removed_body and not lost
    else:
        row["ok"] = not removed and not lost
    return row


def main() -> int:
    from sugo.core.pipeline import convert

    rows = []
    for doc in documents():
        conversion = convert(doc.pdf, receipt=True)
        receipt = conversion.receipt
        removed = [] if receipt is None else [entry.text for entry in receipt.removed]
        rows.append(_check(doc, conversion.markdown, removed))
    for row in rows:
        status = "ok  " if row["ok"] else "FAIL"
        details = {key: value for key, value in row.items() if key not in ("document", "ok")}
        sys.stdout.write(f"{status} {row['document']:<20} {details}\n")
    out = Path(_REPO_ROOT) / "benchmarks" / "results" / f"letterheads_{date.today()}.json"
    out.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8", newline="\n")
    return 0 if all(row["ok"] for row in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
