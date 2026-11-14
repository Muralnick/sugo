"""Offline bundles: carry installed models to a machine without internet (ADR-013, ADR-070).

A bundle is a ZIP file holding ``sugo-models.json`` and the model files,
each named ``<id>/<sha256><suffix>``. Writing one needs no network: it copies
installed models, checked first. Installing one needs no network either, and
trusts nothing in the archive:

- only the names the registry knows are accepted, and the archive's names
  are never used as paths, so nothing can be written outside the models
  folder (zip slip);
- each entry must declare the registry's size, and no more bytes than that
  are read (zip bombs); the whole file is capped too;
- every file is extracted to ``.part`` and checked against the registry's
  SHA-256; only when all match do they get their names. A bundle with one
  unknown, altered or encrypted entry is refused whole.

Nothing here touches the network (principle 1).
"""

import hashlib
import json
import os
import zipfile
from collections.abc import Iterable
from pathlib import Path

from sugo.models.errors import BundleInvalidError, ModelInvalidError, ModelMissingError
from sugo.models.registry import REGISTRY, ModelCard
from sugo.models.store import PART_SUFFIX, download_lock, find, model_path, verify

MANIFEST_NAME = "sugo-models.json"
BUNDLE_FORMAT = 1
MAX_MANIFEST_BYTES = 64 * 1024
_CHUNK_BYTES = 1024 * 1024
# Room for the manifest and the ZIP headers around the models.
_OVERHEAD_BYTES = 1024 * 1024


def entry_name(card: ModelCard) -> str:
    """The name of a model's file inside a bundle."""
    return f"{card.id}/{card.sha256}{card.suffix}"


def write_bundle(cards: Iterable[ModelCard], destination: Path, *, sugo_version: str) -> int:
    """Write the installed models to a bundle at ``destination``.

    Returns:
        The size of the bundle in bytes.

    Raises:
        ModelMissingError: If a model is not installed.
        ModelInvalidError: If an installed model fails its SHA-256.
        OSError: If the bundle cannot be written; nothing is left behind.
    """
    chosen = list(dict.fromkeys(cards))
    paths = []
    for card in chosen:
        installed = find(card)
        if installed is None:
            raise ModelMissingError(card.id)
        paths.append(verify(installed))
    manifest = {
        "format": BUNDLE_FORMAT,
        "sugo_version": sugo_version,
        "models": [
            {"id": card.id, "sha256": card.sha256, "size": card.size, "file": entry_name(card)}
            for card in chosen
        ],
    }
    part = destination.with_name(destination.name + PART_SUFFIX)
    try:
        # Stored, not compressed: model weights hardly compress, and reading
        # them back needs no decompressor.
        with zipfile.ZipFile(part, "w", compression=zipfile.ZIP_STORED) as archive:
            archive.writestr(MANIFEST_NAME, json.dumps(manifest, indent=2) + "\n")
            for card, path in zip(chosen, paths, strict=True):
                archive.write(path, entry_name(card))
        os.replace(part, destination)
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    return destination.stat().st_size


def install_bundle(path: Path) -> list[ModelCard]:
    """Install every model of the bundle at ``path``, after checking all of them.

    Returns:
        The models installed (already installed ones included).

    Raises:
        BundleInvalidError: If the file is not a valid bundle, or an entry is
            unknown, encrypted, of the wrong size or fails its SHA-256.
            Nothing is installed then.
        OSError: If the bundle cannot be read or a model cannot be written.
    """
    if path.stat().st_size > _max_bundle_bytes():
        raise BundleInvalidError("bundle is larger than every known model together")
    try:
        with zipfile.ZipFile(path) as archive:
            cards = _checked_entries(archive)
            return _extract(archive, cards)
    except zipfile.BadZipFile:
        raise BundleInvalidError("not a ZIP file") from None


def _max_bundle_bytes() -> int:
    return sum(card.size for card in REGISTRY.values()) + _OVERHEAD_BYTES


def _checked_entries(archive: zipfile.ZipFile) -> list[ModelCard]:
    """The models the archive holds, after checking every entry against the registry."""
    known = {entry_name(card): card for card in REGISTRY.values()}
    infos = archive.infolist()
    names = [info.filename for info in infos]
    if len(names) != len(set(names)):
        raise BundleInvalidError("an entry appears twice")
    cards: list[ModelCard] = []
    manifest_info = None
    for info in infos:
        if info.flag_bits & 0x1:
            raise BundleInvalidError("an entry is encrypted")
        if info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
            raise BundleInvalidError("an entry uses an unsupported compression")
        if info.filename == MANIFEST_NAME:
            manifest_info = info
            continue
        card = known.get(info.filename)
        if card is None:
            raise BundleInvalidError("an entry is not a model Sugo knows")
        if info.file_size != card.size:
            raise BundleInvalidError("an entry has the wrong size")
        cards.append(card)
    if manifest_info is None or manifest_info.file_size > MAX_MANIFEST_BYTES:
        raise BundleInvalidError("the manifest is missing or too large")
    manifest = _manifest(archive, manifest_info)
    listed = manifest.get("models")
    if manifest.get("format") != BUNDLE_FORMAT or not isinstance(listed, list):
        raise BundleInvalidError("the manifest is of an unknown format")
    ids = sorted(str(item.get("id")) for item in listed if isinstance(item, dict))
    if len(ids) != len(listed) or ids != sorted(card.id for card in cards):
        raise BundleInvalidError("the manifest does not match the files")
    if not cards:
        raise BundleInvalidError("the bundle holds no model")
    return cards


def _manifest(archive: zipfile.ZipFile, info: zipfile.ZipInfo) -> dict[str, object]:
    with archive.open(info) as file:
        data = file.read(MAX_MANIFEST_BYTES + 1)
    try:
        manifest = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise BundleInvalidError("the manifest is not JSON") from None
    if not isinstance(manifest, dict):
        raise BundleInvalidError("the manifest is not a JSON object")
    return manifest


def _extract(archive: zipfile.ZipFile, cards: list[ModelCard]) -> list[ModelCard]:
    """Extract every model to ``.part``, check all, then give them their names."""
    parts: list[tuple[Path, Path]] = []
    try:
        for card in cards:
            installed = find(card)
            if installed is not None:
                try:
                    verify(installed)
                    continue
                except ModelInvalidError:
                    pass  # A damaged copy is replaced by the bundle's.
            with download_lock(card):
                part = _extract_one(archive, card)
            parts.append((part, model_path(card)))
        for part, final in parts:
            os.replace(part, final)
    finally:
        for part, _final in parts:
            part.unlink(missing_ok=True)
    return cards


def _extract_one(archive: zipfile.ZipFile, card: ModelCard) -> Path:
    part = model_path(card).with_name(model_path(card).name + PART_SUFFIX)
    # A leftover, or a planted link, is removed rather than written through.
    part.unlink(missing_ok=True)
    digest = hashlib.sha256()
    written = 0
    try:
        with archive.open(entry_name(card)) as source, part.open("wb") as target:
            while chunk := source.read(_CHUNK_BYTES):
                written += len(chunk)
                if written > card.size:
                    raise BundleInvalidError("an entry is larger than it declares")
                digest.update(chunk)
                target.write(chunk)
    except zipfile.BadZipFile:
        part.unlink(missing_ok=True)
        raise BundleInvalidError("an entry is damaged") from None
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    if written != card.size or digest.hexdigest() != card.sha256:
        part.unlink(missing_ok=True)
        raise BundleInvalidError("an entry does not match its SHA-256")
    return part
