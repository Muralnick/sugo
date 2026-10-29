"""Turn failures into the error model and exit codes of the CLI (ADR-022, ADR-048).

Every failure the user can act on becomes a stable code, a message, a hint
and an exit code. The messages come from Sugo's own exceptions, which never
quote document text; the CLI adds the file name the user typed, since the
user needs it and it is shown only on their own terminal, never logged.
"""

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any


class ExitCode(IntEnum):
    """Process exit codes; a public contract (ARCHITECTURE §12)."""

    OK = 0
    ERROR = 1
    USAGE = 2
    PARTIAL = 3
    SECURITY = 4
    MISSING = 5
    INTERRUPTED = 130


# Not frozen: Python sets attributes on exceptions it raises (tracebacks, notes).
@dataclass
class CliError(Exception):
    """A failure in the error model: stable code, message, hint, details."""

    code: str
    message: str
    exit_code: ExitCode
    hint: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def as_json(self) -> dict[str, Any]:
        """The error as the JSON object every port uses."""
        return {
            "code": self.code,
            "message": self.message,
            "hint": self.hint,
            "details": self.details,
        }


# Codes raised by the extractors and the pipeline, with what the user can do.
# Size limits are part of the security floor (principle 7): exit code 4.
_KNOWN: dict[str, tuple[ExitCode, str | None]] = {
    "INPUT_UNSUPPORTED": (ExitCode.ERROR, "Sugo reads PDF, PNG, JPEG and WEBP files."),
    "IMAGE_UNSUPPORTED": (ExitCode.ERROR, "Save the image as a still PNG, JPEG or WEBP."),
    "IMAGE_INVALID": (ExitCode.ERROR, "The file may be damaged; open it and save it again."),
    "IMAGE_TOO_LARGE": (ExitCode.SECURITY, "Reduce the image size, or split it."),
    "PDF_INVALID": (ExitCode.ERROR, "The file may be damaged; open it and save it again."),
    "PDF_ENCRYPTED": (ExitCode.ERROR, "Save an unprotected copy of the PDF and convert that."),
    "PDF_TOO_LARGE": (ExitCode.SECURITY, "Split the PDF into smaller files."),
    "PDF_UNSUPPORTED": (ExitCode.ERROR, None),
    "PDF_EXTRACTION_FAILED": (ExitCode.ERROR, "Try again; if it fails again, run: sugo doctor"),
}


def level_missing(packages: list[str]) -> CliError:
    """The error for a missing engine level, naming the absent packages."""
    return CliError(
        code="LEVEL_MISSING",
        message="The lite level is not installed.",
        exit_code=ExitCode.MISSING,
        hint='pip install "sugo[lite]"',
        details={"missing": packages},
    )


def from_exception(error: Exception) -> CliError | None:
    """Return the CLI error for an exception Sugo raises on purpose, else None."""
    code = getattr(type(error), "code", None)
    if isinstance(code, str) and code in _KNOWN:
        exit_code, hint = _KNOWN[code]
        return CliError(code=code, message=str(error), exit_code=exit_code, hint=hint)
    # Imported here: the integrity errors live in the lite level's modules.
    from sugo.extractors.image.ocr_engine import ModelIntegrityError
    from sugo.metrics.tokenizer import VocabularyIntegrityError

    if isinstance(error, ModelIntegrityError | VocabularyIntegrityError):
        return CliError(
            code="INTEGRITY_CHECK_FAILED",
            message=str(error),
            exit_code=ExitCode.SECURITY,
            hint="Reinstall Sugo; a bundled file was altered or damaged.",
        )
    return None


def unreadable(error: OSError) -> CliError:
    """The error for an input that cannot be read; only for reading, never for writing."""
    # strerror only: the full message repeats the path, which the CLI shows separately.
    return CliError(
        code="FILE_UNREADABLE",
        message=error.strerror or "the file could not be read",
        exit_code=ExitCode.ERROR,
    )
