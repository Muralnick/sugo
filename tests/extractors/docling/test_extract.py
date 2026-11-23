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
from sugo.extractors.docling import extract, worker
from sugo.extractors.docling.extract import (
    DoclingWorker,
    NormalFailedError,
    NormalLevelMissingError,
    docling_installed,
    extract_docling,
    warm_docling,
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
            from sugo.extractors.worker import read_frame, write_frame
            read_frame(sys.stdin.buffer, 10**9)  # one document (ADR-072 §3)
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


# --- A warm worker (ADR-072) ------------------------------------------------------


def serving_worker(tmp_path: Path, fail_on: int = 0) -> list[str]:
    """A worker that reads documents in turn, like the real one, and names its process.

    Each page's text is "<pid>:<n>:<document>", so tests see which process read
    which document. With ``fail_on``, that document (counted from 1) is refused.
    """
    script = tmp_path / "serving_worker.py"
    script.write_text(
        textwrap.dedent(
            f"""
            import os, sys
            from sugo.core.models import Block, BlockType, Page, PageOrigin
            from sugo.extractors.docling.protocol import Opened, PageRead, Refused, write_message
            from sugo.extractors.worker import read_frame
            out = sys.stdout.buffer
            count = 0
            while (data := read_frame(sys.stdin.buffer, 10**9)) is not None:
                count += 1
                if count == {fail_on}:
                    write_message(out, Refused(code="NORMAL_FAILED", message="no"))
                    continue
                text = f"{{os.getpid()}}:{{count}}:{{data.decode()}}"
                block = Block(
                    id="p0-d0", type=BlockType.PARAGRAPH, text=text, origin_engine="docling"
                )
                page = Page(
                    index=0, width=600, height=800, origin=PageOrigin.NATIVE, blocks=(block,)
                )
                write_message(out, Opened(pages=1))
                write_message(out, PageRead(page=page))
            """
        )
    )
    return [sys.executable, str(script)]


def read_text(docling: DoclingWorker, document: str) -> tuple[str, int, str]:
    pages = docling.read(document.encode(), kind="pdf", page_count=1, artifacts=Path("models"))
    pid, count, text = (pages[0].blocks[0].text or "").split(":")
    return pid, int(count), text


class TestWarmWorker:
    def test_documents_go_through_one_process_in_turn(self, tmp_path: Path) -> None:
        docling = DoclingWorker(worker=serving_worker(tmp_path), idle_s=None)
        try:
            first, second = read_text(docling, "a"), read_text(docling, "b")
        finally:
            docling.close()
        assert first[0] == second[0]
        assert (first[1:], second[1:]) == ((1, "a"), (2, "b"))
        assert docling.started == 1

    def test_the_worker_is_replaced_after_n_documents(self, tmp_path: Path) -> None:
        docling = DoclingWorker(worker=serving_worker(tmp_path), recycle_after=2, idle_s=None)
        try:
            pids = [read_text(docling, name)[0] for name in "abcde"]
        finally:
            docling.close()
        assert docling.started == 3
        assert pids[0] == pids[1] != pids[2] == pids[3] != pids[4]

    def test_the_worker_is_never_reused_after_a_failure(self, tmp_path: Path) -> None:
        docling = DoclingWorker(worker=serving_worker(tmp_path, fail_on=2), idle_s=None)
        try:
            before = read_text(docling, "a")
            with pytest.raises(NormalFailedError):
                read_text(docling, "b")
            after = read_text(docling, "c")
        finally:
            docling.close()
        assert before[0] != after[0]
        assert after[1:] == (1, "c")  # a fresh process: its first document
        assert docling.started == 2

    def test_an_idle_worker_stops_and_starts_again_on_demand(self, tmp_path: Path) -> None:
        import time

        docling = DoclingWorker(worker=serving_worker(tmp_path), idle_s=0.2)
        try:
            first = read_text(docling, "a")
            deadline = time.monotonic() + 5
            while docling._process is not None and time.monotonic() < deadline:
                time.sleep(0.05)
            assert docling._process is None
            second = read_text(docling, "b")
        finally:
            docling.close()
        assert first[0] != second[0]
        assert docling.started == 2

    def test_a_read_after_close_keeps_nothing_running(self, tmp_path: Path) -> None:
        # A warm block that ends while a read waits for the worker (security review of #133).
        docling = DoclingWorker(worker=serving_worker(tmp_path), idle_s=60)
        docling.close()
        assert read_text(docling, "a")[1:] == (1, "a")
        assert docling._process is None
        assert docling._timer is None

    def test_a_worker_that_cannot_start_is_a_normal_failure(self, tmp_path: Path) -> None:
        # Popen's OSError is reported like any worker failure (#133 review).
        docling = DoclingWorker(worker=[str(tmp_path / "no-such-program")], idle_s=None)
        with pytest.raises(NormalFailedError):
            docling.read(b"x", kind="pdf", page_count=1, artifacts=Path("m"))
        assert docling._process is None

    def test_other_models_start_another_worker(self, tmp_path: Path) -> None:
        docling = DoclingWorker(worker=serving_worker(tmp_path), idle_s=None)
        try:
            docling.read(b"a", kind="pdf", page_count=1, artifacts=Path("one"))
            docling.read(b"b", kind="pdf", page_count=1, artifacts=Path("two"))
        finally:
            docling.close()
        assert docling.started == 2


class TestWarmBlock:
    def test_only_inside_the_block_and_shared_by_nested_blocks(self) -> None:
        assert extract._shared_worker() is None
        with warm_docling():
            shared = extract._shared_worker()
            assert shared is not None
            with warm_docling():
                assert extract._shared_worker() is shared
            assert extract._shared_worker() is shared
        assert extract._shared_worker() is None

    def test_extract_uses_the_shared_worker_inside_the_block(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        used: list[bytes] = []

        def read(self: DoclingWorker, data: bytes, **_: object) -> list[Page]:
            used.append(data)
            return [PAGE]

        monkeypatch.setattr(DoclingWorker, "read", read)
        with warm_docling():
            shared = extract._shared_worker()
            assert extract_docling(b"x", kind="pdf", page_count=1, artifacts=Path("m")) == [PAGE]
        assert used == [b"x"]
        assert shared is not None


class TestServe:
    def test_documents_are_answered_in_turn_until_the_input_ends(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        import io

        from sugo.extractors.docling.protocol import parse_message
        from sugo.extractors.worker import read_frame, write_frame

        seen: list[bytes] = []

        def convert(data: bytes, kind: str, artifacts: Path) -> dict[str, Any]:
            seen.append(data)
            return {"pages": {"1": {"size": {"width": 600, "height": 800}}}, "texts": []}

        monkeypatch.setattr(worker, "_convert", convert)
        source = io.BytesIO()
        write_frame(source, b"first")
        write_frame(source, b"second")
        source.seek(0)
        out = io.BytesIO()
        worker.serve(source, out, "pdf", tmp_path)
        out.seek(0)
        kinds = []
        while (frame := read_frame(out, 10**9)) is not None:
            kinds.append(type(parse_message(frame)).__name__)
        assert seen == [b"first", b"second"]
        assert kinds == ["Opened", "PageRead", "Opened", "PageRead"]

    def test_a_malformed_frame_ends_the_worker(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        import io

        monkeypatch.setattr(worker, "_convert", lambda *_: pytest.fail("nothing to convert"))
        out = io.BytesIO()
        worker.serve(io.BytesIO(b"\xff\xff\xff\xff"), out, "pdf", tmp_path)
        assert out.getvalue() == b""
