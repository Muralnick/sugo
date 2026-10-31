"""Office Open XML packages: ZIP archives of XML parts, opened with every limit enforced (ADR-054).

Nothing is ever extracted to disk, so entry names with ``..`` or absolute
paths do no harm. Parts are found only through the package's relationships;
external relationships are recorded but never followed. Each part is
decompressed in bounded steps and counted as it comes: the sizes written in
the archive are the attacker's, so they are never trusted.

``word_document`` and ``excel_workbook`` recognise a Word document or an
Excel workbook from the raw bytes, without parsing XML, so Sugo's own process
can route a file before the worker reads it. ``stream`` lets a large part be
parsed piece by piece; a part read twice counts once towards the total.
"""

import io
import posixpath
import zipfile
from dataclasses import dataclass
from typing import IO

from sugo.core.constants import (
    MAX_OFFICE_FILE_BYTES,
    OFFICE_MAX_CONTENT_TYPES_BYTES,
    OFFICE_MAX_ENTRIES,
    OFFICE_MAX_PART_BYTES,
    OFFICE_MAX_PART_ELEMENTS,
    OFFICE_MAX_RATIO,
    OFFICE_MAX_TOTAL_BYTES,
    OFFICE_RATIO_MIN_BYTES,
)
from sugo.extractors.office.xml_reader import Element, Refusal, local_name, parse
from sugo.i18n import N_

ZIP_SIGNATURE = b"PK\x03\x04"
# Compound file (OLE): legacy .doc/.xls/.ppt, or any password-protected Office file.
OLE_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
CONTENT_TYPES = "[Content_Types].xml"
# Main parts of Word documents, templates and their macro-enabled forms.
WORD_MAIN_TYPES = (
    b"application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml",
    b"application/vnd.openxmlformats-officedocument.wordprocessingml.template.main+xml",
    b"application/vnd.ms-word.document.macroEnabled.main+xml",
    b"application/vnd.ms-word.template.macroEnabledTemplate.main+xml",
)
# Main parts of Excel workbooks, templates and their macro-enabled forms; the
# binary .xlsb is not among them.
EXCEL_MAIN_TYPES = (
    b"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml",
    b"application/vnd.openxmlformats-officedocument.spreadsheetml.template.main+xml",
    b"application/vnd.ms-excel.sheet.macroEnabled.main+xml",
    b"application/vnd.ms-excel.template.macroEnabled.main+xml",
)
_OFFICE_DOCUMENT = "/officeDocument"
_CHUNK = 64 * 1024
_ENCRYPTED_FLAG = 0x1
_DAMAGED = N_("the Office file is damaged, or too large to read safely")
_TOO_LARGE = N_("the Office file is too large to read safely")


@dataclass(frozen=True)
class Relationship:
    """A link from one part to another, or to an outside address (never followed)."""

    type: str
    target: str
    external: bool


def word_document(data: bytes) -> bool:
    """Whether the data is a ZIP whose content types name a Word main part.

    Reads the ZIP directory and one small entry; parses no XML.
    """
    return _names_main_type(data, WORD_MAIN_TYPES)


def excel_workbook(data: bytes) -> bool:
    """Whether the data is a ZIP whose content types name an Excel main part."""
    return _names_main_type(data, EXCEL_MAIN_TYPES)


def _names_main_type(data: bytes, main_types: tuple[bytes, ...]) -> bool:
    if not data.startswith(ZIP_SIGNATURE):
        return False
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            info = archive.getinfo(CONTENT_TYPES)
            if info.flag_bits & _ENCRYPTED_FLAG or info.file_size > OFFICE_MAX_CONTENT_TYPES_BYTES:
                return False
            with archive.open(info) as entry:
                types = entry.read(OFFICE_MAX_CONTENT_TYPES_BYTES + 1)
    except (zipfile.BadZipFile, KeyError, OSError, ValueError, EOFError, NotImplementedError):
        return False
    return len(types) <= OFFICE_MAX_CONTENT_TYPES_BYTES and any(
        main in types for main in main_types
    )


