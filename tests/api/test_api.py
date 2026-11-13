"""Tests for the public Python API (ADR-067): names, results, errors, cache, import cost."""

import dataclasses
import inspect
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path

import pymupdf
import pytest

import sugo
from sugo.api import Result, SugoError

PUBLIC = {"Chunk", "Result", "SugoError", "__version__", "convert"}
SECRET_XML = b"<config><user>u</user><password>p</password></config>"


def pdf(*paragraphs: str) -> bytes:
    document = pymupdf.open()
    page = document.new_page()
    for row, text in enumerate(paragraphs):
        page.insert_text((72, 100 + row * 40), text, fontsize=11)
    return document.tobytes()


@pytest.fixture
def report(tmp_path: Path) -> Path:
    path = tmp_path / "report.pdf"
    path.write_bytes(pdf("Quarterly results improved.", "Costs fell by a tenth."))
    return path


def test_exactly_the_documented_names_are_public() -> None:
    assert set(sugo.__all__) == PUBLIC
    for name in PUBLIC:
        assert getattr(sugo, name) is not None
    assert set(dir(sugo)) >= PUBLIC


def test_convert_signature_is_the_contract() -> None:
    parameters = inspect.signature(sugo.convert).parameters
    assert [(p.name, p.kind, p.default) for p in parameters.values()] == [
        ("source", inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.empty),
        ("name", inspect.Parameter.KEYWORD_ONLY, None),
        ("chunks", inspect.Parameter.KEYWORD_ONLY, False),
        ("max_tokens", inspect.Parameter.KEYWORD_ONLY, None),
        ("receipt", inspect.Parameter.KEYWORD_ONLY, False),
        ("cache", inspect.Parameter.KEYWORD_ONLY, "ephemeral"),
        ("level", inspect.Parameter.KEYWORD_ONLY, "lite"),
    ]


def test_version_is_the_installed_one() -> None:
    assert sugo.__version__ == version("sugo-cli")


def test_unknown_name_is_an_attribute_error() -> None:
    with pytest.raises(AttributeError):
        _ = sugo.Engine  # type: ignore[attr-defined]


def test_importing_sugo_loads_neither_the_pipeline_nor_pydantic() -> None:
    probe = "import sys, sugo; print(sorted({'sugo.core.pipeline', 'pydantic'} & set(sys.modules)))"
    out = subprocess.run(  # noqa: S603 - fixed arguments, no shell
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True
    ).stdout
    assert out.strip() == "[]"


def test_a_path_gives_markdown_chunks_and_facts(report: Path) -> None:
    result = sugo.convert(report, chunks=True)
    assert "Quarterly results improved." in result.markdown
    assert result.chunks
    assert all(isinstance(c, sugo.Chunk) for c in result.chunks)
    assert result.source == report.as_posix() == result.chunks[0].source
    assert (result.kind, result.pages, result.failed_pages, result.partial) == ("pdf", 1, (), False)
    assert result.tokens > 0
    assert result.secret_blocks == 0
    assert result.receipt is None
    assert result.sugo_version == sugo.__version__


def test_a_string_path_is_accepted(report: Path) -> None:
    assert sugo.convert(str(report)).markdown == sugo.convert(report).markdown


def test_no_chunks_unless_asked(report: Path) -> None:
    assert sugo.convert(report).chunks == ()


def test_bytes_take_their_name_and_identity_from_name() -> None:
    data = pdf("A note.")
    assert sugo.convert(data).source is None
    named = sugo.convert(data, name="notes/a.pdf", chunks=True)
    again = sugo.convert(pdf("A note."), name="notes/a.pdf", chunks=True)
    assert named.source == "notes/a.pdf"
    assert [c.id for c in named.chunks] == [c.id for c in again.chunks]


def test_max_tokens_sizes_the_chunks(report: Path) -> None:
    assert all(c.tokens <= 32 for c in sugo.convert(report, chunks=True, max_tokens=32).chunks)


def test_receipt_is_json_when_asked(report: Path) -> None:
    receipt = sugo.convert(report, receipt=True).receipt
    assert receipt is not None
    assert receipt["source_sha256"] == sugo.convert(report).source_sha256


def test_result_cannot_be_changed(report: Path) -> None:
    result = sugo.convert(report)
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.markdown = ""  # type: ignore[misc]
    with pytest.raises(TypeError):
        result.removed["x"] = 1  # type: ignore[index]


def test_a_document_with_credentials_is_returned_and_counted() -> None:
    result = sugo.convert(SECRET_XML)
    assert result.secret_blocks == 1


def test_a_refused_file_raises_sugo_error_with_the_cli_code() -> None:
    with pytest.raises(SugoError) as caught:
        sugo.convert(b"neither a PDF nor an image")
    error = caught.value
    assert error.code == "INPUT_UNSUPPORTED"
    assert error.message == str(error)
    assert error.hint
    assert error.__cause__ is not None
    assert dict(error.details) == {}


def test_invalid_settings_raise_config_invalid(
    report: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SUGO_LANGUAGES", "xx")
    with pytest.raises(SugoError) as caught:
        sugo.convert(report)
    assert caught.value.code == "CONFIG_INVALID"


def test_a_missing_path_raises_os_error(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        sugo.convert(tmp_path / "missing.pdf")


@pytest.mark.parametrize(
    ("arguments", "error"),
    [
        ({"source": 12}, TypeError),
        ({"source": b"x", "max_tokens": 64}, ValueError),
        ({"source": b"x", "chunks": True, "max_tokens": 1}, ValueError),
        ({"source": b"x", "chunks": True, "max_tokens": 1_000_000}, ValueError),
        ({"source": b"x", "cache": "disk"}, ValueError),
        ({"source": b"x", "level": "normal"}, ValueError),
    ],
)
def test_wrong_arguments_fail_before_any_work(arguments: dict[str, object], error: type) -> None:
    with pytest.raises(error):
        sugo.convert(**arguments)  # type: ignore[arg-type]


def test_ephemeral_cache_leaves_nothing_in_the_user_cache(
    report: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    user_cache = tmp_path / "user-cache"
    monkeypatch.setenv("SUGO_CACHE_DIR", str(user_cache))
    sugo.convert(report)
    assert not user_cache.exists() or not any(user_cache.iterdir())
    sugo.convert(report, cache="user")
    assert (user_cache / "cache.db").is_file()


def test_convert_prints_nothing(report: Path, capfd: pytest.CaptureFixture[str]) -> None:
    sugo.convert(report, chunks=True)
    assert capfd.readouterr() == ("", "")


def test_result_type_is_exported_unchanged() -> None:
    assert sugo.Result is Result
    assert sugo.SugoError is SugoError
