"""Korean: the OCR model chosen by language, and what happens without it (ADR-069 §6, ADR-070 §5-7).

CI has no Korean model: it cannot download one. These tests check the
routing, the missing-model error and the cache keys; ``SUGO_TEST_KOREAN_MODEL``
(the path of a downloaded ``ocr-korean`` file) also runs a real Korean read.
"""

import hashlib
import os
import shutil
from io import BytesIO
from pathlib import Path

import pymupdf
import pytest
from PIL import Image, ImageDraw
from typer.testing import CliRunner

import sugo
from sugo.api import SugoError
from sugo.core import pipeline
from sugo.core.pipeline import convert, korean_ocr_engine, ocr_for
from sugo.extractors.image.ocr_engine import KOREAN_ENGINE_NAME
from sugo.extractors.pymupdf.extract import default_ocr_engine
from sugo.models import store
from sugo.models.errors import ModelInvalidError, ModelMissingError
from sugo.models.registry import card
from sugo.ports.cli import app as cli
from sugo.ports.cli import uninstall
from sugo.ports.errors import ExitCode, from_exception
from sugo.storage.paths import CACHE_DIR_ENV

KOREAN = card("ocr-korean")
REAL_MODEL = os.environ.get("SUGO_TEST_KOREAN_MODEL")


@pytest.fixture(autouse=True)
def cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    folder = tmp_path / "cache"
    monkeypatch.setenv(CACHE_DIR_ENV, str(folder))
    return folder


def picture() -> bytes:
    image = Image.new("RGB", (600, 120), "white")
    ImageDraw.Draw(image).text((20, 40), "Meeting at 3 PM", fill="black")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def native_pdf() -> bytes:
    document = pymupdf.open()
    document.new_page().insert_text((72, 100), "Native text needs no OCR.", fontsize=11)
    return document.tobytes()


def test_korean_picks_the_korean_model() -> None:
    assert ocr_for(("ko",)) is korean_ocr_engine
    assert ocr_for(("en", "ko")) is korean_ocr_engine
    assert ocr_for(("en", "ja")) is default_ocr_engine


def test_without_the_model_ocr_stops_with_model_missing() -> None:
    with pytest.raises(ModelMissingError):
        convert(picture(), languages=("en", "ko"))
    assert "Meeting" in convert(picture(), languages=("en",)).markdown


def test_native_pdfs_need_no_model() -> None:
    assert "Native text" in convert(native_pdf(), languages=("ko",)).markdown


def test_a_damaged_model_is_refused() -> None:
    store.prepare(KOREAN)
    with store.file_path(KOREAN, KOREAN.files[0]).open("wb") as file:
        file.truncate(KOREAN.size)
    with pytest.raises(ModelInvalidError):
        korean_ocr_engine()


def test_pages_read_with_the_korean_model_are_cached_apart() -> None:
    plain = pipeline._engine_identity(pipeline.InputKind.PDF)
    korean = pipeline._engine_identity(pipeline.InputKind.PDF, korean=True)
    assert korean == plain + f";ocr={KOREAN_ENGINE_NAME}"


def test_every_port_reports_model_missing() -> None:
    error = from_exception(ModelMissingError("ocr-korean"))
    assert error is not None
    assert error.code == "MODEL_MISSING"
    assert error.exit_code == ExitCode.MISSING
    assert error.hint == "sugo models pull ocr-korean"
    assert error.details == {"model": "ocr-korean", "size_mb": 13}


def test_the_api_and_the_cli_report_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "shot.png"
    path.write_bytes(picture())
    monkeypatch.setenv("SUGO_LANGUAGES", "ko")
    with pytest.raises(SugoError) as caught:
        sugo.convert(path)
    assert caught.value.code == "MODEL_MISSING"
    result = CliRunner().invoke(cli.app, [str(path), "-o", str(tmp_path / "out")])
    assert result.exit_code == ExitCode.MISSING
    assert "MODEL_MISSING" in result.stderr
    assert "sugo models pull ocr-korean" in result.stderr


def test_uninstall_deletes_models_and_cache_clear_keeps_them() -> None:
    store.prepare(KOREAN)
    with store.file_path(KOREAN, KOREAN.files[0]).open("wb") as file:
        file.truncate(KOREAN.size)
    assert uninstall.find().models == (("ocr-korean", KOREAN.size),)
    result = CliRunner().invoke(cli.app, ["cache", "clear"])
    assert result.exit_code == 0
    assert store.find(KOREAN) is not None
    result = CliRunner().invoke(cli.app, ["uninstall", "--yes"])
    assert result.exit_code == 0, result.stderr
    assert "downloaded model: ocr-korean" in result.stderr
    assert store.find(KOREAN) is None
    assert not store.models_dir().exists()


@pytest.mark.skipif(REAL_MODEL is None, reason="set SUGO_TEST_KOREAN_MODEL to a downloaded model")
def test_a_real_korean_screenshot(tmp_path: Path) -> None:
    from PIL import ImageFont

    source = Path(str(REAL_MODEL))
    assert hashlib.sha256(source.read_bytes()).hexdigest() == KOREAN.files[0].sha256
    store.prepare(KOREAN)
    shutil.copyfile(source, store.file_path(KOREAN, KOREAN.files[0]))
    font_path = Path("C:/Windows/Fonts/malgun.ttf")
    if not font_path.exists():
        pytest.skip("no Korean font")
    lines = ["한국어 문서를 변환하는 테스트입니다.", "서울특별시 중구 세종대로 110"]
    image = Image.new("RGB", (900, 160), "white")
    draw = ImageDraw.Draw(image)
    for n, line in enumerate(lines):
        draw.text(
            (30, 25 + 60 * n), line, font=ImageFont.truetype(str(font_path), 30), fill="black"
        )
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    markdown = convert(buffer.getvalue(), languages=("ko",)).markdown
    assert all(line in markdown for line in lines), markdown
