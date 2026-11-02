"""Tests for text edits: the core checks each edit's kind mechanically, applies
all of a cleaner's edits or none, and records them so they can be undone
(principles 3 and 4, ADR-050)."""

import time
from itertools import pairwise

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from sugo.core.constants import MAX_EDITS_PER_BLOCK, MAX_EDITS_PER_PAGE
from sugo.core.decisions import (
    Decision,
    EditDecision,
    InvalidDecisionError,
    apply_decisions,
    within_limits,
)
from sugo.core.models import Block, BlockFlag, BlockType, EditKind, Page, PageOrigin, TextEdit
from sugo.core.text import visible

NBSP = chr(0xA0)
FI = chr(0xFB01)
SOFT_HYPHEN = chr(0xAD)
ZWSP = chr(0x200B)


def page(*texts: str) -> Page:
    blocks = tuple(
        Block(id=f"b{n}", type=BlockType.PARAGRAPH, text=text, origin_engine="t")
        for n, text in enumerate(texts)
    )
    return Page(index=0, width=100, height=100, origin=PageOrigin.NATIVE, blocks=blocks)


def edit(start: int, end: int, replacement: str, kind: EditKind, block: str = "b0") -> EditDecision:
    return EditDecision(
        block_id=block, start=start, end=end, replacement=replacement, kind=kind, reason="r"
    )


def applied(text: str, *edits: EditDecision) -> Block:
    return apply_decisions(page(text), edits, cleaner="c").blocks[0]


class TestKinds:
    def test_delete_removes_a_span_and_records_it(self) -> None:
        block = applied("see a.b/x?utm_source=n now", edit(9, 22, "", EditKind.DELETE))
        assert block.text == "see a.b/x now"
        assert block.edits == (
            TextEdit(
                start=9,
                end=22,
                original="?utm_source=n",
                replacement="",
                kind=EditKind.DELETE,
                edited_by="c",
                reason="r",
            ),
        )

    def test_delete_must_not_replace(self) -> None:
        with pytest.raises(InvalidDecisionError, match="not a valid delete"):
            applied("abc", edit(0, 1, "x", EditKind.DELETE))

    @pytest.mark.parametrize(
        ("text", "start", "end", "replacement"),
        [
            (f"de{FI}ne", 2, 3, "fi"),
            (f"a{NBSP}b", 1, 2, " "),
            ("a   b", 1, 4, " "),
            (f"in{ZWSP}fo", 2, 3, ""),
            ("cafe" + chr(0x301), 3, 5, "é"),
            ("dell' albero", 5, 6, ""),
        ],
    )
    def test_normalize_keeps_every_visible_character(
        self, text: str, start: int, end: int, replacement: str
    ) -> None:
        block = applied(text, edit(start, end, replacement, EditKind.NORMALIZE))
        assert visible(block.text) == visible(text)

    @pytest.mark.parametrize(
        ("text", "start", "end", "replacement"),
        [
            ("e' vero", 0, 2, "è"),  # a letter changes: a guess, not a normalisation
            ("m" + chr(0xB2), 1, 2, "2"),  # "m²" is not "m2"
            ("ab", 0, 1, "x"),
            ("a b", 1, 2, " not "),
            ("now here", 3, 4, ""),  # joins two words: "nowhere"
            ("one two", 3, 4, "\n\n    "),  # opens a paragraph and a code block
            ("one two", 3, 4, "\t"),  # other whitespace
            ("a  b", 1, 3, "\n "),  # a new line break
            ("xy z", 0, 4, "x yz"),  # splits a word
        ],
    )
    @pytest.mark.invariant
    def test_normalize_refuses_any_visible_change(
        self, text: str, start: int, end: int, replacement: str
    ) -> None:
        with pytest.raises(InvalidDecisionError, match="not a valid normalize"):
            applied(text, edit(start, end, replacement, EditKind.NORMALIZE))

    @pytest.mark.parametrize("hyphen", ["-", chr(0x2010), chr(0x2011), SOFT_HYPHEN])
    def test_hyphen_join_removes_hyphen_and_line_break(self, hyphen: str) -> None:
        block = applied(f"infor{hyphen}\nmation", edit(5, 7, "", EditKind.HYPHEN_JOIN))
        assert block.text == "information"

    @pytest.mark.parametrize(
        ("text", "start", "end"),
        [
            ("infor-mation", 5, 6),  # no line break
            ("2024-\n2025", 4, 6),  # digits, not letters
            ("word -\nnext", 5, 7),  # space before the hyphen: not inside a word
            ("infor-\nmation", 4, 7),  # takes a letter too
            ("end-\n", 3, 5),  # nothing after
        ],
    )
    @pytest.mark.invariant
    def test_hyphen_join_refuses_anything_else(self, text: str, start: int, end: int) -> None:
        with pytest.raises(InvalidDecisionError, match="not a valid hyphen_join"):
            applied(text, edit(start, end, "", EditKind.HYPHEN_JOIN))


