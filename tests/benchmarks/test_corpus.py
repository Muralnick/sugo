"""The benchmark corpus converts cleanly: every document, no content lost (step 8, ROADMAP.md).

``benchmarks/`` sits outside ``src``, so these tests add it (and the
repository root, for its own reuse of a DOCX/XLSX test fixture) to
``sys.path`` directly, the same way the scripts there import each other.
"""

import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _path in (_REPO_ROOT, _REPO_ROOT / "benchmarks"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import pytest  # noqa: E402
from _text import character_error_rate  # type: ignore[import-not-found] # noqa: E402
from corpus import CorpusDocument, synthetic_documents  # type: ignore[import-not-found] # noqa: E402
from corpus_eur_lex import (  # type: ignore[import-not-found] # noqa: E402
    CORPUS_DIR,
    eur_lex_documents,
)

from sugo.core.pipeline import convert  # noqa: E402

# Real OCR on rendered text has a small, honest error rate (docs/TESTING.md);
# this only catches a regression far larger than what bundled models show today.
_MAX_CHARACTER_ERROR_RATE = 0.15


def _missing_text(ground_truth: tuple[str, ...], markdown: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", markdown).replace("\\", "")
    return [text for text in ground_truth if re.sub(r"\s+", " ", text).strip() not in normalized]


def _read_lines(markdown: str) -> list[str]:
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


def _assert_nothing_lost(document: CorpusDocument) -> None:
    languages = ("it", "es", "fr", "de", "en")
    conversion = convert(document.data, source=document.name, languages=languages)
    if document.needs_ocr:
        truth = [text.strip() for text in document.ground_truth]
        rate = character_error_rate(truth, _read_lines(conversion.markdown))
        assert rate <= _MAX_CHARACTER_ERROR_RATE, f"{document.name}: character_error_rate={rate}"
    else:
        missing = _missing_text(document.ground_truth, conversion.markdown)
        assert missing == [], f"{document.name}: lost {missing!r}"


@pytest.mark.parametrize("document", synthetic_documents(), ids=lambda d: d.name)
def test_synthetic_document_loses_no_content(document: CorpusDocument) -> None:
    _assert_nothing_lost(document)


def test_eur_lex_documents_lose_no_content() -> None:
    documents = eur_lex_documents()
    if not documents:
        pytest.skip(f"EUR-Lex sample not fetched under {CORPUS_DIR}")
    for document in documents:
        _assert_nothing_lost(document)


def test_eur_lex_documents_are_empty_without_the_external_corpus(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("corpus_eur_lex.CORPUS_DIR", tmp_path / "missing")
    assert eur_lex_documents() == []
