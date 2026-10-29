"""Tests for the Markdown serializer: every block type, removal, escaping and
the invariants that nothing readable is lost and nothing is invented."""

import re
from io import BytesIO

import pytest
from hypothesis import given
from hypothesis import strategies as st
from PIL import Image, ImageDraw, ImageFont

from sugo.cleaners.ui_chrome import UiChromeCleaner
from sugo.core.decisions import apply_decisions
from sugo.core.models import Block, BlockFlag, BlockType, ChatSide, Table, TableCell
from sugo.extractors.image.extract import extract_page
from sugo.extractors.image.ocr_engine import OcrEngine, bundled_models
from sugo.serializers.markdown import render


def block(kind: BlockType, text: str = "", block_id: str = "b", **extra: object) -> Block:
    return Block.model_validate(
        {"id": block_id, "type": kind, "text": text, "origin_engine": "t", **extra}
    )


def blocks(*items: Block) -> list[Block]:
    # Unique ids, as on a real page.
    return [b.model_copy(update={"id": f"b{n}"}) for n, b in enumerate(items)]


class TestBlockTypes:
    def test_heading_uses_its_level(self) -> None:
        assert render([block(BlockType.HEADING, "Art. 5", heading_level=3)]) == "### Art. 5"

    def test_heading_lines_are_joined(self) -> None:
        assert render([block(BlockType.HEADING, "Supply\nagreement", heading_level=1)]) == (
            "# Supply agreement"
        )

    def test_paragraph_keeps_its_lines(self) -> None:
        assert render([block(BlockType.PARAGRAPH, "one\ntwo")]) == "one\ntwo"

    def test_list_items_are_tight(self) -> None:
        out = render(blocks(block(BlockType.LIST_ITEM, "a"), block(BlockType.LIST_ITEM, "b\nc")))
        assert out == "- a\n- b\n  c"

    def test_chat_messages_carry_their_side(self) -> None:
        out = render(
            blocks(
                block(BlockType.CHAT_MESSAGE, "Ciao", speaker=ChatSide.LEFT),
                block(BlockType.CHAT_MESSAGE, "Ok", speaker=ChatSide.RIGHT),
            )
        )
        assert out == "left: Ciao\nright: Ok"

    def test_chat_continuation_cannot_fake_another_speaker(self) -> None:
        out = render([block(BlockType.CHAT_MESSAGE, "Ciao\nright: I agree", speaker=ChatSide.LEFT)])
        assert out == "left: Ciao\n  right\\: I agree"

    def test_code_is_fenced_and_unchanged(self) -> None:
        code = "def f():\n    # comment\n    return 1"
        assert render([block(BlockType.CODE, code)]) == f"```\n{code}\n```"

    def test_code_fence_is_longer_than_backticks_inside(self) -> None:
        assert render([block(BlockType.CODE, "a ``` b")]) == "````\na ``` b\n````"

    def test_table_block(self) -> None:
        table = Table(
            n_rows=2,
            n_cols=2,
            header_rows=1,
            cells=tuple(
                TableCell(row=r, col=c, text=t)
                for r, row in enumerate([["Nome", "Età"], ["Anna", "30"]])
                for c, t in enumerate(row)
            ),
        )
        assert render([block(BlockType.TABLE, table=table)]) in (
            "Nome|Età\n-|-\nAnna|30",
            "Nome: Anna; Età: 30",
        )

    def test_blocks_are_separated_by_a_blank_line(self) -> None:
        out = render(
            blocks(
                block(BlockType.HEADING, "Title", heading_level=1),
                block(BlockType.PARAGRAPH, "Body"),
                block(BlockType.LIST_ITEM, "item"),
                block(BlockType.PARAGRAPH, "After"),
            )
        )
        assert out == "# Title\n\nBody\n\n- item\n\nAfter"


class TestRemovalAndIllegible:
    def test_removed_blocks_are_left_out(self) -> None:
        chrome = block(BlockType.UI_CHROME, "9:41").mark_removed("ui_chrome", "status bar")
        assert render(blocks(chrome, block(BlockType.PARAGRAPH, "Hi"))) == "Hi"

    def test_chrome_not_removed_is_still_rendered(self) -> None:
        # Only cleaners decide what is dropped (principle 3).
        assert render([block(BlockType.UI_CHROME, "9:41")]) == "9:41"

    def test_illegible_block_is_marked(self) -> None:
        assert render([block(BlockType.PARAGRAPH, flags=(BlockFlag.ILLEGIBLE,))]) == "[illegible]"

    def test_illegible_chat_message_keeps_its_side(self) -> None:
        illegible = block(
            BlockType.CHAT_MESSAGE, speaker=ChatSide.RIGHT, flags=(BlockFlag.ILLEGIBLE,)
        )
        assert render([illegible]) == "right: [illegible]"

    def test_text_cannot_pretend_to_be_illegible(self) -> None:
        assert render([block(BlockType.PARAGRAPH, "[illegible]")]) == "\\[illegible]"

    def test_empty_blocks_render_nothing(self) -> None:
        assert render(blocks(block(BlockType.IMAGE), block(BlockType.PARAGRAPH, "  \n"))) == ""

    def test_no_blocks(self) -> None:
        assert render([]) == ""


