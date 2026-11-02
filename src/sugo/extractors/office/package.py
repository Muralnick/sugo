"""Office Open XML packages: ZIP archives of XML parts, opened with every limit enforced (ADR-054).

Nothing is ever extracted to disk, so entry names with ``..`` or absolute
paths do no harm. Parts are found only through the package's relationships;
external relationships are recorded but never followed. Each part is
decompressed in bounded steps and counted as it comes: the sizes written in
the archive are the attacker's, so they are never trusted.

``office_kind`` recognises a Word document, an Excel workbook or a
PowerPoint presentation from the raw bytes, without parsing XML, so Sugo's own process can route a
file before the worker reads it. ``stream`` lets a large part be
parsed piece by piece; a part read twice counts once towards the total.
"""

import io
import math
import posixpath
import re
import zipfile
from dataclasses import dataclass
from typing import IO

from sugo.core.constants import (
    MAX_OFFICE_FILE_BYTES,
    OFFICE_EMU_PER_POINT,
    OFFICE_MAX_CONTENT_TYPES_BYTES,
    OFFICE_MAX_COORDINATE,
    OFFICE_MAX_ENTRIES,
    OFFICE_MAX_PART_BYTES,
    OFFICE_MAX_PART_ELEMENTS,
    OFFICE_MAX_RATIO,
    OFFICE_MAX_TOTAL_BYTES,
    OFFICE_RATIO_MIN_BYTES,
    OFFICE_UNDERSTOOD_NAMESPACES,
)
from sugo.core.models import Page
from sugo.extractors.office.xml_reader import (
    REQUIRED_NAMESPACES,
    Element,
    Refusal,
    local_name,
    parse,
)
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
# Main parts of PowerPoint presentations, templates, slide shows and their
# macro-enabled forms; the binary .ppt is an OLE file, refused before this.
POWERPOINT_MAIN_TYPES = (
    b"application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml",
    b"application/vnd.openxmlformats-officedocument.presentationml.template.main+xml",
    b"application/vnd.openxmlformats-officedocument.presentationml.slideshow.main+xml",
    b"application/vnd.ms-powerpoint.presentation.macroEnabled.main+xml",
    b"application/vnd.ms-powerpoint.template.macroEnabled.main+xml",
    b"application/vnd.ms-powerpoint.slideshow.macroEnabled.main+xml",
)
# In the order a file naming several main parts is taken for one of them.
_MAIN_TYPES = (
    ("docx", WORD_MAIN_TYPES),
    ("xlsx", EXCEL_MAIN_TYPES),
    ("pptx", POWERPOINT_MAIN_TYPES),
)
# Only these outside addresses become Markdown links; anything else (javascript:,
# file:, white space or brackets that would break the link) stays plain text.
SAFE_LINK = re.compile(r"(?:https?://|mailto:)[^\s()<>\[\]]+", re.IGNORECASE)
_MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"
_RELATIONSHIP_NAMESPACES = frozenset(
    {
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
        "http://purl.oclc.org/ooxml/officeDocument/relationships",
    }
)
# Text bodies inside drawings: Word's text boxes and DrawingML's text, which
# the readers lay out themselves, pictures included.
_TEXT_BODIES = frozenset({"txbxContent", "txBody", "textbox"})
_OFFICE_DOCUMENT = "/officeDocument"
_CHUNK = 64 * 1024
_ENCRYPTED_FLAG = 0x1
_DAMAGED = N_("the Office file is damaged, or too large to read safely")
_TOO_LARGE = N_("the Office file is too large to read safely")


@dataclass(frozen=True)
class Picture:
    """A picture drawn from a package part, as a person sees it on the page."""

    part: str
    # Shares of the image cut off on the left, top, right and bottom: what a
    # person never sees of it.
    crop: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    # Height and width it is shown at, in points; None when the reader cannot
    # tell. Zero is a size: a picture drawn with none is not seen.
    height: float | None = None
    width: float | None = None


# A page as a reader lays it out, with each picture marked not converted, by
# block id: Sugo's process reads them with OCR (ADR-054).
type LaidOut = tuple[Page, dict[str, Picture]]


@dataclass(frozen=True)
class Relationship:
    """A link from one part to another, or to an outside address (never followed)."""

    type: str
    target: str
    external: bool


def office_kind(data: bytes) -> str | None:
    """ "docx", "xlsx" or "pptx" if the data is a ZIP whose content types name that main part.

    Reads the ZIP directory and one small entry, once; parses no XML.
    """
    if not data.startswith(ZIP_SIGNATURE):
        return None
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            info = archive.getinfo(CONTENT_TYPES)
            if info.flag_bits & _ENCRYPTED_FLAG or info.file_size > OFFICE_MAX_CONTENT_TYPES_BYTES:
                return None
            with archive.open(info) as entry:
                types = entry.read(OFFICE_MAX_CONTENT_TYPES_BYTES + 1)
    except (zipfile.BadZipFile, KeyError, OSError, ValueError, EOFError, NotImplementedError):
        return None
    if len(types) > OFFICE_MAX_CONTENT_TYPES_BYTES:
        return None
    for kind, main_types in _MAIN_TYPES:
        if any(main in types for main in main_types):
            return kind
    return None


def word_document(data: bytes) -> bool:
    """Whether the data is a ZIP whose content types name a Word main part."""
    return office_kind(data) == "docx"


