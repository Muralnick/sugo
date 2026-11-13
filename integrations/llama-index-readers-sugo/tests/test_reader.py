"""Tests for SugoReader (ADR-068): documents, ids, metadata, failures, credentials."""

import ast
import logging
import socket
from collections.abc import Callable
from pathlib import Path

import pytest
import sugo
from llama_index.core import SimpleDirectoryReader, VectorStoreIndex
from llama_index.core.embeddings import MockEmbedding
from llama_index.core.schema import MetadataMode

from llama_index.readers.sugo import Skipped, SugoReader
from loader_helpers import NetworkBlockedError, make_pdf

Write = Callable[[str, bytes], Path]
SECRET_XML = b"<config><user>u</user><password>p</password></config>"
SOURCE = Path(__file__).parents[1] / "src" / "llama_index" / "readers" / "sugo"
PUBLIC_SUGO = {"convert", "Result", "Chunk", "SugoError", "__version__"}


@pytest.fixture
def report(write: Write) -> Path:
    return write("report.pdf", make_pdf("Quarterly results improved.", "Costs fell by a tenth."))


def test_one_document_per_chunk_with_the_chunk_id(report: Path) -> None:
    documents = SugoReader().load_data(report)
    chunks = sugo.convert(report, chunks=True).chunks
    assert [d.id_ for d in documents] == [c.id for c in chunks]
    assert [d.text for d in documents] == [c.text for c in chunks]


def test_ids_are_the_same_on_every_load(report: Path) -> None:
    first = [d.id_ for d in SugoReader().load_data(report)]
    assert first == [d.id_ for d in SugoReader().load_data(report)]


def test_metadata_holds_only_scalars(report: Path) -> None:
    (document, *_) = SugoReader().load_data(report)
    metadata = document.metadata
    assert all(isinstance(value, str | int | bool) for value in metadata.values())
    assert metadata["source"] == report.as_posix()
    assert metadata["chunk_id"] == document.id_
    assert (metadata["page_start"], metadata["page_end"]) == (1, 1)
    assert metadata["sugo_version"] == sugo.__version__


def test_ids_and_digests_stay_out_of_the_embedded_and_llm_text(report: Path) -> None:
    (document, *_) = SugoReader().load_data(report)
    for mode in (MetadataMode.EMBED, MetadataMode.LLM):
        text = document.get_content(metadata_mode=mode)
        assert document.id_ not in text
        assert document.metadata["source_sha256"] not in text
        assert "page_start: 1" in text


def test_documents_go_into_an_index_by_id(report: Path) -> None:
    documents = SugoReader().load_data(report)
    index = VectorStoreIndex(documents, embed_model=MockEmbedding(embed_dim=8))
    assert set(index.docstore.docs) == {d.id_ for d in documents}


def test_works_as_a_file_extractor_of_simple_directory_reader(report: Path) -> None:
    reader = SimpleDirectoryReader(
        input_files=[str(report)], file_extractor={".pdf": SugoReader(mode="document")}
    )
    (document,) = reader.load_data()
    assert "Quarterly results improved." in document.text
    assert document.metadata["file_name"] == "report.pdf"  # the directory reader's own key
    assert document.metadata["document_id"] == document.id_


def test_document_mode_gives_one_document_per_file(report: Path) -> None:
    (document,) = SugoReader(mode="document").load_data(report)
    result = sugo.convert(report)
    assert document.id_ == result.document_id
    assert document.text == result.markdown


def test_extra_info_is_kept_and_sugo_keys_win(report: Path) -> None:
    extra = {"team": "finance", "source": "elsewhere"}
    (document,) = SugoReader(mode="document").load_data(report, extra_info=extra)
    assert document.metadata["team"] == "finance"
    assert document.metadata["source"] == report.as_posix()


def test_other_file_systems_are_refused(report: Path) -> None:
    with pytest.raises(ValueError, match="local files only"):
        SugoReader().load_data(report, fs=object())


def test_a_file_with_credentials_is_skipped_by_default(write: Write) -> None:
    secret = write("settings.xml", SECRET_XML)
    reader = SugoReader()
    assert reader.load_data(secret) == []
    assert reader.skipped == [Skipped(path=secret.as_posix(), code="CONTENT_EXCLUDED")]


def test_a_file_with_credentials_can_be_included_or_stop_the_load(write: Write) -> None:
    secret = write("settings.xml", SECRET_XML)
    assert SugoReader(mode="document", on_secret="include").load_data(secret)
    with pytest.raises(sugo.SugoError) as caught:
        SugoReader(on_secret="raise").load_data(secret)
    assert caught.value.code == "CONTENT_EXCLUDED"


def test_refused_and_missing_files_can_be_skipped(
    report: Path, write: Write, tmp_path: Path
) -> None:
    bad = write("notes.pdf", b"not really a PDF")
    missing = tmp_path / "missing.pdf"
    with pytest.raises(sugo.SugoError):
        SugoReader().load_data(bad)
    reader = SugoReader(on_error="skip")
    assert reader.load_data([bad, missing, report])
    assert [s.path for s in reader.skipped] == [bad.as_posix(), missing.as_posix()]
    assert reader.skipped[1].code == "FILE_UNREADABLE"


def test_skipped_files_are_not_named_in_the_log(
    write: Write, caplog: pytest.LogCaptureFixture
) -> None:
    secret = write("payroll-settings.xml", SECRET_XML)
    with caplog.at_level(logging.WARNING):
        SugoReader().load_data(secret)
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
def test_wrong_options_fail_at_once(options: dict[str, object]) -> None:
    with pytest.raises(ValueError, match=r"must be one of|needs"):
        SugoReader(**options)  # type: ignore[arg-type]


def test_network_is_blocked_in_these_tests() -> None:
    with pytest.raises(NetworkBlockedError):
        socket.create_connection(("example.org", 443))


def test_the_reader_uses_only_the_public_sugo_api() -> None:
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
