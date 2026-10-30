"""A document must not drive the terminal that shows its text (security review, ADR-048)."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from sugo.ports.cli import app as cli
from sugo.storage.paths import CACHE_DIR_ENV

# A font whose encoding maps "A" to ESC and "C" to BEL: PyMuPDF returns the
# real control characters, as an attacker's PDF would.
_CONTENT = b"BT /F1 24 Tf 72 700 Td (Quarterly report A[2JA[1;31mFAKE PROMPT A]0;pwnedC) Tj ET"
_OBJECTS = [
    b"<< /Type /Catalog /Pages 2 0 R >>",
    b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]"
    b" /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
    b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica"
    b" /Encoding << /Differences [65 /uni001B 67 /uni0007] >> >>",
    b"<< /Length %d >>\nstream\n" % len(_CONTENT) + _CONTENT + b"\nendstream",
]


def escape_pdf() -> bytes:
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(_OBJECTS, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(_OBJECTS) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer << /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(_OBJECTS) + 1,
        xref,
    )
    return bytes(out)


def controls(text: str) -> set[str]:
    return {
        char
        for char in text
        if char not in "\t\n" and (ord(char) < 0x20 or 0x7F <= ord(char) < 0xA0)
    }


@pytest.mark.parametrize("args", [[], ["--json"], ["--chunks"]])
def test_escape_sequences_in_a_pdf_never_reach_the_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, args: list[str]
) -> None:
    monkeypatch.setenv(CACHE_DIR_ENV, str(tmp_path / "cache"))
    path = tmp_path / "report.pdf"
    path.write_bytes(escape_pdf())
    result = CliRunner().invoke(cli.app, [str(path), *args])
    assert result.exit_code == 0
    assert controls(result.stdout) == set()
    # JSON would escape C0 controls as \u001b: decode it, so they count too.
    lines = [json.loads(line) for line in result.stdout.splitlines()] if args else []
    decoded = "".join(strings(lines)) if args else result.stdout
    assert "Quarterly report" in decoded
    assert controls(decoded) == set()


def strings(value: object) -> list[str]:
    """Every string inside a decoded JSON value."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for item in value.values() for s in strings(item)]
    if isinstance(value, list):
        return [s for item in value for s in strings(item)]
    return []
