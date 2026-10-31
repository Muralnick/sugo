"""Tests for the multi-pass pipeline: routing, cleaning order, cache, resume and fallbacks."""

from collections.abc import Callable, Iterator
from io import BytesIO
from pathlib import Path

import pymupdf
import pytest
from PIL import Image, ImageDraw, ImageFont

from sugo.core import pipeline
from sugo.core.decisions import EditDecision
from sugo.core.models import EditKind, Page
from sugo.core.pipeline import (
    InputKind,
    InputUnsupportedError,
    convert,
    convert_file,
    detect_kind,
    read_input,
)
from sugo.exporters.jsonl import write_jsonl
from sugo.extractors.image.ocr_engine import OcrEngine, bundled_models
from sugo.extractors.pymupdf.extract import _failed_page, extract_pdf
from sugo.extractors.pymupdf.protocol import PageBox
from sugo.metrics.tokenizer import count_tokens
from sugo.storage.page_cache import CacheLevel, CacheUnavailableError, PageCache

CLAUSE = "The supplier is liable for all damages caused by delays."


def report(pages: int) -> bytes:
    """A short report: running header, a footer clause, page numbers, distinct bodies."""
    document = pymupdf.open()
    for n in range(pages):
        page = document.new_page()
        page.insert_text((72, 40), "ACME Corporation - Annual Report 2026", fontsize=10)
        page.insert_text(
            (72, 120), f"Section {n + 1} of the report says something new.", fontsize=10
        )
        page.insert_text((72, 780), CLAUSE, fontsize=10)
        page.insert_text((290, 815), str(n + 1), fontsize=10)
    return document.tobytes()


EXPECTED = "\n\n".join(
    [f"Section 1 of the report says something new.\n\n{CLAUSE}"]
    + [f"Section {n} of the report says something new." for n in range(2, 5)]
)


@pytest.fixture(scope="module")
def engine() -> OcrEngine:
    return OcrEngine(*bundled_models())


@pytest.fixture
def cache(tmp_path: Path) -> Iterator[PageCache]:
    with PageCache(tmp_path / "cache" / "cache.db") as opened:
        yield opened


class CountingExtractor:
    """Wraps the real PDF extractor, recording each call's start and pages."""

    def __init__(
        self, stop_after: int | None = None, fail: frozenset[int] | set[int] = frozenset()
    ) -> None:
        self.starts: list[int] = []
        self.pages = 0
        self._stop_after = stop_after
        self._fail = fail

    def __call__(self, data: bytes, **options: object) -> Iterator[Page]:
        self.starts.append(int(str(options.get("start", 0))))
        for page in extract_pdf(data, **options):  # type: ignore[arg-type]
            if self._stop_after is not None and self.pages == self._stop_after:
                raise KeyboardInterrupt  # The job is interrupted.
            self.pages += 1
            if page.index in self._fail:
                # What the extractor yields for a page the worker could not read.
                box = PageBox(width=page.width, height=page.height, rotation=0)
                page = _failed_page(page.index, box)
            yield page


def test_pdf_report_becomes_clean_markdown() -> None:
    result = convert(report(4))
    assert result.markdown == EXPECTED
    assert (result.kind, result.pages) == (InputKind.PDF, 4)
    assert dict(result.removed) == {"headers_footers": 7, "page_numbers": 4}


def test_raw_tokens_are_counted_only_when_asked(cache: PageCache) -> None:
    data = report(4)
    assert convert(data).raw_tokens is None
    measured = convert(data, cache=cache, count_raw_tokens=True)
    # The raw text keeps the running headers and page numbers the cleaners remove.
    assert measured.raw_tokens is not None
    assert measured.raw_tokens > count_tokens(measured.markdown)
    # Measuring never changes the output, nor the settings digest.
    assert measured.markdown == EXPECTED
    assert measured.config_hash == convert(data).config_hash
    # From the cache, the raw pages are read back and counted the same.
    assert convert(data, cache=cache, count_raw_tokens=True).raw_tokens == measured.raw_tokens


def test_input_is_read_up_to_one_byte_past_the_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pipeline, "_MAX_INPUT_BYTES", 10)
    path = tmp_path / "big.bin"
    path.write_bytes(b"x" * 100)
    assert read_input(path) == b"x" * 11


def test_input_is_routed_by_content_not_name(tmp_path: Path) -> None:
    path = tmp_path / "looks-like.png"
    path.write_bytes(report(4))
    assert convert_file(path).markdown == EXPECTED


