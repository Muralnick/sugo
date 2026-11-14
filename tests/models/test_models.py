"""Tests for the model registry, the store and the download of registry models (ADR-070)."""

import hashlib
import os
import sys
import urllib.parse
from pathlib import Path

import pytest
from tests.internal.test_net import FakeResponse, FakeServer

from sugo.models import download as download_module
from sugo.models import store
from sugo.models.download import pull
from sugo.models.errors import (
    DownloadFailedError,
    ModelInvalidError,
    OfflineModeError,
    UnknownModelError,
)
from sugo.models.registry import GROUPS, REGISTRY, ModelCard, ModelFile, Source, card, cards
from sugo.storage.paths import CACHE_DIR_ENV

BODY = b"onnx model bytes " * 1000
CARD = ModelCard(
    id="ocr-test",
    task="ocr-recognition",
    languages=("xx",),
    level="lite",
    format="onnx",
    folder="ocr-test",
    files=(
        ModelFile(
            path="test.onnx",
            size=len(BODY),
            sha256=hashlib.sha256(BODY).hexdigest(),
            sources=(
                Source(
                    "GitHub",
                    "https://github.com/Muralnick/sugo/releases/download/models-1/test.onnx",
                ),
                Source("ModelScope", "https://www.modelscope.cn/models/test.onnx"),
            ),
        ),
    ),
    licence="Apache-2.0",
    notice="A test model.",
    revision="test",
)
CONFIG = b'{"labels": 17}'
# Two files in nested folders, as Docling's models are.
TWO = ModelCard(
    id="layout-test",
    task="layout",
    languages=(),
    level="normal",
    format="safetensors",
    folder="docling",
    files=tuple(
        ModelFile(
            path=f"org--layout/{name}",
            size=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            sources=(
                Source("Hugging Face", f"https://huggingface.co/org/layout/resolve/abc/{name}"),
            ),
        )
        for name, data in (("model.safetensors", BODY), ("config.json", CONFIG))
    ),
    licence="Apache-2.0",
    notice="A two-file test model.",
    revision="org/layout@abc",
)


def model_file(model: ModelCard = CARD, index: int = 0) -> Path:
    return store.file_path(model, model.files[index])


@pytest.fixture(autouse=True)
def cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    folder = tmp_path / "cache"
    monkeypatch.setenv(CACHE_DIR_ENV, str(folder))
    return folder


class ByHost:
    """A fake opener answering per host: a server, or an HTTP status for failure."""

    def __init__(self, **hosts: FakeServer) -> None:
        self.hosts = hosts
        self.asked: list[str] = []

    def __call__(self, request: object) -> FakeResponse:
        url = request.full_url  # type: ignore[attr-defined]
        host = urllib.parse.urlsplit(url).hostname or ""
        self.asked.append(host)
        return self.hosts[host.split(".")[-2]](request)  # type: ignore[arg-type]


class TestRegistry:
    def test_every_model_is_pinned_safe_and_fetched_over_https(self) -> None:
        from sugo.models.registry import ALLOWED_SUFFIXES

        for model in REGISTRY.values():
            assert model.format in ("onnx", "safetensors", "gguf")
            assert any(f.path.endswith("." + model.format) for f in model.files)
            for file in model.files:
                assert file.path.endswith(ALLOWED_SUFFIXES)
                assert ".." not in file.path.split("/")
                assert len(file.sha256) == 64
                assert int(file.sha256, 16) >= 0
                assert file.size > 0
                assert file.sources
                assert all(s.url.startswith("https://") for s in file.sources)
                assert all(s.url.endswith(file.name) for s in file.sources)
            if model.format != "onnx":
                # Pinned to a commit, never a branch.
                assert all("/resolve/main/" not in s.url for f in model.files for s in f.sources)

    def test_korean_is_the_rapidocr_file(self) -> None:
        korean = card("ocr-korean")
        assert korean.size == 13_488_748
        assert korean.files[0].sha256.startswith("cd6e2ea5")
        assert korean.sources == ("GitHub", "ModelScope")

    def test_normal_stands_for_both_docling_models(self) -> None:
        assert [c.id for c in cards("normal")] == list(GROUPS["normal"])
        assert {c.folder for c in cards("normal")} == {"docling"}
        assert card("layout-docling").size == 171_658_996 + 3268 + 444
        assert cards("ocr-korean") == (card("ocr-korean"),)

    def test_an_unknown_model_is_refused(self) -> None:
        with pytest.raises(UnknownModelError):
            card("ocr-klingon")