class TestValidation:
    @pytest.mark.parametrize(("start", "end"), [(2, 2), (3, 2), (0, 99)])
    def test_empty_or_out_of_range_spans_are_refused(self, start: int, end: int) -> None:
        # An empty span would be an insertion: text the source never had.
        with pytest.raises(InvalidDecisionError, match="outside the text or empty"):
            applied("abcd", edit(start, end, "", EditKind.DELETE))

    def test_overlapping_edits_are_refused(self) -> None:
        with pytest.raises(InvalidDecisionError, match="overlap"):
            applied("abcdef", edit(0, 3, "", EditKind.DELETE), edit(2, 4, "", EditKind.DELETE))

    def test_one_invalid_edit_means_none_is_applied(self) -> None:
        original = page("abcdef", "xyz")
        with pytest.raises(InvalidDecisionError):
            apply_decisions(
                original,
                [
                    edit(0, 1, "", EditKind.DELETE),
                    edit(0, 1, "q", EditKind.NORMALIZE, block="b1"),
                ],
                cleaner="c",
            )
        assert original.blocks[0].text == "abcdef"

    def test_edit_of_unknown_block_is_refused(self) -> None:
        with pytest.raises(InvalidDecisionError, match="not on the page"):
            applied("abc", edit(0, 1, "", EditKind.DELETE, block="zz"))

    def test_edit_of_removed_block_is_refused(self) -> None:
        removed = apply_decisions(page("abc"), [Decision(block_id="b0", reason="r")], cleaner="c")
        with pytest.raises(InvalidDecisionError, match="already removed"):
            apply_decisions(removed, [edit(0, 1, "", EditKind.DELETE)], cleaner="d")

    def test_block_both_removed_and_edited_is_refused(self) -> None:
        with pytest.raises(InvalidDecisionError, match="both removed and edited"):
            apply_decisions(
                page("abc"),
                [Decision(block_id="b0", reason="r"), edit(0, 1, "", EditKind.DELETE)],
                cleaner="c",
            )

    def test_same_cleaner_cannot_edit_a_block_twice(self) -> None:
        # Its edits are undone as one batch: a second batch would undo wrongly.
        once = apply_decisions(page("a  b  c"), [edit(1, 3, " ", EditKind.NORMALIZE)], cleaner="c")
        with pytest.raises(InvalidDecisionError, match="already edited by this cleaner"):
            apply_decisions(once, [edit(3, 5, " ", EditKind.NORMALIZE)], cleaner="c")

    def test_words_may_join_after_an_apostrophe_or_hyphen(self) -> None:
        assert applied("dell' albero", edit(5, 6, "", EditKind.NORMALIZE)).text == "dell'albero"
        assert applied("well-\nknown", edit(4, 6, "-", EditKind.NORMALIZE)).text == "well-known"

    def test_errors_never_quote_the_text(self) -> None:
        with pytest.raises(InvalidDecisionError) as error:
            applied("secret words", edit(0, 6, "public", EditKind.NORMALIZE))
        assert "secret" not in str(error.value)
        assert "public" not in str(error.value)

    def test_edit_decision_rejects_unknown_fields(self) -> None:
        with pytest.raises(ValidationError):
            EditDecision.model_validate(
                {
                    "block_id": "b0",
                    "start": 0,
                    "end": 1,
                    "replacement": "",
                    "kind": "delete",
                    "reason": "r",
                    "edited_by": "someone else",
                }
            )


