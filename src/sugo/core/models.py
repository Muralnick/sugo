"""Intermediate representation (IR): Document → Page → Block (ADR-005).

Extractors produce these models, cleaners and detectors propose changes to them,
and only the core applies those changes. Markdown is rendered from the IR at the
very end of the pipeline.

Every model is immutable: a change is a new copy, so a buggy extension cannot
alter a block behind the core's back (ADR-028). Coordinates are normalised to
0-1 so the same positional rules work on phone screenshots, 4K monitors and A4
pages. Removal is soft: a removed block stays in the IR with who removed it and
why (principle 3).

A Document carries only its source metadata. Its pages live in the page store
and are streamed one at a time, so memory does not grow with document length
(ADR-006).
"""

from enum import StrEnum
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from sugo.core.constants import MAX_HEADING_LEVEL, PAGE_ROTATIONS, SHA256_HEX_LENGTH

NonEmptyStr = Annotated[str, Field(min_length=1)]
UnitInterval = Annotated[float, Field(ge=0.0, le=1.0)]
# Lowercase, hyphen-separated identifiers such as "latin" or "han-kana": language
# packs add scripts over time, so the set stays open instead of being an enum.
ScriptName = Annotated[str, Field(pattern=r"^[a-z]+(-[a-z]+)*$")]


class _Model(BaseModel):
    """Shared configuration: immutable, unknown fields rejected, no silent coercion."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class BlockType(StrEnum):
    """What a block is; drives cleaning rules and Markdown rendering."""

    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST_ITEM = "list_item"
    TABLE = "table"
    CODE = "code"
    CHAT_MESSAGE = "chat_message"
    IMAGE = "image"
    CAPTION = "caption"
    FOOTNOTE = "footnote"
    FORMULA = "formula"
    HEADER = "header"
    FOOTER = "footer"
    PAGE_NUMBER = "page_number"
    UI_CHROME = "ui_chrome"


class PageOrigin(StrEnum):
    """How the page's text was obtained (ADR-001)."""

    NATIVE = "native"
    OCR = "ocr"
    VLM = "vlm"


class ChatSide(StrEnum):
    """Side of a chat bubble. Neutral on purpose: which side is the phone's
    owner depends on the app, so Sugo records what it sees, not who it guesses."""

    LEFT = "left"
    RIGHT = "right"


class BlockFlag(StrEnum):
    """Warnings attached to a block for later stages and for the user (ADR-026)."""

    ILLEGIBLE = "illegible"
    SUSPICIOUS_INSTRUCTION = "suspicious_instruction"
    LOW_AGREEMENT = "low_agreement"
    # Text a reader cannot see on the rendered page: white on white, microscopic,
    # off the page or drawn invisible. Kept apart so a cleaner can remove it with
    # a reason; a classic way to slip instructions to an LLM (ADR-043).
    HIDDEN = "hidden"


class EditKind(StrEnum):
    """The only kinds of text change the core applies (ADR-050).

    Each kind is checked mechanically by the core, so no cleaner can slip in
    new words: a deletion only removes, a normalisation keeps every visible
    character, and a hyphen join only removes a line-break hyphen.
    """

    # Remove a span, e.g. a tracking parameter from a URL.
    DELETE = "delete"
    # Same visible characters, other form: "ﬁ" -> "fi", a no-break space -> " ".
    NORMALIZE = "normalize"
    # "infor-\nmation" -> "information": the hyphen and the line break go.
    HYPHEN_JOIN = "hyphen_join"


class TextEdit(_Model):
    """A change the core made to a block's text, kept so it can be inspected and undone.

    ``start`` and ``end`` index the text as it was before the edits of the
    same cleaner, so applying the record in reverse restores the original.
    """

    start: Annotated[int, Field(ge=0)]
    end: Annotated[int, Field(ge=0)]
    original: NonEmptyStr
    replacement: str
    kind: EditKind
    edited_by: NonEmptyStr
    reason: NonEmptyStr

    @model_validator(mode="after")
    def _check_span(self) -> Self:
        if self.end - self.start != len(self.original):
            raise ValueError("an edit's span must match its original text")
        if self.original == self.replacement:
            raise ValueError("an edit must change the text")
        return self


