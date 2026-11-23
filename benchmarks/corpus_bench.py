"""Run the benchmark corpus through sugo: savings, content accuracy, time and memory.

Run with ``uv run python benchmarks/corpus_bench.py [--level normal]`` on the reference
machine (8 GB RAM, 4 cores, no GPU; docs/TESTING.md); close other programs
first, timings are sensitive to load. Covers the synthetic corpus
(``corpus.py``, generated in memory) and, once fetched, the EUR-Lex sample
(``corpus_eur_lex.py``); EUR-Lex is skipped with a note if its text has not
been fetched. Every document keeps an exact ground truth, so "content lost"
is measured, not guessed, alongside token savings (TESTING.md's golden
rule). Results go to standard output as JSON and are archived under
``benchmarks/results/``.

``--level normal`` needs ``sugo-cli[normal]`` and ``sugo models pull normal``
(ADR-071); only PDFs read differently at that level. Docling runs in a child
process, so the report also gives the largest child's peak memory.
"""

import argparse
import json
import re
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from _memory import peak_child_rss_mb, peak_rss_mb
from _text import character_error_rate
from corpus import CorpusDocument, synthetic_documents
from corpus_eur_lex import eur_lex_documents

from sugo.core.estimate import estimate_savings
from sugo.core.pipeline import convert
from sugo.metrics.providers import list_providers

RUNS = 3
RESULTS_DIR = Path(__file__).resolve().parent / "results"


def _missing_text(ground_truth: tuple[str, ...], markdown: str) -> list[str]:
    """Ground-truth paragraphs the output drops: ignores line wrap, edge space, Markdown escapes."""
    normalized = re.sub(r"\s+", " ", markdown).replace("\\", "")
    return [text for text in ground_truth if re.sub(r"\s+", " ", text).strip() not in normalized]


def _read_lines(markdown: str) -> list[str]:
    """Markdown's visible lines, with a chat speaker prefix or a code fence stripped."""
    lines = []
    for line in markdown.splitlines():
        line = line.strip()
        if not line or line == "```":
            continue
        head, sep, rest = line.partition(": ")
        if sep and head in ("left", "right"):
            line = rest
        lines.append(line)
    return lines


def _rows_intact(rows: tuple[tuple[str, ...], ...], markdown: str) -> int:
    """Table rows whose cells all come out on one Markdown line, in any table format."""
    lines = [line.replace("\\", "") for line in markdown.splitlines()]
    return sum(1 for cells in rows if any(all(cell in line for cell in cells) for line in lines))


def _bench_one(document: CorpusDocument, providers: list[str], level: str) -> dict[str, Any]:
    timings = []
    start = time.perf_counter()
    conversion = convert(document.data, source=document.name, count_raw_tokens=True, level=level)
    timings.append(time.perf_counter() - start)
    for _ in range(RUNS - 1):
        start = time.perf_counter()
        convert(document.data, source=document.name, count_raw_tokens=True, level=level)
        timings.append(time.perf_counter() - start)
    savings = estimate_savings(document.data, conversion, providers)
    content: dict[str, Any]
    if document.needs_ocr:
        truth = [text.strip() for text in document.ground_truth]
        content = {
            "character_error_rate": character_error_rate(truth, _read_lines(conversion.markdown))
        }
    else:
        content = {"missing_text": _missing_text(document.ground_truth, conversion.markdown)}
    if document.table_rows:
        content["table_rows"] = len(document.table_rows)
        content["table_rows_intact"] = _rows_intact(document.table_rows, conversion.markdown)
    return {
        "name": document.name,
        "pages": conversion.pages,
        "tokens_before": savings.text.baseline_tokens,
        "tokens_after": savings.text.result_tokens,
        "saved_percent": round(savings.text.saved_percent, 1),
        "image_baseline": [
            {"provider": image.provider, "saved_percent": round(image.saved_percent, 1)}
            for image in savings.images
        ],
        "removed": dict(conversion.removed),
        "median_s": round(statistics.median(timings), 3),
        **content,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--level", choices=("lite", "normal"), default="lite")
    level = parser.parse_args().level
    documents = synthetic_documents() + eur_lex_documents()
    if not any(document.name.startswith("eur_lex_") for document in documents):
        sys.stderr.write(
            "note: EUR-Lex sample not found under benchmarks/corpus_eur_lex.CORPUS_DIR; "
            "running the synthetic corpus only.\n"
        )
    # One throwaway OCR conversion loads the engine before anything is timed.
    for document in documents:
        if document.needs_ocr:
            convert(document.data, source=document.name)
            break
    if level != "lite":
        # Likewise for Docling: its first load reads the models from disk.
        first_pdf = next(document for document in documents if document.name.endswith(".pdf"))
        convert(first_pdf.data, source=first_pdf.name, level=level)
    providers = list_providers()
    results = [_bench_one(document, providers, level) for document in documents]
    content_issues = [
        result["name"]
        for result in results
        if result.get("missing_text") or result.get("character_error_rate", 0.0) > 0.0
    ]
    child_peak = peak_child_rss_mb()
    report = {
        "date": datetime.now(UTC).date().isoformat(),
        "level": level,
        "documents": len(results),
        "peak_rss_mb": round(peak_rss_mb()),
        "peak_child_rss_mb": None if child_peak is None else round(child_peak),
        "median_tokens_saved_percent": round(
            statistics.median(result["saved_percent"] for result in results), 1
        ),
        "content_issues": content_issues,
        "results": results,
    }
    RESULTS_DIR.mkdir(exist_ok=True)
    suffix = "" if level == "lite" else f"_{level}"
    out_path = RESULTS_DIR / f"corpus_bench_{report['date']}{suffix}.json"
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    sys.stdout.write(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