def excel_workbook(data: bytes) -> bool:
    """Whether the data is a ZIP whose content types name an Excel main part."""
    return office_kind(data) == "xlsx"


def powerpoint_presentation(data: bytes) -> bool:
    """Whether the data is a ZIP whose content types name a PowerPoint main part."""
    return office_kind(data) == "pptx"


def pictures_in(
    drawing: Element,
    relationships: dict[str, Relationship],
    package: "Package",
    *,
    height: float | None = None,
    width: float | None = None,
) -> list["Picture"]:
    """Every picture a drawing shows from a part inside the package, in document order.

    ``height`` and ``width`` are the size the drawing is shown at, in points,
    when the reader knows it. Linked pictures (external relationships) are
    never followed, so they are not listed. Text boxes are left to the reader,
    which lays out their text and pictures with their own hidden state, and
    alternate content is read as Office reads it (``chosen_content``).
    """
    found: list[Picture] = []
    stack = [drawing]
    while stack:
        element = stack.pop()
        name = local_name(element.tag)
        if name in _TEXT_BODIES:
            continue
        if element.tag == f"{{{_MC}}}AlternateContent":
            branch = chosen_content(element)
            stack.extend([] if branch is None else list(branch)[::-1])
            continue
        if name == "blipFill":
            # DrawingML: a:blip names the part, a:srcRect the share cut off each side.
            blip = next((child for child in element if local_name(child.tag) == "blip"), None)
            part = _target(blip, "embed", relationships, package)
            if part is not None:
                crop = next((c for c in element if local_name(c.tag) == "srcRect"), None)
                left, top, right, bottom = (
                    _share(None if crop is None else crop.attrib.get(side))
                    for side in ("l", "t", "r", "b")
                )
                found.append(Picture(part, _crop(left, top, right, bottom), height, width))
            continue
        if name == "imagedata":
            # VML, in older documents and in fallbacks: v:imagedata and its crop attributes.
            part = _target(element, "id", relationships, package)
            if part is not None:
                left, top, right, bottom = (
                    _vml_share(element.attrib.get(side))
                    for side in ("cropleft", "croptop", "cropright", "cropbottom")
                )
                found.append(Picture(part, _crop(left, top, right, bottom), height, width))
        stack.extend(list(element)[::-1])
    return found


def shown_size(extent: Element | None) -> tuple[float | None, float | None]:
    """Height and width, in points, of an extent element (``cx``, ``cy`` in EMU).

    A missing or unreadable value is unknown (None); zero or less is no size,
    a drawing nobody sees; a value past the standard's range is that range.
    """

    def points(value: str | None) -> float | None:
        try:
            emu = None if value is None else int(value)
        except ValueError:
            return None
        if emu is None:
            return None
        return min(max(emu, 0), OFFICE_MAX_COORDINATE) / OFFICE_EMU_PER_POINT

    if extent is None:
        return None, None
    return points(extent.attrib.get("cy")), points(extent.attrib.get("cx"))


def _target(
    element: Element | None, name: str, relationships: dict[str, Relationship], package: "Package"
) -> str | None:
    """The internal part a relationship attribute (``r:embed``, ``r:id``) points at."""
    if element is None:
        return None
    for key, value in element.attrib.items():
        namespace = key[1:].split("}", 1)[0] if key.startswith("{") else ""
        if local_name(key) == name and namespace in _RELATIONSHIP_NAMESPACES:
            target = relationships.get(value)
            if target is not None and not target.external and package.has(target.target):
                return target.target
    return None


def _share(value: str | None) -> float:
    """A DrawingML percentage in thousandths of a percent (100 000 = all)."""
    try:
        return 0.0 if value is None else int(value) / 100_000
    except ValueError:
        return 0.0


def _vml_share(value: str | None) -> float:
    """A VML crop value: a fraction ("0.25") or 65 536ths ("16384f")."""
    if value is None:
        return 0.0
    try:
        share = float(value[:-1]) / 65_536 if value.endswith("f") else float(value)
    except ValueError:
        return 0.0
    return share if math.isfinite(share) else 0.0


def _crop(
    left: float, top: float, right: float, bottom: float
) -> tuple[float, float, float, float]:
    """Shares cut off each side, within 0-1; a negative value pads the picture and cuts nothing."""

    def unit(side: float) -> float:
        return min(max(side, 0.0), 1.0)

    return unit(left), unit(top), unit(right), unit(bottom)


def chosen_content(alternate: Element) -> Element | None:
    """The branch of an ``mc:AlternateContent`` that Office shows, or None.

    The first ``mc:Choice`` whose required namespaces Office all understands,
    else the ``mc:Fallback``. A Choice requiring a namespace Office does not
    know is never shown by Office, so it is never read: otherwise a crafted
    file could show a person the fallback and give the LLM other text.
    """
    for branch in alternate:
        if not branch.tag.startswith(f"{{{_MC}}}"):
            continue
        name = local_name(branch.tag)
        if name == "Choice":
            required = branch.attrib.get(REQUIRED_NAMESPACES, "").split()
            if all(uri in OFFICE_UNDERSTOOD_NAMESPACES for uri in required):
                return branch
        elif name == "Fallback":
            return branch
    return None


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
                office=True,
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