class BBox(_Model):
    """Bounding box normalised to the page: (0, 0) is top-left, (1, 1) bottom-right."""

    x0: UnitInterval
    y0: UnitInterval
    x1: UnitInterval
    y1: UnitInterval

    @model_validator(mode="after")
    def _check_order(self) -> Self:
        if self.x0 > self.x1 or self.y0 > self.y1:
            raise ValueError("bbox corners must satisfy x0 <= x1 and y0 <= y1")
        return self


class Style(_Model):
    """Typographic hints, when the extractor can provide them."""

    font_size: Annotated[float, Field(gt=0)] | None = None
    bold: bool | None = None
    monospace: bool | None = None


class TimeRange(_Model):
    """Reserved for audio and video sources (ADR-005); unused for documents."""

    start: Annotated[float, Field(ge=0)]
    end: Annotated[float, Field(ge=0)]

    @model_validator(mode="after")
    def _check_order(self) -> Self:
        if self.start > self.end:
            raise ValueError("time range must satisfy start <= end")
        return self


class TableCell(_Model):
    """One cell of a table grid; spans let a cell cover several rows or columns."""

    row: Annotated[int, Field(ge=0)]
    col: Annotated[int, Field(ge=0)]
    text: str = ""
    row_span: Annotated[int, Field(ge=1)] = 1
    col_span: Annotated[int, Field(ge=1)] = 1


class Table(_Model):
    """Cell grid of a table block, kept structured so the serializer can pick
    the cheapest format that preserves it (ADR-002)."""

    n_rows: Annotated[int, Field(ge=1)]
    n_cols: Annotated[int, Field(ge=1)]
    header_rows: Annotated[int, Field(ge=0)] = 0
    cells: tuple[TableCell, ...]

    @model_validator(mode="after")
    def _check_grid(self) -> Self:
        if self.header_rows > self.n_rows:
            raise ValueError("header_rows cannot exceed n_rows")
        occupied: set[tuple[int, int]] = set()
        for cell in self.cells:
            if cell.row + cell.row_span > self.n_rows or cell.col + cell.col_span > self.n_cols:
                raise ValueError(f"cell at ({cell.row}, {cell.col}) extends outside the grid")
            for r in range(cell.row, cell.row + cell.row_span):
                for c in range(cell.col, cell.col + cell.col_span):
                    if (r, c) in occupied:
                        raise ValueError(f"cells overlap at ({r}, {c})")
                    occupied.add((r, c))
        return self


