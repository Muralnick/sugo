"""Tests for the CLI's parts: error mapping, clipboard reading and doctor checks."""

from io import BytesIO

import pytest
from PIL import Image

from sugo.core.pipeline import InputUnsupportedError
from sugo.extractors.image.loader import ImageTooLargeError
from sugo.extractors.image.ocr_engine import ModelIntegrityError
from sugo.extractors.pymupdf.extract import PdfEncryptedError, PdfTooLargeError
from sugo.ports.cli import clipboard, doctor
from sugo.ports.cli.errors import CliError, ExitCode, from_exception, unreadable


@pytest.mark.parametrize(
    ("error", "code", "exit_code"),
    [
        (InputUnsupportedError("x"), "INPUT_UNSUPPORTED", ExitCode.ERROR),
        (PdfEncryptedError("x"), "PDF_ENCRYPTED", ExitCode.ERROR),
        (PdfTooLargeError("x"), "PDF_TOO_LARGE", ExitCode.SECURITY),
        (ImageTooLargeError("x"), "IMAGE_TOO_LARGE", ExitCode.SECURITY),
        (ModelIntegrityError("x"), "INTEGRITY_CHECK_FAILED", ExitCode.SECURITY),
    ],
)
def test_known_errors_get_a_code_and_exit_code(
    error: Exception, code: str, exit_code: ExitCode
) -> None:
    mapped = from_exception(error)
    assert mapped is not None
    assert (mapped.code, mapped.exit_code, mapped.message) == (code, exit_code, "x")


def test_unreadable_input_does_not_repeat_the_path() -> None:
    mapped = unreadable(FileNotFoundError(2, "No such file or directory", "secret/name.pdf"))
    assert (mapped.code, mapped.message) == ("FILE_UNREADABLE", "No such file or directory")


def test_os_errors_are_not_mapped_outside_reading() -> None:
    # A broken stdout pipe must not be reported as an unreadable input.
    assert from_exception(BrokenPipeError(32, "Broken pipe")) is None


def test_other_errors_are_not_mapped() -> None:
    assert from_exception(RuntimeError("bug")) is None


# --- clipboard ----------------------------------------------------------------


def test_clipboard_image_is_reencoded_as_png(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("PIL.ImageGrab.grabclipboard", lambda: Image.new("RGB", (8, 4)))
    assert clipboard.read_clipboard_image().startswith(b"\x89PNG\r\n\x1a\n")


@pytest.mark.parametrize("content", [None, ["C:/copied/file.pdf"]])
def test_clipboard_without_an_image_is_refused(
    monkeypatch: pytest.MonkeyPatch, content: object
) -> None:
    monkeypatch.setattr("PIL.ImageGrab.grabclipboard", lambda: content)
    with pytest.raises(CliError) as caught:
        clipboard.read_clipboard_image()
    assert caught.value.code == "CLIPBOARD_NO_IMAGE"


def test_unreadable_clipboard_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    def unavailable() -> None:
        raise NotImplementedError("wl-paste or xclip is required")

    monkeypatch.setattr("PIL.ImageGrab.grabclipboard", unavailable)
    with pytest.raises(CliError) as caught:
        clipboard.read_clipboard_image()
    assert caught.value.code == "CLIPBOARD_UNAVAILABLE"


def test_huge_clipboard_image_is_refused_before_encoding(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(clipboard, "MAX_IMAGE_PIXELS", 31)
    monkeypatch.setattr("PIL.ImageGrab.grabclipboard", lambda: Image.new("RGB", (8, 4)))
    with pytest.raises(ImageTooLargeError):
        clipboard.read_clipboard_image()


def test_cmyk_clipboard_image_becomes_rgb_png(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("PIL.ImageGrab.grabclipboard", lambda: Image.new("CMYK", (8, 4)))
    with Image.open(BytesIO(clipboard.read_clipboard_image())) as image:
        assert (image.format, image.mode) == ("PNG", "RGB")


def test_clipboard_bomb_is_refused_as_too_large(monkeypatch: pytest.MonkeyPatch) -> None:
    def bomb() -> None:
        raise Image.DecompressionBombError("too many pixels")

    monkeypatch.setattr("PIL.ImageGrab.grabclipboard", bomb)
    with pytest.raises(ImageTooLargeError):
        clipboard.read_clipboard_image()


# --- doctor -------------------------------------------------------------------


def test_old_pymupdf_is_a_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(doctor, "version", lambda name: "1.28.2")
    check = doctor._pymupdf()
    assert check.status is doctor.Status.WARNING
    assert "trust" in check.detail
    monkeypatch.setattr(doctor, "version", lambda name: "2.0.1")
    assert doctor._pymupdf().status is doctor.Status.OK


def test_altered_model_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def altered() -> doctor.Check:
        raise ModelIntegrityError("model x failed its SHA-256 check")

    check = doctor._guarded("ocr models", altered)
    assert check.status is doctor.Status.ERROR
    assert "SHA-256" in check.detail


def test_clipboard_check_on_linux_without_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setattr("shutil.which", lambda tool: None)
    assert doctor._clipboard().status is doctor.Status.WARNING
    monkeypatch.setattr("shutil.which", lambda tool: f"/usr/bin/{tool}")
    assert doctor._clipboard().detail == "wl-paste, xclip"
