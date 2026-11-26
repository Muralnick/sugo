"""Merge one-platform OCI image archives into one multi-platform image (ADR-075).

The release builds the container image once per architecture, each on its own
runner, as an OCI archive (``docker buildx build --output type=oci``). Each
archive holds the image and its SBOM attestation, and is the exact file the
MCP probe ran. This script puts the archives' images side by side in one OCI
image index, as an OCI layout folder that ``skopeo copy --all
--preserve-digests`` then pushes unchanged: the digest it prints is the one
the registry will serve, and the one the provenance attestation signs.

Every blob's SHA-256 is checked against its name while it is moved into the
output. An archive must hold exactly one Linux image, for the architecture
given with it, and its image configuration must say the same. Standard
library only.

Usage (inside the release workflow):
    python3 scripts/release/merge_oci_images.py <out-dir> <arch>=<archive>...

Prints ``digest=sha256:...`` for ``$GITHUB_OUTPUT``.
"""

import hashlib
import json
import os
import re
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any

OCI_INDEX = "application/vnd.oci.image.index.v1+json"
INDEXES = {OCI_INDEX, "application/vnd.docker.distribution.manifest.list.v2+json"}
# BuildKit marks its attestation manifests with these annotations.
REFERENCE_TYPE = "vnd.docker.reference.type"
REFERENCE_DIGEST = "vnd.docker.reference.digest"
ATTESTATION = "attestation-manifest"
# The name skopeo uses to find the image in the layout: oci:<out-dir>:sugo.
REF_NAME = "sugo"
_CHUNK = 1 << 20
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")

Descriptor = dict[str, Any]


class MergeError(ValueError):
    """An archive is not a one-platform image, or the archives clash."""


def _blob(layout: Path, digest: str) -> Path:
    if _DIGEST.fullmatch(digest) is None:
        raise MergeError(f"unsupported digest {digest!r}")
    path = layout / "blobs" / "sha256" / digest.removeprefix("sha256:")
    if not path.is_file():
        raise MergeError(f"missing blob {digest}")
    return path


def _read_json(layout: Path, digest: str) -> Any:
    return json.loads(_blob(layout, digest).read_bytes())


def _descriptors(layout: Path) -> list[Descriptor]:
    """The archive's manifests, with nested indexes opened one level."""
    found: list[Descriptor] = []
    for descriptor in json.loads((layout / "index.json").read_text(encoding="utf-8"))["manifests"]:
        if descriptor["mediaType"] in INDEXES:
            found.extend(_read_json(layout, descriptor["digest"])["manifests"])
        else:
            found.append(descriptor)
    return found


def _is_attestation(descriptor: Descriptor) -> bool:
    return bool(descriptor.get("annotations", {}).get(REFERENCE_TYPE) == ATTESTATION)


def _platform(layout: Path, descriptor: Descriptor) -> tuple[str, str]:
    """The image's (os, architecture), from its configuration.

    A descriptor's ``platform`` field, when present, must agree with it: a
    mislabeled image would be served to machines it cannot run on.
    """
    manifest = _read_json(layout, descriptor["digest"])
    config = _read_json(layout, manifest["config"]["digest"])
    platform = (str(config["os"]), str(config["architecture"]))
    label = descriptor.get("platform")
    if label is not None and (label["os"], label["architecture"]) != platform:
        raise MergeError(f"image labelled {label['os']}/{label['architecture']} is {platform}")
    return platform


def _move_blobs(source: Path, target: Path) -> None:
    """Move every blob, refusing one whose content does not match its name."""
    for path in sorted((source / "blobs" / "sha256").iterdir()):
        digest = hashlib.sha256()
        with path.open("rb") as file:
            while chunk := file.read(_CHUNK):
                digest.update(chunk)
        if digest.hexdigest() != path.name:
            raise MergeError(f"blob sha256:{path.name} does not match its content")
        destination = target / "blobs" / "sha256" / path.name
        if not destination.exists():
            os.replace(path, destination)


def _extract(archive: Path, into: Path) -> Path:
    with tarfile.open(archive) as tar:
        tar.extractall(into, filter="data")
    if not (into / "oci-layout").is_file():
        raise MergeError(f"{archive.name} is not an OCI layout archive")
    return into


def merge(archives: dict[str, Path], out_dir: Path) -> str:
    """Merge ``{architecture: archive}`` into ``out_dir``; return the index digest."""
    if not archives:
        raise MergeError("no archives given")
    (out_dir / "blobs" / "sha256").mkdir(parents=True)
    manifests: list[Descriptor] = []
    # Extracted next to the output, so blobs move into it without a copy.
    with tempfile.TemporaryDirectory(dir=out_dir.parent) as work:
        for number, (arch, archive) in enumerate(archives.items()):
            layout = _extract(archive, Path(work) / str(number))
            descriptors = _descriptors(layout)
            images = [d for d in descriptors if not _is_attestation(d)]
            if len(images) != 1:
                raise MergeError(f"{archive.name} holds {len(images)} images, not one")
            platform = _platform(layout, images[0])
            if platform != ("linux", arch):
                raise MergeError(f"{archive.name} is for {'/'.join(platform)}, not linux/{arch}")
            image = images[0]["digest"]
            for descriptor in descriptors:
                if (
                    _is_attestation(descriptor)
                    and descriptor["annotations"].get(REFERENCE_DIGEST) != image
                ):
                    raise MergeError(f"{archive.name} has an attestation for another image")
            _move_blobs(layout, out_dir)
            manifests.extend(descriptors)
    index = json.dumps(
        {"schemaVersion": 2, "mediaType": OCI_INDEX, "manifests": manifests},
        separators=(",", ":"),
    ).encode()
    digest = hashlib.sha256(index).hexdigest()
    (out_dir / "blobs" / "sha256" / digest).write_bytes(index)
    top = {
        "schemaVersion": 2,
        "mediaType": OCI_INDEX,
        "manifests": [
            {
                "mediaType": OCI_INDEX,
                "digest": f"sha256:{digest}",
                "size": len(index),
                "annotations": {"org.opencontainers.image.ref.name": REF_NAME},
            }
        ],
    }
    (out_dir / "index.json").write_text(json.dumps(top), encoding="utf-8")
    (out_dir / "oci-layout").write_text('{"imageLayoutVersion":"1.0.0"}', encoding="utf-8")
    return f"sha256:{digest}"


def main() -> None:
    if len(sys.argv) < 3:  # noqa: PLR2004  (script name, folder, one archive at least)
        sys.exit(__doc__)
    archives: dict[str, Path] = {}
    for arg in sys.argv[2:]:
        arch, sep, path = arg.partition("=")
        if not sep or not arch or arch in archives:
            sys.exit(f"merge_oci_images: expected one <arch>=<archive> per architecture: {arg!r}")
        archives[arch] = Path(path)
    try:
        digest = merge(archives, Path(sys.argv[1]))
    except (MergeError, OSError, KeyError, json.JSONDecodeError, tarfile.TarError) as error:
        sys.exit(f"merge_oci_images: {error}")
    sys.stdout.write(f"digest={digest}\n")


if __name__ == "__main__":
    main()
