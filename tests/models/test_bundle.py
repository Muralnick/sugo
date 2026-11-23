"""Tests for offline bundles: writing them, and refusing any bundle Sugo did not write (ADR-070)."""

import json
import zipfile
from pathlib import Path
from types import MappingProxyType

import pytest
from tests.models.test_models import BODY, CARD, CONFIG, TWO, model_file
from typer.testing import CliRunner

from sugo.models import bundle as bundle_module
from sugo.models import registry, store
from sugo.models.bundle import MANIFEST_NAME, entry_name, install_bundle, write_bundle
from sugo.models.errors import BundleInvalidError, ModelMissingError
from sugo.ports.cli import app as cli
from sugo.ports.errors import ExitCode
from sugo.storage.paths import CACHE_DIR_ENV

ENTRY = entry_name(CARD, CARD.files[0])


@pytest.fixture(autouse=True)
def test_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(CACHE_DIR_ENV, str(tmp_path / "cache"))
    monkeypatch.setattr(registry, "REGISTRY", MappingProxyType({CARD.id: CARD, TWO.id: TWO}))
    monkeypatch.setattr(bundle_module, "REGISTRY", registry.REGISTRY)


def install_model() -> None:
    store.prepare(CARD)
    model_file().write_bytes(BODY)


def manifest(**changes: object) -> str:
    value: dict[str, object] = {
        "format": 1,
        "sugo_version": "0.0.0",
        "models": [{"id": CARD.id, "files": [{"name": ENTRY, "size": CARD.size}]}],
    }
    value.update(changes)
    return json.dumps(value)


def hand_made(
    path: Path, entries: dict[str, bytes | str], compression: int = zipfile.ZIP_STORED
) -> Path:
    with zipfile.ZipFile(path, "w", compression=compression) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return path


def test_a_written_bundle_installs_on_another_machine(tmp_path: Path) -> None:
    install_model()
    target = tmp_path / "models.zip"
    assert write_bundle([CARD, CARD], target, sugo_version="0.0.0") == target.stat().st_size
    with zipfile.ZipFile(target) as archive:
        assert sorted(archive.namelist()) == sorted([MANIFEST_NAME, ENTRY])
    store.remove(CARD)
    assert install_bundle(target) == [CARD]
    assert store.verify(store.find(CARD)) == store.model_dir(CARD)  # type: ignore[arg-type]
    assert install_bundle(target) == [CARD]  # already installed: nothing to do


def test_a_model_that_is_not_installed_cannot_be_bundled(tmp_path: Path) -> None:
    with pytest.raises(ModelMissingError):
        write_bundle([CARD], tmp_path / "models.zip", sugo_version="0.0.0")
    assert not (tmp_path / "models.zip").exists()
    assert not (tmp_path / "models.zip.part").exists()


@pytest.mark.parametrize(
    ("entries", "reason"),
    [
        ({MANIFEST_NAME: manifest(), ENTRY: BODY[:-1] + b"!"}, "SHA-256"),
        ({MANIFEST_NAME: manifest(), ENTRY: BODY + b"!"}, "wrong size"),
        ({MANIFEST_NAME: manifest(), ENTRY: BODY, "../../evil.py": b"x"}, "not a model"),
        ({MANIFEST_NAME: manifest(), "ocr-test/other.onnx": BODY}, "not a model"),
        ({ENTRY: BODY}, "manifest is missing"),
        ({MANIFEST_NAME: manifest(format=2), ENTRY: BODY}, "unknown format"),
        ({MANIFEST_NAME: manifest(models=[]), ENTRY: BODY}, "does not match"),
        ({MANIFEST_NAME: "not json", ENTRY: BODY}, "not JSON"),
        ({MANIFEST_NAME: manifest(models=[])}, "no model"),
    ],
)
def test_hostile_bundles_install_nothing(
    tmp_path: Path, entries: dict[str, bytes | str], reason: str
) -> None:
    path = hand_made(tmp_path / "bad.zip", entries)
    with pytest.raises(BundleInvalidError, match=reason):
        install_bundle(path)
    assert store.find(CARD) is None
    assert not list((tmp_path / "cache").rglob("*.part"))
    assert not (tmp_path / "evil.py").exists()


def test_an_altered_bundle_is_refused_even_when_the_model_is_installed(tmp_path: Path) -> None:
    # The installed copy is valid, so nothing would be written; the bundle is
    # still refused whole (ADR-070), and the installed copy is left as it was.
    install_model()
    path = hand_made(tmp_path / "bad.zip", {MANIFEST_NAME: manifest(), ENTRY: BODY[:-1] + b"!"})
    with pytest.raises(BundleInvalidError, match="SHA-256"):
        install_bundle(path)
    assert model_file().read_bytes() == BODY
    assert not list((tmp_path / "cache").rglob("*.part"))


@pytest.mark.parametrize("installed", [False, True])
def test_a_damaged_deflate_stream_is_a_bundle_error(tmp_path: Path, installed: bool) -> None:
    # Checked whether or not the model is already installed (#123 review).
    if installed:
        install_model()
    path = hand_made(
        tmp_path / "bad.zip",
        {MANIFEST_NAME: manifest(), ENTRY: BODY},
        compression=zipfile.ZIP_DEFLATED,
    )
    data = bytearray(path.read_bytes())
    with zipfile.ZipFile(path) as archive:
        info = archive.getinfo(ENTRY)
    # The compressed bytes start after the local header, its name and extra field.
    start = info.header_offset + 30 + len(ENTRY.encode()) + len(info.extra)
    data[start : start + 8] = b"\xff" * 8
    path.write_bytes(bytes(data))
    with pytest.raises(BundleInvalidError, match=r"damaged|SHA-256"):
        install_bundle(path)
    assert not list((tmp_path / "cache").rglob("*.part"))


