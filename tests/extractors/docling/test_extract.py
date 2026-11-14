"""Tests for the Docling worker and its driver (ADR-071 §3), without Docling.

A fake worker script stands in for Docling's process; the real worker's
``run`` is tested with ``_convert`` replaced, as Docling is not installed in
the development environment.
"""

import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest

from sugo.core.models import Block, BlockType, Page, PageOrigin
from sugo.extractors.docling import worker
from sugo.extractors.docling.extract import (
    NormalFailedError,
    NormalLevelMissingError,
    docling_installed,
    extract_docling,
)
from sugo.extractors.docling.protocol import Opened, PageRead, Refused, write_message

PAGE = Page(
    index=0,
    width=600,
    height=800,
    origin=PageOrigin.NATIVE,
    blocks=(Block(id="p0-d0", type=BlockType.PARAGRAPH, text="hi", origin_engine="docling"),),
)


def fake_worker(tmp_path: Path, body: str) -> list[str]:
    """A worker command running ``body``, which may call ``send(message)``."""
    script = tmp_path / "fake_worker.py"
    script.write_text(
        textwrap.dedent(
            """
            import sys
            from sugo.core.models import Block, BlockType, Page, PageOrigin
            from sugo.extractors.docling.protocol import Opened, PageRead, Refused, write_message
            from sugo.extractors.worker import write_frame
            sys.stdin.buffer.read()
            out = sys.stdout.buffer
            def send(message):
                write_message(out, message)
            block = Block(id="p0-d0", type=BlockType.PARAGRAPH, text="hi", origin_engine="docling")
            page = Page(index=0, width=600, height=800, origin=PageOrigin.NATIVE, blocks=(block,))
            """
        )
        + textwrap.dedent(body)
    )
    return [sys.executable, str(script)]


def run(command: list[str], **limits: float) -> list[Page]:
    return extract_docling(
        b"%PDF-1.7", kind="pdf", page_count=1, artifacts=Path("models"), worker=command, **limits
    )


def test_pages_come_back_validated(tmp_path: Path) -> None:
    pages = run(fake_worker(tmp_path, "send(Opened(pages=1))\nsend(PageRead(page=page))\n"))
    assert pages == [PAGE]


@pytest.mark.parametrize(
    ("body", "error"),
    [
        ('send(Refused(code="LEVEL_MISSING", message="no"))\n', NormalLevelMissingError),
        ('send(Refused(code="NORMAL_FAILED", message="no"))\n', NormalFailedError),
        ("write_frame(out, b'not json')\n", NormalFailedError),
        ("send(Opened(pages=2))\nsend(PageRead(page=page))\n", NormalFailedError),  # one missing
        ("send(PageRead(page=page))\n", NormalFailedError),  # no Opened first
        ("raise SystemExit(3)\n", NormalFailedError),  # crash
    ],
)
def test_every_failure_stops_the_conversion(
    tmp_path: Path, body: str, error: type[Exception]
) -> None:
    with pytest.raises(error):
        run(fake_worker(tmp_path, body))


def test_a_stalled_worker_is_killed(tmp_path: Path) -> None:
    command = fake_worker(tmp_path, "import time\ntime.sleep(30)\n")
    with pytest.raises(NormalFailedError):
        run(command, load_timeout=0.5, page_timeout=0.1)


def test_docling_is_not_in_the_development_environment() -> None:
    assert docling_installed() is False


class TestWorkerRun:
    def test_pages_of_the_docling_export(self, monkeypatch: pytest.MonkeyPatch) -> None:
        exported: dict[str, Any] = {
            "body": {"children": [{"$ref": "#/texts/0"}]},
            "texts": [{"self_ref": "#/texts/0", "label": "text", "text": "hi"}],
            "pages": {"1": {"size": {"width": 600, "height": 800}}},
        }
        monkeypatch.setattr(worker, "_convert", lambda data, kind, artifacts: exported)
        messages = list(worker.run(b"x", "pdf", Path("m")))
        assert messages[0] == Opened(pages=1)
        assert isinstance(messages[1], PageRead)
        assert messages[1].page.blocks[0].text == "hi"

    def test_without_docling_it_says_so(self) -> None:
        # The development environment has no Docling: the real import fails.
        assert list(worker.run(b"x", "pdf", Path("m"))) == [
            Refused(code="LEVEL_MISSING", message="Docling is not installed")
        ]

    def test_a_docling_failure_names_only_its_type(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fail(*_: object) -> dict[str, Any]:
            raise ValueError("text from the document")

        monkeypatch.setattr(worker, "_convert", fail)
        (message,) = worker.run(b"x", "pdf", Path("m"))
        assert message == Refused(code="NORMAL_FAILED", message="Docling failed: ValueError")

    def test_the_network_is_shut_before_docling_loads(self) -> None:
        assert worker._OFFLINE_ENVIRONMENT["HF_HUB_OFFLINE"] == "1"
        assert worker._OFFLINE_ENVIRONMENT["TRANSFORMERS_OFFLINE"] == "1"

    def test_unknown_kinds_are_refused(self) -> None:
        with pytest.raises(ValueError, match="unknown kind"):
            list(worker.run(b"x", "docx", Path("m")))

    def test_messages_are_frames(self, tmp_path: Path) -> None:
        path = tmp_path / "out"
        with path.open("wb") as out:
            write_message(out, Opened(pages=1))
        assert path.read_bytes()[4:] == b'{"kind":"opened","pages":1}'
