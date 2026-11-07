"""Handwriting benchmark (ADR-063): signed scans and scans without handwriting.

Builds image-only PDFs in memory, as a scanner would make them: typed text
drawn at 200 dpi, with pen-stroke signatures in black or blue ink under,
beside or across the typed names. Control pages hold no handwriting at all
but the typed text most likely to be mistaken for it: large headings, a
coloured heading, coloured small text and a large grey stamp.

The gate (ADR-063 section 5): every signature becomes ``[handwriting]``
with no made-up words left, and no typed text away from the ink is lost.
Typed names crossed by a signature are reported apart: the OCR may not
read them at all, with or without this check. Nothing is stored or
downloaded; run from the repository root:

    uv run python benchmarks/handwriting.py
"""

import io
import json
import math
import random
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pymupdf
from PIL import Image, ImageDraw, ImageFont

_REPO_ROOT = str(Path(__file__).resolve().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

DPI = 200
# A4 at 200 dpi.
PAGE_SIZE = (1654, 2339)
BLACK = (25, 25, 25)
BLUE = (40, 70, 190)
MARKER = "[handwriting]"

_BODY = (
    "The meeting took place on 31 March 2026 at 15:00 by video call.",
    "The committee examined every application received within the deadline.",
    "Each candidate was assessed on language skills, motivation and experience.",
    "The final ranking will be published on the website of each school.",
    "This record is drafted, approved and signed to be kept on file.",
)
_NAMES = ("Anna Rossi", "Marco Bianchi", "Elena Ferrari", "Paolo Greco")


@dataclass(frozen=True)
class Page:
    """One scanned page: its PDF bytes, what must survive and what must not appear."""

    name: str
    pdf: bytes
    # Typed text away from any ink, which must stay in the Markdown word for word.
    typed: tuple[str, ...]
    # Typed names with a signature near them: reported, not part of the gate,
    # since ink across a name can make it unreadable to the OCR.
    names: tuple[str, ...]
    # Signatures drawn on the page: each must become one marker.
    signatures: int


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    return ImageFont.load_default(size=size)


def _signature(
    draw: ImageDraw.ImageDraw,
    x: float,
    y: float,
    width: float,
    rng: random.Random,
    ink: tuple[int, int, int],
) -> None:
    """Draw a cursive-like pen stroke: loops along a baseline, then a flourish."""
    points: list[tuple[float, float]] = []
    loops = rng.randint(5, 9)
    height = rng.uniform(45, 75)
    steps = 240
    for i in range(steps + 1):
        t = i / steps
        angle = t * loops * 2 * math.pi
        px = x + t * width + 0.35 * height * math.cos(angle)
        py = y - 0.5 * height * (1 + math.sin(angle)) * rng.uniform(0.85, 1.0)
        points.append((px, py))
    # A long underline flourish back to the left.
    end = points[-1]
    for i in range(1, 41):
        t = i / 40
        points.append((end[0] - t * width * 0.9, end[1] + 12 + 10 * math.sin(t * math.pi)))
    draw.line(points, fill=ink, width=rng.randint(3, 4), joint="curve")


def _to_pdf(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    document = pymupdf.open()
    page = document.new_page(width=595.2, height=841.7)
    page.insert_image(page.rect, stream=buffer.getvalue())
    return document.tobytes()


def _body(draw: ImageDraw.ImageDraw, top: int) -> int:
    font = _font(30)
    for line in _BODY:
        draw.text((160, top), line, fill=BLACK, font=font)
        top += 52
    return top


def signed_page(placement: str, ink: tuple[int, int, int], seed: int) -> Page:
    """A record with three typed names, each signed ``under``, ``beside`` or ``across`` it."""
    rng = random.Random(seed)  # noqa: S311 - reproducible drawings, not secrets
    image = Image.new("RGB", PAGE_SIZE, "white")
    draw = ImageDraw.Draw(image)
    font = _font(30)
    draw.text((160, 160), "MEETING RECORD", fill=BLACK, font=_font(44))
    top = _body(draw, 300) + 80
    draw.text((160, top), "The Committee", fill=BLACK, font=font)
    top += 110
    names = _NAMES[:3]
    for name in names:
        draw.text((180, top), name, fill=BLACK, font=font)
        width = rng.uniform(260, 380)
        if placement == "under":
            _signature(draw, 170, top + 120, width, rng, ink)
        elif placement == "beside":
            _signature(draw, 600, top + 50, width, rng, ink)
        else:  # across
            _signature(draw, 170, top + 60, width, rng, ink)
        top += 230
    colour = "blue" if ink == BLUE else "black"
    return Page(f"signed_{placement}_{colour}", _to_pdf(image), (*_BODY, "The Committee"), names, 3)


def control_page(seed: int) -> Page:
    """No handwriting: large, coloured and grey typed text that could be mistaken for it."""
    image = Image.new("RGB", PAGE_SIZE, "white")
    draw = ImageDraw.Draw(image)
    draw.text((160, 140), "ANNUAL REPORT", fill=BLACK, font=_font(84))
    draw.text((160, 280), "Regional Training Consortium", fill=BLUE, font=_font(56))
    top = _body(draw, 420)
    draw.text((160, top + 20), "More at www.example.org/report", fill=BLUE, font=_font(30))
    draw.text((160, top + 140), "Results", fill=BLACK, font=_font(60))
    draw.text((900, 1900), "APPROVED", fill=(150, 150, 150), font=_font(90))
    typed = (
        "ANNUAL REPORT",
        "Regional Training Consortium",
        *_BODY,
        "www.example.org/report",
        "Results",
        "APPROVED",
    )
    return Page(f"control_{seed}", _to_pdf(image), typed, (), 0)


def pages() -> list[Page]:
    result: list[Page] = []
    seed = 0
    for placement in ("under", "beside", "across"):
        for ink in (BLACK, BLUE):
            seed += 1
            result.append(signed_page(placement, ink, seed))
    result.append(control_page(1))
    return result


def _check(page: Page, markdown: str) -> dict[str, object]:
    """The ADR-063 gate: every signature marked, no made-up words, typed text kept."""
    markers = markdown.count(MARKER)
    missing = [text for text in page.typed if text not in markdown]
    # Below the signers' heading, every line is a name, a marker or made-up words.
    made_up: list[str] = []
    if page.signatures:
        signing = markdown.split("The Committee", 1)[-1]
        for text in signing.splitlines():
            rest = text.replace(MARKER, "").replace("[illegible]", "")
            for name in page.names:
                rest = rest.replace(name, "")
            if rest.strip():
                made_up.append(text.strip())
    return {
        "page": page.name,
        "signatures": page.signatures,
        "markers": markers,
        "made_up": made_up,
        "typed_missing": missing,
        "names_missing": [name for name in page.names if name not in markdown],
        "ok": markers == page.signatures and not made_up and not missing,
    }


def main() -> int:
    from sugo.core.pipeline import convert

    rows = []
    for page in pages():
        conversion = convert(page.pdf)
        rows.append(_check(page, conversion.markdown))
    for row in rows:
        status = "ok  " if row["ok"] else "FAIL"
        sys.stdout.write(
            f"{status} {row['page']:<22} signatures={row['signatures']} "
            f"markers={row['markers']} made_up={row['made_up']} "
            f"typed_missing={row['typed_missing']} names_missing={row['names_missing']}\n"
        )
    out = Path(_REPO_ROOT) / "benchmarks" / "results" / f"handwriting_{date.today()}.json"
    out.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8", newline="\n")
    return 0 if all(row["ok"] for row in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
