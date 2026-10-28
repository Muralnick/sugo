"""Tests for sugo.extractors.image.ocr_engine, with the real bundled models."""

import shutil
import socket
from collections.abc import Callable
from pathlib import Path
from typing import Any, NoReturn

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont
from rapidocr.utils.output import RapidOCROutput

from sugo.extractors.image import ocr_engine
from sugo.extractors.image.classifier import classify
from sugo.extractors.image.loader import decode_image
from sugo.extractors.image.ocr_engine import (
    ModelIntegrityError,
    OcrEngine,
    OcrModel,
    bundled_models,
)
from sugo.extractors.image.preprocess import PreparedImage, preprocess

Encode = Callable[..., bytes]
Screenshot = Callable[..., Image.Image]

LINES = ("Invoice number 4521", "Total due 1250 EUR", "Payment within 30 days")


@pytest.fixture(scope="module")
def engine() -> OcrEngine:
    return OcrEngine(*bundled_models())


def text_image(
    lines: tuple[str, ...] = LINES, *, size: tuple[int, int] = (900, 300)
) -> Image.Image:
    image = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=30)
    for row, line in enumerate(lines):
        draw.text((40, 40 + row * 80), line, fill="black", font=font)
    return image


def prepare(encode: Encode, image: Image.Image) -> PreparedImage:
    loaded = decode_image(encode(image, "PNG"))
    return preprocess(loaded, classify(loaded))


def test_reads_lines_with_boxes_in_reading_order(engine: OcrEngine, encode: Encode) -> None:
    lines = engine.read(prepare(encode, text_image()))
    assert [line.text for line in lines] == list(LINES)
    assert all(not line.illegible and line.confidence > 0.9 for line in lines)
    tops = [line.bbox.y0 for line in lines]
    assert tops == sorted(tops)
    # The first line was drawn at x = 40 px of 900 and y = 40 px of 300.
    assert lines[0].bbox.x0 == pytest.approx(40 / 900, abs=0.02)
    assert lines[0].bbox.y0 == pytest.approx(40 / 300, abs=0.03)


def test_dark_mode_screenshot_is_read_after_preprocessing(
    engine: OcrEngine, encode: Encode, screenshot: Screenshot
) -> None:
    lines = engine.read(prepare(encode, screenshot(dark=True)))
    assert any("contract may be withdrawn" in line.text for line in lines)


def test_upscaled_image_keeps_normalised_boxes(engine: OcrEngine, encode: Encode) -> None:
    # The small copy is upscaled by preprocessing; boxes must still line up.
    large = engine.read(prepare(encode, text_image(size=(900, 300))))
    small_image = text_image(size=(900, 300)).resize((450, 150), Image.Resampling.LANCZOS)
    small = engine.read(prepare(encode, small_image))
    assert len(small) == len(large)
    for a, b in zip(small, large, strict=True):
        assert a.bbox.x0 == pytest.approx(b.bbox.x0, abs=0.02)
        assert a.bbox.y0 == pytest.approx(b.bbox.y0, abs=0.03)


def test_image_without_text_has_no_lines(engine: OcrEngine, encode: Encode) -> None:
    assert engine.read(prepare(encode, Image.new("RGB", (400, 300), "white"))) == []


def test_pixels_reach_rapidocr_in_bgr_order(engine: OcrEngine) -> None:
    received: list[np.ndarray] = []

    class Recorder:
        def __call__(self, image: np.ndarray) -> Any:
            received.append(image)
            return RapidOCROutput()

    pixels = np.zeros((10, 10, 3), dtype=np.uint8)
    pixels[..., 0] = 255  # pure red in RGB
    recorder_engine = object.__new__(OcrEngine)
    recorder_engine._engine = Recorder()  # type: ignore[assignment]
    recorder_engine.read(PreparedImage(pixels=pixels, inverted=False, scale=1))
    assert tuple(received[0][0, 0]) == (0, 0, 255)


@pytest.mark.invariant
def test_low_confidence_lines_are_marked_never_filled(
    engine: OcrEngine, encode: Encode, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Principle 4: with a threshold no line can reach, every line is unreadable,
    # so every line must keep its box and lose its guessed text.
    monkeypatch.setattr(ocr_engine, "OCR_MIN_CONFIDENCE", 1.01)
    lines = engine.read(prepare(encode, text_image()))
    assert len(lines) == len(LINES)
    assert all(line.illegible and line.text == "" for line in lines)


@pytest.mark.invariant
def test_rapidocr_never_drops_lines_on_its_own(engine: OcrEngine) -> None:
    # Principle 3: RapidOCR's own score filter would drop low-score lines
    # silently; it must stay disabled so Sugo marks them illegible instead.
    # Low-score lines are hard to provoke with this robust model, so the
    # setting is checked directly.
    assert engine._engine.text_score == 0.0


def test_boxes_outside_the_image_are_clamped() -> None:
    line = ocr_engine._to_line([[-5, -5], [120, -5], [120, 30], [-5, 30]], "x", 0.99, 100, 50)
    assert (line.bbox.x0, line.bbox.y0, line.bbox.x1) == (0.0, 0.0, 1.0)


class TestModelIntegrity:
    def test_bundled_models_match_their_pinned_hashes(self) -> None:
        for model in bundled_models():
            model.verify()

    def test_altered_model_is_refused_before_loading(self, tmp_path: Path) -> None:
        detection, recognition = bundled_models()
        altered = tmp_path / "det.onnx"
        shutil.copyfile(detection.path, altered)
        with altered.open("r+b") as file:
            file.seek(1000)
            file.write(b"\x00\x01\x02")
        with pytest.raises(ModelIntegrityError):
            OcrEngine(OcrModel(altered, detection.sha256), recognition)


@pytest.mark.invariant
def test_ocr_never_touches_the_network(encode: Encode, monkeypatch: pytest.MonkeyPatch) -> None:
    # Principle 1 and ADR-036: loading and running OCR must not download anything.
    def forbidden(*_args: Any, **_kwargs: Any) -> NoReturn:
        raise AssertionError("network used")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    engine = OcrEngine(*bundled_models())
    assert engine.read(prepare(encode, text_image()))


@pytest.mark.invariant
def test_ocr_logs_no_paths_at_default_level(
    encode: Encode, capfd: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
) -> None:
    # Principle 11: RapidOCR logs model paths at INFO unless silenced.
    engine = OcrEngine(*bundled_models())
    engine.read(prepare(encode, text_image()))
    captured = capfd.readouterr()
    output = captured.out + captured.err + caplog.text
    assert "PP-OCRv6" not in output
    assert str(Path.home()) not in output
