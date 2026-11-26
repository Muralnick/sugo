"""Tests for merging one-platform image archives into one index (ADR-075)."""

import hashlib
import importlib.util
import io
import json
import tarfile
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = "application/vnd.oci.image.manifest.v1+json"
INDEX = "application/vnd.oci.image.index.v1+json"


def load() -> ModuleType:
    path = ROOT / "scripts" / "release" / "merge_oci_images.py"
    spec = importlib.util.spec_from_file_location("merge_oci_images", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


merge_oci_images = load()


class Archive:
    """A small OCI layout written as a tar file, shaped like BuildKit's output."""

    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}

    def add(self, content: Any) -> dict[str, Any]:
        data = content if isinstance(content, bytes) else json.dumps(content).encode()
        digest = f"sha256:{hashlib.sha256(data).hexdigest()}"
        self.blobs[digest] = data
        return {"digest": digest, "size": len(data)}

    def image(
        self, arch: str, *, attest: bool = True, platform: bool = True, label: str = ""
    ) -> dict[str, Any]:
        config = self.add({"os": "linux", "architecture": arch})
        layer = self.add(f"layer for {arch}".encode())
        manifest = self.add({"schemaVersion": 2, "config": config, "layers": [layer]})
        image = {"mediaType": MANIFEST, **manifest}
        if platform:
            image["platform"] = {"os": "linux", "architecture": label or arch}
        descriptors = [image]
        if attest:
            sbom = self.add(b'{"spdxVersion":"SPDX-2.3"}')
            attestation = self.add({"schemaVersion": 2, "config": config, "layers": [sbom]})
            descriptors.append(
                {
                    "mediaType": MANIFEST,
                    **attestation,
                    "platform": {"os": "unknown", "architecture": "unknown"},
                    "annotations": {
                        "vnd.docker.reference.type": "attestation-manifest",
                        "vnd.docker.reference.digest": manifest["digest"],
                    },
                }
            )
        return {"mediaType": INDEX, **self.add({"schemaVersion": 2, "manifests": descriptors})}

    def write(self, path: Path, top: list[dict[str, Any]]) -> Path:
        files = {
            "oci-layout": b'{"imageLayoutVersion":"1.0.0"}',
            "index.json": json.dumps({"schemaVersion": 2, "manifests": top}).encode(),
        }
        for digest, data in self.blobs.items():
            files[f"blobs/sha256/{digest.removeprefix('sha256:')}"] = data
        with tarfile.open(path, "w") as tar:
            for name, data in files.items():
                info = tarfile.TarInfo(name)
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
        return path


def archive(tmp_path: Path, arch: str, *, attest: bool = True, platform: bool = True) -> Path:
    built = Archive()
    image = built.image(arch, attest=attest, platform=platform)
    return built.write(tmp_path / f"{arch}.tar", [image])


def merged_index(out: Path) -> dict[str, Any]:
    top = json.loads((out / "index.json").read_text(encoding="utf-8"))
    (descriptor,) = top["manifests"]
    assert descriptor["annotations"]["org.opencontainers.image.ref.name"] == "sugo"
    blob = out / "blobs" / "sha256" / descriptor["digest"].removeprefix("sha256:")
    data = blob.read_bytes()
    assert descriptor["size"] == len(data)
    return dict(json.loads(data))