class Block(_Model):
    """Smallest unit of content on a page.

    Invariants checked on every construction:
    - a removed block always records who removed it and why (principle 3);
    - an illegible block carries no text: unreadable content is marked, never
      filled with a guess (principle 4);
    - heading levels, table grids and chat speakers appear only on blocks of
      the matching type.
    """

    id: NonEmptyStr
    type: BlockType
    text: str = ""
    script: ScriptName | None = None
    language: NonEmptyStr | None = None
    confidence: UnitInterval | None = None
    bbox: BBox | None = None
    style: Style | None = None
    heading_level: Annotated[int, Field(ge=1, le=MAX_HEADING_LEVEL)] | None = None
    reading_order: Annotated[int, Field(ge=0)] | None = None
    table: Table | None = None
    speaker: ChatSide | None = None
    origin_engine: NonEmptyStr
    flags: tuple[BlockFlag, ...] = ()
    time_range: TimeRange | None = None
    # Every change made to ``text``, oldest first (principle 3, ADR-050).
    edits: tuple[TextEdit, ...] = ()
    removed: bool = False
    removed_by: NonEmptyStr | None = None
    reason: NonEmptyStr | None = None

    @field_validator("flags", mode="after")
    @classmethod
    def _normalise_flags(cls, flags: tuple[BlockFlag, ...]) -> tuple[BlockFlag, ...]:
        # Sorted and unique, so equal blocks serialise identically (principle 6).
        return tuple(sorted(set(flags)))

    @model_validator(mode="after")
    def _check_invariants(self) -> Self:
        if self.removed and (self.removed_by is None or self.reason is None):
            raise ValueError("a removed block must record removed_by and reason")
        if not self.removed and (self.removed_by is not None or self.reason is not None):
            raise ValueError("removed_by and reason are only allowed on removed blocks")
        if BlockFlag.ILLEGIBLE in self.flags and (self.text or self.edits):
            raise ValueError("an illegible block must not carry text")
        if self.heading_level is not None and self.type is not BlockType.HEADING:
            raise ValueError("heading_level is only allowed on heading blocks")
        if self.table is not None and self.type is not BlockType.TABLE:
            raise ValueError("table is only allowed on table blocks")
        if self.speaker is not None and self.type is not BlockType.CHAT_MESSAGE:
            raise ValueError("speaker is only allowed on chat_message blocks")
        return self

    def original_text(self) -> str:
        """The text as extracted, before any edit: every edit undone, newest first."""
        text = self.text
        groups: list[list[TextEdit]] = []
        for edit in self.edits:
            if groups and groups[-1][0].edited_by == edit.edited_by:
                groups[-1].append(edit)
            else:
                groups.append([edit])
        for group in reversed(groups):
            # Offsets index the text before this cleaner's edits. Undone in
            # order, everything before an edit is already that text again.
            for edit in group:
                end = edit.start + len(edit.replacement)
                text = text[: edit.start] + edit.original + text[end:]
        return text

    def mark_removed(self, removed_by: str, reason: str) -> Self:
        """Return a copy marked as removed; the block itself is never deleted.

        Args:
            removed_by: Name of the cleaner or rule that removed the block.
            reason: Human-readable explanation, shown by preview and explain.

        Raises:
            ValueError: If the block is already removed, or either argument is empty.
        """
        if self.removed:
            raise ValueError(f"block {self.id!r} is already removed")
        # model_copy skips validation, so rebuild through the validator instead.
        return self.model_validate(
            {**self.model_dump(), "removed": True, "removed_by": removed_by, "reason": reason}
        )


class Page(_Model):
    """One page of a document, or one image."""

    index: Annotated[int, Field(ge=0)]
    # Native units of the source: points for PDF pages, pixels for images.
    width: Annotated[float, Field(gt=0)]
    height: Annotated[float, Field(gt=0)]
    rotation: int = 0
    origin: PageOrigin
    blocks: tuple[Block, ...] = ()

    @field_validator("rotation", mode="after")
    @classmethod
    def _check_rotation(cls, rotation: int) -> int:
        if rotation not in PAGE_ROTATIONS:
            raise ValueError(f"rotation must be one of {sorted(PAGE_ROTATIONS)}")
        return rotation

    @model_validator(mode="after")
    def _check_unique_block_ids(self) -> Self:
        ids = [block.id for block in self.blocks]
        if len(ids) != len(set(ids)):
            raise ValueError("block ids must be unique within a page")
        return self


class DocumentSource(_Model):
    """Where a document comes from and what it contains."""

    # A filesystem path or a URL, as given by the user or the container.
    location: NonEmptyStr
    # Path of the entry inside an archive or email, e.g. "2025/agreement.pdf" (ADR-020).
    container_path: NonEmptyStr | None = None
    media_type: NonEmptyStr
    sha256: Annotated[
        str,
        Field(
            min_length=SHA256_HEX_LENGTH,
            max_length=SHA256_HEX_LENGTH,
            pattern=r"^[0-9a-f]+$",
        ),
    ]
    page_count: Annotated[int, Field(ge=0)]
    languages: tuple[NonEmptyStr, ...] = ()


class Document(_Model):
    """A document being processed; its pages are streamed from the page store."""

    source: DocumentSource