class TestRecords:
    def test_text_edit_span_must_match_original(self) -> None:
        with pytest.raises(ValidationError):
            TextEdit(
                start=0,
                end=3,
                original="ab",
                replacement="",
                kind=EditKind.DELETE,
                edited_by="c",
                reason="r",
            )

    def test_illegible_block_cannot_carry_edits(self) -> None:
        record = TextEdit(
            start=0,
            end=1,
            original="a",
            replacement="",
            kind=EditKind.DELETE,
            edited_by="c",
            reason="r",
        )
        with pytest.raises(ValidationError):
            Block(
                id="b",
                type=BlockType.PARAGRAPH,
                origin_engine="t",
                flags=(BlockFlag.ILLEGIBLE,),
                edits=(record,),
            )

    def test_edits_of_several_cleaners_are_undone_in_order(self) -> None:
        first = apply_decisions(
            page(f"a{NBSP}{NBSP}b infor-\nmation"),
            [edit(1, 3, " ", EditKind.NORMALIZE), edit(10, 12, "", EditKind.HYPHEN_JOIN)],
            cleaner="one",
        )
        assert first.blocks[0].text == "a b information"
        second = apply_decisions(first, [edit(0, 2, "", EditKind.DELETE)], cleaner="two")
        block = second.blocks[0]
        assert block.text == "b information"
        assert [e.edited_by for e in block.edits] == ["one", "one", "two"]
        assert block.original_text() == f"a{NBSP}{NBSP}b infor-\nmation"


_PIECES = st.sampled_from(["ab", " ", "  ", NBSP, FI, ZWSP, "x-\ny", "\n", "é", "q"])


@pytest.mark.invariant
@given(st.lists(_PIECES, min_size=1, max_size=12), st.data())
def test_any_accepted_edits_can_be_undone(pieces: list[str], data: st.DataObject) -> None:
    """Principle 3: whatever the core accepts, the original text can be rebuilt."""
    text = "".join(pieces)
    cut = sorted(data.draw(st.sets(st.integers(0, len(text)), max_size=6)))
    spans = [(a, b) for a, b in pairwise(cut) if a < b][::2]
    decisions = [edit(a, b, "", EditKind.DELETE) for a, b in spans]
    if not decisions:
        return
    block = applied(text, *decisions)
    assert block.original_text() == text
    assert len(block.edits) == len(decisions)


class TestLimits:
    def test_too_many_edits_for_a_block_are_refused(self) -> None:
        text = "a " * (MAX_EDITS_PER_BLOCK + 1)
        edits = [edit(2 * n + 1, 2 * n + 2, "", EditKind.DELETE) for n in range(len(text) // 2)]
        with pytest.raises(InvalidDecisionError, match="too many edits"):
            applied(text, *edits)

    def test_within_limits_leaves_an_oversized_block_and_stops_at_the_page_limit(self) -> None:
        small = [edit(0, 1, "", EditKind.DELETE, block="small")]
        huge = [edit(0, 1, "", EditKind.DELETE, block="huge")] * (MAX_EDITS_PER_BLOCK + 1)
        assert within_limits([huge, small]) == small
        full = [[edit(0, 1, "", EditKind.DELETE, block=f"b{n}")] * 2_000 for n in range(6)]
        assert len(within_limits(full)) == MAX_EDITS_PER_PAGE

    def test_many_edits_stay_fast(self) -> None:
        text = "word  " * 1_500
        edits = [edit(6 * n + 4, 6 * n + 6, " ", EditKind.NORMALIZE) for n in range(1_500)]
        start = time.perf_counter()
        block = applied(text, *edits)
        assert time.perf_counter() - start < 2
        assert block.original_text() == text