class TestPull:
    def test_downloads_from_the_first_source(self) -> None:
        opener = ByHost(github=FakeServer(BODY))
        path = pull(CARD, offline=False, opener=opener)
        assert path == store.model_dir(CARD)
        assert model_file().read_bytes() == BODY
        assert opener.asked == ["github.com"]
        assert store.find(CARD) is not None

    def test_falls_back_to_the_next_source(self) -> None:
        opener = ByHost(github=FakeServer(status=404), modelscope=FakeServer(BODY))
        pull(CARD, offline=False, opener=opener)
        assert opener.asked == ["github.com", "www.modelscope.cn"]

    def test_a_source_with_another_file_is_skipped(self) -> None:
        opener = ByHost(github=FakeServer(b"x" * len(BODY)), modelscope=FakeServer(BODY))
        pull(CARD, offline=False, opener=opener)
        assert model_file().read_bytes() == BODY

    def test_every_source_failing_names_each_reason(self) -> None:
        opener = ByHost(github=FakeServer(status=404), modelscope=FakeServer(status=503))
        with pytest.raises(DownloadFailedError) as caught:
            pull(CARD, offline=False, opener=opener)
        assert caught.value.failures == [
            ("GitHub", "server answered 404"),
            ("ModelScope", "server answered 503"),
        ]
        assert store.find(CARD) is None

    def test_offline_mode_downloads_nothing(self) -> None:
        opener = ByHost(github=FakeServer(BODY))
        with pytest.raises(OfflineModeError):
            pull(CARD, offline=True, opener=opener)
        assert opener.asked == []

    def test_an_installed_model_is_not_downloaded_again(self) -> None:
        pull(CARD, offline=False, opener=ByHost(github=FakeServer(BODY)))
        opener = ByHost(github=FakeServer(BODY))
        pull(CARD, offline=True, opener=opener)
        assert opener.asked == []

    def test_a_damaged_model_is_replaced(self) -> None:
        root = pull(CARD, offline=False, opener=ByHost(github=FakeServer(BODY)))
        model_file().write_bytes(b"y" * len(BODY))
        with pytest.raises(ModelInvalidError):
            store.verify(store.Installed(CARD, root))
        pull(CARD, offline=False, opener=ByHost(github=FakeServer(BODY)))
        assert store.verify(store.Installed(CARD, root)) == root

    def test_a_model_of_several_files_in_nested_folders(self) -> None:
        sent: list[int] = []

        class Both(FakeServer):
            def __call__(self, request: object) -> FakeResponse:
                url = request.full_url  # type: ignore[attr-defined]
                self.body = CONFIG if url.endswith("config.json") else BODY
                return super().__call__(request)  # type: ignore[arg-type]

        pull(TWO, offline=False, opener=ByHost(huggingface=Both()), progress=sent.append)
        assert model_file(TWO, 0).read_bytes() == BODY
        assert model_file(TWO, 1).read_bytes() == CONFIG
        assert sent[-1] == TWO.size
        assert store.find(TWO) is not None
        assert store.remove(TWO) == TWO.size
        assert not store.model_dir(TWO).exists()

    def test_is_offline_also_reads_the_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert not download_module.is_offline(False)
        assert download_module.is_offline(True)
        monkeypatch.setenv("SUGO_OFFLINE", "yes")
        assert download_module.is_offline(False)


class TestStore:
    def test_find_needs_a_plain_file_of_the_right_size(self) -> None:
        assert store.find(CARD) is None
        store.prepare(CARD)
        model_file().write_bytes(BODY[:10])
        assert store.find(CARD) is None
        model_file().write_bytes(BODY)
        assert store.find(CARD) is not None

    def test_remove_deletes_only_known_files(self) -> None:
        pull(CARD, offline=False, opener=ByHost(github=FakeServer(BODY)))
        assert store.remove(CARD) == len(BODY)
        assert not store.model_dir(CARD).exists()
        assert store.remove(CARD) == 0

    def test_remove_keeps_a_folder_with_other_files(self) -> None:
        pull(CARD, offline=False, opener=ByHost(github=FakeServer(BODY)))
        (store.model_dir(CARD) / "mine.txt").write_text("keep")
        store.remove(CARD)
        assert (store.model_dir(CARD) / "mine.txt").read_text() == "keep"
        assert store.find(CARD) is None

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX symbolic links")
    def test_a_linked_model_folder_is_refused(self, tmp_path: Path) -> None:
        from sugo.storage.paths import StorageDirError

        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        (elsewhere / "test.onnx").write_bytes(BODY)
        store.models_dir().mkdir(parents=True)
        os.symlink(elsewhere, store.model_dir(CARD))
        with pytest.raises(StorageDirError):
            store.remove(CARD)
        assert (elsewhere / "test.onnx").exists()