def test_unsupported_input_is_refused() -> None:
    with pytest.raises(InputUnsupportedError, match="PDF, PNG, JPEG, WEBP or XML") as caught:
        detect_kind(b"PK\x03\x04 a zip or docx file")
    assert caught.value.code == "INPUT_UNSUPPORTED"


def test_xml_is_converted_and_cached(cache: PageCache) -> None:
    data = b"<invoice><number>7</number><note>Thanks</note></invoice>"
    assert detect_kind(data) is InputKind.XML
    first = convert(data, cache=cache)
    assert (first.kind, first.pages, first.secret_blocks) == (InputKind.XML, 1, 0)
    assert first.markdown == "invoice:\n  number: 7\n  note: Thanks"
    # The cached page answers the second run, flags included.
    secret = b"<config><user>u</user><password>p</password></config>"
    assert convert(secret, cache=cache).secret_blocks == 1
    assert convert(secret, cache=cache).secret_blocks == 1
    assert convert(data, cache=cache).markdown == first.markdown


def test_screenshot_loses_its_status_bar(engine: OcrEngine) -> None:
    image = Image.new("RGB", (750, 1334), "white")  # A phone screen.
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=30)
    draw.text((30, 20), "9:41", fill="black", font=font)
    draw.text((40, 200), "The meeting moved to Friday morning.", fill="black", font=font)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    result = convert(buffer.getvalue(), ocr=lambda: engine)
    assert result.kind is InputKind.IMAGE
    assert result.markdown == "The meeting moved to Friday morning."
    assert dict(result.removed) == {"ui_chrome": 1}


