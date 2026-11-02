"""Tests for the decorative image cleaner: only decorative pictures, removal applied by the core."""

from sugo.cleaners.decorative_images import REASON, DecorativeImageCleaner
from sugo.core.decisions import Decision, apply_decisions
from sugo.core.models import Block, BlockFlag, BlockType, Page, PageOrigin


def picture(block_id: str, *flags: BlockFlag) -> Block:
    return Block(
        id=block_id,
        type=BlockType.IMAGE,
        origin_engine="t",
        flags=(BlockFlag.ILLEGIBLE, *flags),
    )


def page(*blocks: Block) -> Page:
    return Page(index=0, width=1.0, height=1.0, origin=PageOrigin.NATIVE, blocks=blocks)


def test_proposes_only_decorative_pictures() -> None:
    p = page(picture("dot", BlockFlag.DECORATIVE), picture("photo"))
    assert DecorativeImageCleaner().propose(p) == [Decision(block_id="dot", reason=REASON)]


def test_skips_pictures_already_removed() -> None:
    p = page(picture("dot", BlockFlag.DECORATIVE).mark_removed("other", "r"))
    assert DecorativeImageCleaner().propose(p) == []


def test_removal_is_soft() -> None:
    p = page(picture("dot", BlockFlag.DECORATIVE))
    cleaned = apply_decisions(p, DecorativeImageCleaner().propose(p), cleaner="decorative_images")
    (block,) = cleaned.blocks
    assert (block.removed, block.removed_by, block.reason) == (True, "decorative_images", REASON)
