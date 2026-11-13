"""Tests for SugoLoader (ADR-068): documents, ids, metadata, failures, credentials."""

import ast
import logging
import socket
from collections.abc import Callable
from pathlib import Path

import pytest
import sugo
from langchain_core.embeddings import DeterministicFakeEmbedding
from langchain_core.vectorstores import InMemoryVectorStore

from langchain_sugo import Skipped, SugoLoader
from loader_helpers import NetworkBlockedError, make_pdf

Write = Callable[[str, bytes], Path]
SECRET_XML = b"<config><user>u</user><password>p</password></config>"
SOURCE = Path(__file__).parents[1] / "src" / "langchain_sugo"
PUBLIC_SUGO = {"convert", "Result", "Chunk", "SugoError", "__version__"}


@pytest.fixture
def report(write: Write) -> Path:
    return write("report.pdf", make_pdf("Quarterly results improved.", "Costs fell by a tenth."))


def test_one_document_per_chunk_with_the_chunk_id(report: Path) -> None:
    documents = SugoLoader(report).load()
    chunks = sugo.convert(report, chunks=True).chunks
    assert [d.id for d in documents] == [c.id for c in chunks]
    assert [d.page_content for d in documents] == [c.text for c in chunks]
    assert "Quarterly results improved." in documents[0].page_content


def test_ids_are_the_same_on_every_load(report: Path) -> None:
    assert [d.id for d in SugoLoader(report).load()] == [d.id for d in SugoLoader(report).load()]


def test_metadata_holds_only_scalars(report: Path) -> None:
    (document, *_) = SugoLoader(report).load()
    metadata = document.metadata
    assert all(isinstance(value, str | int | bool) for value in metadata.values())
    assert metadata["source"] == report.as_posix()
    assert metadata["chunk_id"] == document.id
    assert metadata["document_id"].startswith("d_")
    assert (metadata["page_start"], metadata["page_end"]) == (1, 1)
    assert metadata["partial"] is False
    assert metadata["tokens"] > 0
    assert metadata["sugo_version"] == sugo.__version__


def test_documents_go_into_a_vector_store_by_id(report: Path) -> None:
    documents = SugoLoader(report).load()
    store = InMemoryVectorStore(DeterministicFakeEmbedding(size=8))
    assert store.add_documents(documents) == [d.id for d in documents]


def test_document_mode_gives_one_document_per_file(report: Path) -> None:
    (document,) = SugoLoader(report, mode="document").load()
    result = sugo.convert(report)
    assert document.id == result.document_id == document.metadata["document_id"]
    assert document.page_content == result.markdown
    assert "chunk_id" not in document.metadata


def test_several_files_load_in_order(report: Path, write: Write) -> None:
    other = write("other.pdf", make_pdf("A second file."))
    documents = SugoLoader([report, other], mode="document").load()
    assert [d.metadata["source"] for d in documents] == [report.as_posix(), other.as_posix()]


def test_a_file_with_credentials_is_skipped_by_default(write: Write) -> None:
    secret = write("settings.xml", SECRET_XML)
    loader = SugoLoader(secret)
    assert loader.load() == []
    assert loader.skipped == [Skipped(path=secret.as_posix(), code="CONTENT_EXCLUDED")]


def test_a_file_with_credentials_can_be_included_or_stop_the_load(write: Write) -> None:
    secret = write("settings.xml", SECRET_XML)
    assert SugoLoader(secret, mode="document", on_secret="include").load()
    with pytest.raises(sugo.SugoError) as caught:
        SugoLoader(secret, on_secret="raise").load()
    assert caught.value.code == "CONTENT_EXCLUDED"


def test_a_refused_file_stops_the_load_by_default(write: Write) -> None:
    bad = write("notes.pdf", b"not really a PDF")
    with pytest.raises(sugo.SugoError):
        SugoLoader(bad).load()


def test_refused_and_missing_files_can_be_skipped(
    report: Path, write: Write, tmp_path: Path
) -> None:
    bad = write("notes.pdf", b"not really a PDF")
    missing = tmp_path / "missing.pdf"
    loader = SugoLoader([bad, missing, report], on_error="skip")
    documents = loader.load()
    assert documents
    assert [s.path for s in loader.skipped] == [bad.as_posix(), missing.as_posix()]
    assert loader.skipped[1].code == "FILE_UNREADABLE"


def test_skipped_files_are_not_named_in_the_log(
    write: Write, caplog: pytest.LogCaptureFixture
) -> None:
    secret = write("payroll-settings.xml", SECRET_XML)
    with caplog.at_level(logging.WARNING):
        SugoLoader(secret).load()
    assert caplog.messages == ["a file was left out: CONTENT_EXCLUDED"]


@pytest.mark.parametrize(
    "options",
    [
        {"mode": "pages"},
        {"on_error": "ignore"},
        {"on_secret": "drop"},
        {"mode": "document", "max_tokens": 64},
    ],
)
def test_wrong_options_fail_at_once(report: Path, options: dict[str, object]) -> None:
    with pytest.raises(ValueError, match=r"must be one of|needs"):
        SugoLoader(report, **options)  # type: ignore[arg-type]


def test_network_is_blocked_in_these_tests() -> None:
    with pytest.raises(NetworkBlockedError):
        socket.create_connection(("example.org", 443))


def test_the_loader_uses_only_the_public_sugo_api() -> None:
    for path in SOURCE.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith("sugo"), (path.name, node.module)
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name == "sugo" or not alias.name.startswith("sugo"), path.name
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == "sugo"
            ):
                assert node.attr in PUBLIC_SUGO, (path.name, node.attr)