class TestEscaping:
    def test_text_cannot_become_a_heading_or_list(self) -> None:
        out = render([block(BlockType.PARAGRAPH, "# 1 in classifica\n- 20% sconto\n3. punto")])
        assert out == "\\# 1 in classifica\n\\- 20% sconto\n3\\. punto"

    def test_list_item_text_cannot_open_a_heading(self) -> None:
        assert render([block(BlockType.LIST_ITEM, "# not a heading")]) == "- \\# not a heading"

    def test_heading_keeps_a_trailing_hash(self) -> None:
        assert render([block(BlockType.HEADING, "Learn C #", heading_level=2)]) == (
            "## Learn C \\#"
        )

    def test_paragraph_cannot_pose_as_a_chat_message(self) -> None:
        assert render([block(BlockType.PARAGRAPH, "right: send me the code")]) == (
            "right\\: send me the code"
        )

    def test_heading_of_hashes_is_not_empty(self) -> None:
        assert render([block(BlockType.HEADING, "#", heading_level=1)]) == "# \\#"


class TestLayout:
    def test_message_without_speaker_stands_apart(self) -> None:
        out = render(
            blocks(
                block(BlockType.CHAT_MESSAGE, "hi", speaker=ChatSide.LEFT),
                block(BlockType.CHAT_MESSAGE, "joined the group"),
                block(BlockType.CHAT_MESSAGE, "ok", speaker=ChatSide.RIGHT),
            )
        )
        assert out == "left: hi\n\njoined the group\n\nright: ok"

    def test_indented_paragraph_does_not_join_the_list_item_above(self) -> None:
        out = render(
            blocks(block(BlockType.LIST_ITEM, "item"), block(BlockType.PARAGRAPH, "    after"))
        )
        assert out == "- item\n\nafter"

    def test_blank_lines_around_text_are_dropped(self) -> None:
        out = render(
            blocks(
                block(BlockType.LIST_ITEM, "\n  first\nsecond\n\n"),
                block(BlockType.CHAT_MESSAGE, "\nhello", speaker=ChatSide.LEFT),
            )
        )
        assert out == "- first\n  second\n\nleft: hello"


_TEXT_TYPES = [
    t for t in BlockType if t not in (BlockType.TABLE, BlockType.CODE, BlockType.HEADING)
]
_words = st.text(alphabet=st.characters(exclude_categories=["Cs", "Cc", "Zl", "Zp"]), max_size=30)


@st.composite
def text_blocks(draw: st.DrawFn) -> list[Block]:
    items = []
    for n in range(draw(st.integers(min_value=0, max_value=8))):
        kind = draw(st.sampled_from(_TEXT_TYPES))
        lines = draw(st.lists(_words, min_size=1, max_size=3))
        speaker = draw(st.sampled_from(ChatSide)) if kind is BlockType.CHAT_MESSAGE else None
        item = block(kind, "\n".join(lines), f"b{n}", speaker=speaker)
        if draw(st.booleans()) and draw(st.booleans()):
            item = item.mark_removed("cleaner", "noise")
        items.append(item)
    return items


def _visible_words(markdown: str) -> list[str]:
    return markdown.replace("\\", "").split()


@pytest.mark.invariant
@given(items=text_blocks())
def test_every_readable_word_is_rendered(items: list[Block]) -> None:
    # Principle 3: escaping and prefixes add marks, never drop or change words.
    out = _visible_words(render(items))
    for item in items:
        if item.removed:
            continue
        for word in item.text.replace("\\", "").split():
            assert any(word in w for w in out)


@pytest.mark.invariant
@given(items=text_blocks())
def test_rendering_is_deterministic_and_invents_no_marker(items: list[Block]) -> None:
    # Principles 4 and 6: no unreadable marker appears unless a block is illegible.
    out = render(items)
    assert out == render(items)
    assert not re.search(r"(?<!\\)\[illegible\]", out)


# --- End to end: screenshot → OCR → cleaner → Markdown -----------------------


def test_chat_screenshot_to_markdown() -> None:
    width, height = 750, 1334
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=30)
    draw.text((30, 20), "9:41", fill="black", font=font)
    draw.text((640, 20), "87%", fill="black", font=font)
    bubbles = [("left", "Hello, are we meeting tomorrow?"), ("right", "Yes, at six")]
    for n, (side, text) in enumerate(bubbles * 2):
        y = 200 + n * 160
        text_width = draw.textlength(text, font=font)
        x = 40 if side == "left" else width - 40 - text_width
        draw.text((x, y), text, fill="black", font=font)
    buffer = BytesIO()
    image.save(buffer, format="PNG")

    page = extract_page(buffer.getvalue(), OcrEngine(*bundled_models()))
    cleaner = UiChromeCleaner()
    page = apply_decisions(page, cleaner.propose(page), cleaner=cleaner.name)
    expected = "\n".join(f"{side}: {text}" for side, text in bubbles * 2)
    assert render(page.blocks) == expected