def test_second_run_reads_everything_from_the_cache(
    cache: PageCache, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = report(4)
    first = convert(data, cache=cache)
    counting = CountingExtractor()
    monkeypatch.setattr(pipeline, "extract_pdf", counting)
    second = convert(data, cache=cache)
    assert second == first
    # The worker only opened and checked the file; no page was read again.
    assert (counting.starts, counting.pages) == ([4], 0)


def test_interrupted_job_resumes_where_it_stopped(
    cache: PageCache, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = report(4)
    monkeypatch.setattr(pipeline, "extract_pdf", CountingExtractor(stop_after=2))
    with pytest.raises(KeyboardInterrupt):
        convert(data, cache=cache)
    resumed = CountingExtractor()
    monkeypatch.setattr(pipeline, "extract_pdf", resumed)
    assert convert(data, cache=cache).markdown == EXPECTED
    assert (resumed.starts, resumed.pages) == ([2], 2)


def test_failed_pages_are_retried_on_the_next_run(
    cache: PageCache, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = report(4)
    monkeypatch.setattr(pipeline, "extract_pdf", CountingExtractor(fail={1}))
    first = convert(data, cache=cache)
    assert first.markdown.count("[illegible]") == 1
    # Page numbers count from 1: the second page failed.
    assert first.failed_pages == (2,)
    # The other pages are cached; the failed one, and its cleaned form, are not.
    retry = CountingExtractor()
    monkeypatch.setattr(pipeline, "extract_pdf", retry)
    second = convert(data, cache=cache)
    assert second.markdown == EXPECTED
    assert second.failed_pages == ()
    # Only the failed page is read again; the cached pages after it are skipped.
    assert (retry.starts, retry.pages) == ([1], 1)


def test_ephemeral_store_unavailable_keeps_pages_in_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable() -> PageCache:
        raise CacheUnavailableError("disk full")

    monkeypatch.setattr(PageCache, "ephemeral", unavailable)
    assert convert(report(4)).markdown == EXPECTED


def test_pages_the_cache_refuses_are_kept_in_memory(
    cache: PageCache, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cache, "put", lambda *_: False)  # A full disk.
    assert convert(report(4), cache=cache).markdown == EXPECTED


def test_page_lost_from_the_store_is_extracted_again(
    cache: PageCache, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_get: Callable[[CacheLevel, bytes], Page | None] = cache.get

    def forgetful(level: CacheLevel, key: bytes) -> Page | None:
        # Another process cleared the cache: extracted pages vanish.
        return None if level is CacheLevel.EXTRACTION else real_get(level, key)

    monkeypatch.setattr(cache, "get", forgetful)
    lost = CountingExtractor()
    monkeypatch.setattr(pipeline, "extract_pdf", lost)
    assert convert(report(4), cache=cache).markdown == EXPECTED
    # One full extraction, then each lost page read again once, not once per pass.
    assert lost.starts == [0, 0, 1, 2, 3]


def test_engines_have_distinct_identities() -> None:
    pdf = pipeline._engine_identity(InputKind.PDF)
    image = pipeline._engine_identity(InputKind.IMAGE)
    assert pdf.startswith("pdf:pymupdf=")
    assert image.startswith("image:rapidocr=")


def test_chunks_cover_the_markdown_and_trace_their_pages() -> None:
    result = convert(report(4), source="reports/acme.pdf", max_chunk_tokens=32)
    assert len(result.chunks) > 1
    assert " ".join(c.text for c in result.chunks).split() == result.markdown.split()
    assert {c.document_id for c in result.chunks} == {result.chunks[0].document_id}
    assert all(c.source == "reports/acme.pdf" for c in result.chunks)
    assert sorted({p for c in result.chunks for p in c.pages}) == [1, 2, 3, 4]
    assert result.chunks[0].config_hash == result.config_hash


def test_no_chunks_unless_asked() -> None:
    assert convert(report(4)).chunks == ()


def test_chunk_size_changes_the_config_hash() -> None:
    data = report(4)
    small = convert(data, max_chunk_tokens=32)
    large = convert(data, max_chunk_tokens=512)
    assert small.config_hash != large.config_hash


def test_too_small_chunks_are_refused() -> None:
    with pytest.raises(ValueError, match="at least 32"):
        convert(report(1), max_chunk_tokens=8)


def test_output_is_reproducible(tmp_path: Path) -> None:
    # Principle 6: same input and configuration, same bytes.
    data = report(4)
    for name in ("a", "b"):
        result = convert(data, source="acme.pdf", max_chunk_tokens=64)
        write_jsonl(tmp_path / f"{name}.jsonl", result.chunks)
    assert (tmp_path / "a.jsonl").read_bytes() == (tmp_path / "b.jsonl").read_bytes()


def text_report() -> bytes:
    """Two pages of prose with a line-break hyphen and a tracking URL."""
    document = pymupdf.open()
    first = document.new_page()
    first.insert_text((72, 100), "Good information matters.", fontsize=10)
    first.insert_text((72, 112), "Details at https://a.it/p?id=7&utm_source=mail", fontsize=10)
    second = document.new_page()
    second.insert_text((72, 100), "More infor-", fontsize=10)
    second.insert_text((72, 112), "mation here.", fontsize=10)
    return document.tobytes()


def test_text_cleaners_join_hyphens_and_strip_trackers() -> None:
    result = convert(text_report(), languages=("en", "it"))
    assert "https://a.it/p?id=7\n" in result.markdown + "\n"
    assert "utm_source" not in result.markdown
    assert "More information here" in result.markdown


def test_edits_are_counted_per_cleaner() -> None:
    result = convert(text_report())
    assert result.edited == {"text_normalization": 1, "tracking_urls": 1}
    assert result.removed == {}


def test_a_refused_cleaner_is_skipped_not_fatal(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    class Broken:
        name = "broken"

        def propose(self, page: Page, stats: object) -> list[EditDecision]:
            # Changes a letter: the core refuses it.
            return [
                EditDecision(
                    block_id=block.id,
                    start=0,
                    end=1,
                    replacement="X",
                    kind=EditKind.NORMALIZE,
                    reason="r",
                )
                for block in page.blocks
                if block.text
            ]

    monkeypatch.setattr(pipeline, "CLEANERS", (*pipeline.CLEANERS, Broken()))
    result = convert(text_report())
    assert "Good information matters." in result.markdown
    assert "cleaner broken skipped" in caplog.text
    assert "Good" not in caplog.text


def test_tracking_urls_can_be_kept() -> None:
    result = convert(text_report(), strip_tracking_urls=False)
    assert "utm_source=mail" in result.markdown


def test_text_settings_change_the_config_hash() -> None:
    data = text_report()
    base = convert(data).config_hash
    assert convert(data, languages=("it",)).config_hash != base
    assert convert(data, strip_tracking_urls=False).config_hash != base
    assert convert(data, languages=("en", "en")).config_hash == base


def test_unknown_language_is_refused() -> None:
    with pytest.raises(ValueError, match="no language pack"):
        convert(text_report(), languages=("xx",))
