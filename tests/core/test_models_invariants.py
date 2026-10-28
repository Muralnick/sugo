"""Invariant and property tests for the IR: principles 3, 4 and 6 hold for any block.

Hypothesis generates thousands of valid blocks; every one must satisfy the
principles, whatever its content.
"""

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from sugo.core.models import BBox, Block, BlockFlag, BlockType, Page, PageOrigin

unit = st.floats(min_value=0.0, max_value=1.0, allow_nan=False)
names = st.text(min_size=1, max_size=20)


@st.composite
def bboxes(draw: st.DrawFn) -> BBox:
    x0, x1 = sorted((draw(unit), draw(unit)))
    y0, y1 = sorted((draw(unit), draw(unit)))
    return BBox(x0=x0, y0=y0, x1=x1, y1=y1)


@st.composite
def blocks(draw: st.DrawFn) -> Block:
    flags = draw(st.lists(st.sampled_from(BlockFlag), max_size=3))
    illegible = BlockFlag.ILLEGIBLE in flags
    return Block(
        id=draw(names),
        type=draw(st.sampled_from([t for t in BlockType if t is not BlockType.TABLE])),
        text="" if illegible else draw(st.text(max_size=200)),
        confidence=draw(st.none() | unit),
        bbox=draw(st.none() | bboxes()),
        reading_order=draw(st.none() | st.integers(min_value=0, max_value=10_000)),
        origin_engine=draw(names),
        flags=tuple(flags),
    )


@pytest.mark.invariant
@given(block=blocks(), removed_by=names, reason=names)
def test_removal_always_keeps_content_and_reason(
    block: Block, removed_by: str, reason: str
) -> None:
    # Principle 3: no silent loss.
    removed = block.mark_removed(removed_by, reason)
    assert removed.removed
    assert removed.removed_by == removed_by
    assert removed.reason == reason
    assert removed.text == block.text
    assert removed.model_dump(exclude={"removed", "removed_by", "reason"}) == block.model_dump(
        exclude={"removed", "removed_by", "reason"}
    )


@pytest.mark.invariant
@pytest.mark.parametrize(
    ("removed_by", "reason"), [(None, None), ("cleaner", None), (None, "why"), ("", "why")]
)
def test_removal_without_author_or_reason_is_rejected(
    removed_by: str | None, reason: str | None
) -> None:
    # Principle 3: a removal nobody can explain must be impossible to build.
    with pytest.raises(ValidationError):
        Block(
            id="b1",
            type=BlockType.FOOTER,
            text="Confidential",
            origin_engine="pymupdf",
            removed=True,
            removed_by=removed_by,
            reason=reason,
        )


@pytest.mark.invariant
@given(text=st.text(min_size=1))
def test_illegible_block_cannot_carry_text(text: str) -> None:
    # Principle 4: unreadable areas are marked, never filled with a guess.
    with pytest.raises(ValidationError, match="illegible"):
        Block(
            id="b1",
            type=BlockType.PARAGRAPH,
            text=text,
            origin_engine="rapidocr",
            flags=(BlockFlag.ILLEGIBLE,),
        )


@pytest.mark.invariant
@given(page_blocks=st.lists(blocks(), max_size=5, unique_by=lambda b: b.id))
def test_page_round_trips_through_json_unchanged(page_blocks: list[Block]) -> None:
    # Principle 6: the page store serialises pages; a reload must be identical.
    page = Page(
        index=0, width=595.0, height=842.0, origin=PageOrigin.NATIVE, blocks=tuple(page_blocks)
    )
    json_text = page.model_dump_json()
    reloaded = Page.model_validate_json(json_text)
    assert reloaded == page
    assert reloaded.model_dump_json() == json_text


@given(block=blocks())
def test_flag_order_does_not_change_serialisation(block: Block) -> None:
    reversed_flags = block.model_copy(update={"flags": tuple(reversed(block.flags))})
    rebuilt = Block.model_validate(reversed_flags.model_dump())
    assert rebuilt.model_dump_json() == block.model_dump_json()
