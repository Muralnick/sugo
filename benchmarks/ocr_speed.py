"""Measure OCR speed, memory and accuracy on a synthetic phone screenshot.

Run with ``uv run python benchmarks/ocr_speed.py`` on the reference machine
(8 GB RAM, 4 cores, no GPU; docs/TESTING.md). The image is generated, so the
ground truth is exact and no document leaves the repository. Results go to
standard output as JSON; close other programs first, timings are sensitive to
load.
"""

import json
import resource
import statistics
import sys
import time
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from sugo.extractors.image.classifier import classify
from sugo.extractors.image.loader import decode_image
from sugo.extractors.image.ocr_engine import OcrEngine, bundled_models
from sugo.extractors.image.preprocess import preprocess

RUNS = 5
SIZE = (1170, 2532)  # iPhone screenshot
LINE_COUNT = 30
LATIN_FONT = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
SAMPLE_LINES = (
    "Il contratto è già firmato, perché così.",
    "Der Vertrag ist schon unterschrieben.",
    "¿Dónde está el señor Muñoz?",
    "L'été dernier, nous étions à Paris.",
    "def total(items): return sum(items)",
    "Ciao Marco, ci vediamo alle 18:30?",
)


def _edit_distance(a: str, b: str) -> int:
    previous = list(range(len(b) + 1))
    for i, char_a in enumerate(a, 1):
        current = [i]
        for j, char_b in enumerate(b, 1):
            current.append(
                min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (char_a != char_b))
            )
        previous = current
    return previous[-1]


def _screenshot() -> tuple[bytes, list[str]]:
    # DejaVu covers the accented sample lines; Pillow's own font is ASCII-only.
    if LATIN_FONT.exists():
        font = ImageFont.truetype(str(LATIN_FONT), 40)
        lines = [SAMPLE_LINES[i % len(SAMPLE_LINES)] for i in range(LINE_COUNT)]
    else:
        font = ImageFont.load_default(size=40)
        lines = [f"Line {i}: the contract may be withdrawn." for i in range(LINE_COUNT)]
    image = Image.new("RGB", SIZE, "white")
    draw = ImageDraw.Draw(image)
    for row, line in enumerate(lines):
        draw.text((40 + (200 if row % 2 else 0), 100 + row * 78), line, fill="black", font=font)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue(), lines


def main() -> None:
    """Run the benchmark and write one JSON object to standard output."""
    data, truth = _screenshot()
    start = time.perf_counter()
    engine = OcrEngine(*bundled_models())
    load_seconds = time.perf_counter() - start

    timings = []
    lines = []
    for _ in range(RUNS + 1):  # the first run warms up and is not counted
        start = time.perf_counter()
        loaded = decode_image(data)
        lines = engine.read(preprocess(loaded, classify(loaded)))
        timings.append(time.perf_counter() - start)

    read = [line.text for line in sorted(lines, key=lambda line: line.bbox.y0)]
    errors = sum(_edit_distance(a, b) for a, b in zip(truth, read, strict=False))
    errors += sum(len(line) for line in truth[len(read) :])
    result = {
        "image": f"{SIZE[0]}x{SIZE[1]}, {LINE_COUNT} lines",
        "model_load_s": round(load_seconds, 2),
        "warm_median_s": round(statistics.median(timings[1:]), 2),
        "peak_rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024),
        "lines_found": len(read),
        "character_error_rate": round(errors / sum(len(line) for line in truth), 4),
    }
    sys.stdout.write(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