class Package:
    """An opened package: parts read on demand, within the limits."""

    def __init__(self, data: bytes) -> None:
        """Open the archive and check its directory.

        Raises:
            Refusal: OFFICE_TOO_LARGE or OFFICE_INVALID.
        """
        if len(data) > MAX_OFFICE_FILE_BYTES:
            raise Refusal("OFFICE_TOO_LARGE", _TOO_LARGE)
        try:
            self._archive = zipfile.ZipFile(io.BytesIO(data))
            infos = self._archive.infolist()
        except (zipfile.BadZipFile, OSError, ValueError, EOFError):
            raise Refusal("OFFICE_INVALID", _DAMAGED) from None
        if len(infos) > OFFICE_MAX_ENTRIES:
            raise Refusal("OFFICE_TOO_LARGE", _TOO_LARGE)
        if any(info.flag_bits & _ENCRYPTED_FLAG for info in infos):
            raise Refusal("OFFICE_INVALID", _DAMAGED)
        # Part names are case-insensitive in the standard.
        self._infos = {info.filename.casefold(): info for info in infos}
        self._read_bytes = 0
        # Parts already counted towards the total: one read twice counts once.
        self._counted: set[str] = set()

    def has(self, name: str) -> bool:
        """Whether the package holds a part with this name (without the leading "/")."""
        return name.casefold() in self._infos

    def read(self, name: str) -> bytes:
        """A part's bytes, decompressed within the limits.

        Raises:
            Refusal: OFFICE_TOO_LARGE, or OFFICE_INVALID if the part is missing or broken.
        """
        chunks: list[bytes] = []
        with self.stream(name) as entry:
            while chunk := entry.read(_CHUNK):
                chunks.append(chunk)
        return b"".join(chunks)

    def stream(self, name: str) -> IO[bytes]:
        """A part as a file, decompressed within the limits as it is read.

        Reading raises ``Refusal`` (OFFICE_TOO_LARGE or OFFICE_INVALID) once a
        limit is passed or the data turns out broken.

        Raises:
            Refusal: OFFICE_INVALID if the part is missing or cannot be opened.
        """
        info = self._infos.get(name.casefold())
        if info is None:
            raise Refusal("OFFICE_INVALID", _DAMAGED)
        try:
            entry = self._archive.open(info)
        except (zipfile.BadZipFile, OSError, ValueError, EOFError, NotImplementedError):
            raise Refusal("OFFICE_INVALID", _DAMAGED) from None
        first = info.filename.casefold() not in self._counted
        self._counted.add(info.filename.casefold())
        return io.BufferedReader(_Counted(self, info, entry, counted=first), _CHUNK)

    def _count(self, size: int) -> None:
        self._read_bytes += size
        if self._read_bytes > OFFICE_MAX_TOTAL_BYTES:
            raise Refusal("OFFICE_TOO_LARGE", _TOO_LARGE)

    def xml(self, name: str) -> Element:
        """A part parsed as XML with ``defusedxml``.

        Raises:
            Refusal: OFFICE_TOO_LARGE or OFFICE_INVALID.
        """
        try:
            return parse(
                self.read(name),
                max_bytes=OFFICE_MAX_PART_BYTES,
                max_elements=OFFICE_MAX_PART_ELEMENTS,
            )
        except Refusal as refusal:
            if refusal.code.startswith("OFFICE_"):
                raise
            code = "OFFICE_TOO_LARGE" if refusal.code == "XML_TOO_LARGE" else "OFFICE_INVALID"
            raise Refusal(code, _TOO_LARGE if code == "OFFICE_TOO_LARGE" else _DAMAGED) from None

    def relationships(self, part: str) -> dict[str, Relationship]:
        """The relationships of a part, by id; ``part`` "" for the package's own."""
        folder, base = posixpath.split(part)
        rels = posixpath.join(folder, "_rels", f"{base}.rels")
        if not self.has(rels):
            return {}
        found: dict[str, Relationship] = {}
        for element in self.xml(rels):
            if local_name(element.tag) != "Relationship":
                continue
            rid, target = element.attrib.get("Id"), element.attrib.get("Target")
            if not rid or target is None:
                continue
            external = element.attrib.get("TargetMode", "").casefold() == "external"
            found[rid] = Relationship(
                type=element.attrib.get("Type", ""),
                target=target if external else _resolve(folder, target),
                external=external,
            )
        return found

    def main_part(self) -> str:
        """The name of the main document part, from the package's relationships.

        Raises:
            Refusal: OFFICE_INVALID if there is none.
        """
        for relationship in self.relationships("").values():
            if (
                relationship.type.endswith(_OFFICE_DOCUMENT)
                and not relationship.external
                and self.has(relationship.target)
            ):
                return relationship.target
        raise Refusal("OFFICE_INVALID", _DAMAGED)


class _Counted(io.RawIOBase):
    """One part's decompressed bytes, counted against the limits as they come."""

    def __init__(
        self, package: Package, info: zipfile.ZipInfo, entry: IO[bytes], *, counted: bool
    ) -> None:
        self._package = package
        self._info = info
        self._entry = entry
        self._counts = counted
        self._size = 0

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: "memoryview | bytearray") -> int:  # type: ignore[override]
        try:
            chunk = self._entry.read(min(len(buffer), _CHUNK))
        except (zipfile.BadZipFile, OSError, ValueError, EOFError, NotImplementedError):
            raise Refusal("OFFICE_INVALID", _DAMAGED) from None
        self._size += len(chunk)
        if self._counts:
            self._package._count(len(chunk))
        if self._size > OFFICE_MAX_PART_BYTES:
            raise Refusal("OFFICE_TOO_LARGE", _TOO_LARGE)
        if self._size > OFFICE_RATIO_MIN_BYTES and self._size > OFFICE_MAX_RATIO * max(
            self._info.compress_size, 1
        ):
            raise Refusal("OFFICE_TOO_LARGE", _TOO_LARGE)
        buffer[: len(chunk)] = chunk
        return len(chunk)

    def close(self) -> None:
        self._entry.close()
        super().close()


def _resolve(folder: str, target: str) -> str:
    """A relationship target as a part name: relative to the source's folder, or absolute."""
    path = target[1:] if target.startswith("/") else posixpath.join(folder, target)
    return posixpath.normpath(path).lstrip("/")