def test_a_compressed_bomb_is_refused_by_its_declared_size(tmp_path: Path) -> None:
    bomb = b"\0" * (len(BODY) * 50)
    path = hand_made(
        tmp_path / "bomb.zip",
        {MANIFEST_NAME: manifest(), ENTRY: bomb},
        compression=zipfile.ZIP_DEFLATED,
    )
    with pytest.raises(BundleInvalidError, match="wrong size"):
        install_bundle(path)


def test_an_entry_lying_about_its_size_is_cut_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The central directory says the right size; the data is longer.
    path = hand_made(tmp_path / "liar.zip", {MANIFEST_NAME: manifest(), ENTRY: BODY * 2})
    real = zipfile.ZipFile.infolist

    def lying(self: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
        infos = real(self)
        for info in infos:
            if info.filename == ENTRY:
                info.file_size = CARD.size
        return infos

    monkeypatch.setattr(zipfile.ZipFile, "infolist", lying)
    with pytest.raises(BundleInvalidError):
        install_bundle(path)
    assert store.find(CARD) is None


def test_files_that_are_not_zips_or_too_large(tmp_path: Path) -> None:
    (tmp_path / "x.zip").write_bytes(b"not a zip")
    with pytest.raises(BundleInvalidError, match="not a ZIP"):
        install_bundle(tmp_path / "x.zip")
    with (tmp_path / "huge.zip").open("wb") as file:
        file.truncate(CARD.size + 2 * 1024 * 1024)
    with pytest.raises(BundleInvalidError, match="larger"):
        install_bundle(tmp_path / "huge.zip")


def test_encrypted_entries_are_refused(tmp_path: Path) -> None:
    path = hand_made(tmp_path / "enc.zip", {MANIFEST_NAME: manifest(), ENTRY: BODY})
    data = bytearray(path.read_bytes())
    # Set the "encrypted" flag in the central directory entry of the model.
    central = data.rfind(b"PK\x01\x02")
    data[central + 8] |= 0x1
    path.write_bytes(bytes(data))
    with pytest.raises(BundleInvalidError, match="encrypted"):
        install_bundle(path)


class TestCommands:
    def test_bundle_and_install(self, tmp_path: Path) -> None:
        install_model()
        target = tmp_path / "out.zip"
        result = CliRunner().invoke(cli.app, ["models", "bundle", "ocr-test", "-o", str(target)])
        assert result.exit_code == 0, result.stderr
        assert "Wrote" in result.stderr
        store.remove(CARD)
        result = CliRunner().invoke(cli.app, ["models", "install", str(target)])
        assert result.exit_code == 0, result.stderr
        assert "Installed and verified ocr-test." in result.stderr

    def test_bundling_a_missing_model(self, tmp_path: Path) -> None:
        result = CliRunner().invoke(
            cli.app, ["models", "bundle", "ocr-test", "-o", str(tmp_path / "o.zip")]
        )
        assert result.exit_code == ExitCode.MISSING
        assert "MODEL_MISSING" in result.stderr
        assert "sugo models pull ocr-test" in result.stderr

    def test_installing_a_hostile_bundle(self, tmp_path: Path) -> None:
        path = hand_made(tmp_path / "bad.zip", {MANIFEST_NAME: manifest(), "../x": b"1"})
        result = CliRunner().invoke(cli.app, ["models", "install", str(path)])
        assert result.exit_code == ExitCode.SECURITY
        assert "BUNDLE_INVALID" in result.stderr

    def test_installing_a_missing_file(self, tmp_path: Path) -> None:
        result = CliRunner().invoke(cli.app, ["models", "install", str(tmp_path / "none.zip")])
        assert result.exit_code == ExitCode.ERROR
        assert "FILE_UNREADABLE" in result.stderr


def test_a_model_of_several_files_travels_whole(tmp_path: Path) -> None:
    store.prepare(TWO)
    model_file(TWO, 0).write_bytes(BODY)
    model_file(TWO, 1).write_bytes(CONFIG)
    target = tmp_path / "two.zip"
    write_bundle([TWO], target, sugo_version="0.0.0")
    with zipfile.ZipFile(target) as archive:
        assert sorted(archive.namelist()) == sorted(
            [
                MANIFEST_NAME,
                "docling/org--layout/model.safetensors",
                "docling/org--layout/config.json",
            ]
        )
    store.remove(TWO)
    assert install_bundle(target) == [TWO]
    assert model_file(TWO, 1).read_bytes() == CONFIG


def test_a_model_missing_one_of_its_files_is_refused(tmp_path: Path) -> None:
    two = json.dumps({"format": 1, "models": [{"id": TWO.id}]})
    path = hand_made(
        tmp_path / "half.zip", {MANIFEST_NAME: two, "docling/org--layout/model.safetensors": BODY}
    )
    with pytest.raises(BundleInvalidError, match="incomplete"):
        install_bundle(path)
    assert store.find(TWO) is None