def test_two_architectures_become_one_index(tmp_path: Path) -> None:
    out = tmp_path / "out"
    archives = {"amd64": archive(tmp_path, "amd64"), "arm64": archive(tmp_path, "arm64")}
    digest = merge_oci_images.merge(archives, out)
    blob = out / "blobs" / "sha256" / digest.removeprefix("sha256:")
    # The printed digest is the index's own: what the registry will serve.
    assert hashlib.sha256(blob.read_bytes()).hexdigest() == digest.removeprefix("sha256:")
    index = merged_index(out)
    images = [m for m in index["manifests"] if "annotations" not in m]
    attestations = [m for m in index["manifests"] if "annotations" in m]
    assert {m["platform"]["architecture"] for m in images} == {"amd64", "arm64"}
    assert {a["annotations"]["vnd.docker.reference.digest"] for a in attestations} == {
        m["digest"] for m in images
    }
    # Every manifest the index names, and everything they name, is in the layout.
    for descriptor in index["manifests"]:
        manifest = json.loads(
            (out / "blobs" / "sha256" / descriptor["digest"].removeprefix("sha256:")).read_bytes()
        )
        for child in [manifest["config"], *manifest["layers"]]:
            assert (out / "blobs" / "sha256" / child["digest"].removeprefix("sha256:")).is_file()
    assert (out / "oci-layout").is_file()


def test_an_image_without_platform_is_read_from_its_config(tmp_path: Path) -> None:
    out = tmp_path / "out"
    archives = {
        "amd64": archive(tmp_path, "amd64", platform=False),
        "arm64": archive(tmp_path, "arm64"),
    }
    merge_oci_images.merge(archives, out)
    assert len(merged_index(out)["manifests"]) == 4  # two images, two SBOMs


def test_an_image_without_its_sbom_is_refused(tmp_path: Path) -> None:
    archives = {"amd64": archive(tmp_path, "amd64", attest=False)}
    with pytest.raises(merge_oci_images.MergeError, match="0 attestations"):
        merge_oci_images.merge(archives, tmp_path / "out")


def test_an_archive_for_another_architecture_is_refused(tmp_path: Path) -> None:
    archives = {"amd64": archive(tmp_path, "amd64"), "arm64": archive(tmp_path, "s390x")}
    with pytest.raises(merge_oci_images.MergeError, match="not linux/arm64"):
        merge_oci_images.merge(archives, tmp_path / "out")


def test_a_platform_label_that_contradicts_the_config_is_refused(tmp_path: Path) -> None:
    built = Archive()
    path = built.write(tmp_path / "liar.tar", [built.image("amd64", label="arm64")])
    with pytest.raises(merge_oci_images.MergeError, match="labelled linux/arm64"):
        merge_oci_images.merge({"arm64": path}, tmp_path / "out")


def test_an_archive_with_two_images_is_refused(tmp_path: Path) -> None:
    built = Archive()
    path = built.write(tmp_path / "both.tar", [built.image("amd64"), built.image("arm64")])
    with pytest.raises(merge_oci_images.MergeError, match="2 images"):
        merge_oci_images.merge({"amd64": path}, tmp_path / "out")


def test_a_blob_that_does_not_match_its_name_is_refused(tmp_path: Path) -> None:
    built = Archive()
    top = [built.image("amd64")]
    layer = next(d for d, data in built.blobs.items() if data.startswith(b"layer"))
    built.blobs[layer] = b"tampered"
    with pytest.raises(merge_oci_images.MergeError, match="does not match"):
        merge_oci_images.merge({"amd64": built.write(tmp_path / "bad.tar", top)}, tmp_path / "out")


def test_an_attestation_for_another_image_is_refused(tmp_path: Path) -> None:
    built = Archive()
    top = built.image("amd64")
    nested = json.loads(built.blobs[top["digest"]])
    nested["manifests"][1]["annotations"]["vnd.docker.reference.digest"] = "sha256:" + "0" * 64
    path = built.write(tmp_path / "bad.tar", [{"mediaType": INDEX, **built.add(nested)}])
    with pytest.raises(merge_oci_images.MergeError, match="another image"):
        merge_oci_images.merge({"amd64": path}, tmp_path / "out")


def test_a_file_that_is_not_an_oci_layout_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "plain.tar"
    with tarfile.open(path, "w") as tar:
        info = tarfile.TarInfo("readme.txt")
        tar.addfile(info, io.BytesIO(b""))
    with pytest.raises(merge_oci_images.MergeError, match="not an OCI layout"):
        merge_oci_images.merge({"amd64": path}, tmp_path / "out")
