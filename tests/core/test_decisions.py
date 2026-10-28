"""Tests for cleaner decisions: the core validates them as a whole and applies
them as soft deletions only (principle 3, ADR-041)."""

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from sugo.core.decisions import Decision, InvalidDecisionError, apply_decisions
from sugo.core.models import Block, BlockType, Page, PageOrigin


def page(*ids: str) -> Page:
    blocks = tuple(
        Block(id=i, type=BlockType.PARAGRAPH, text=f"text {i}", origin_engine="t") for i in ids
    )
    return Page(index=0, width=100, height=100, origin=PageOrigin.OCR, blocks=blocks)


class TestDecision:
    def test_reason_is_required(self) -> None:
        with pytest.raises(ValidationError):
            Decision(block_id="b1", reason="")

    def test_unknown_fields_are_rejected(self) -> None:
        # A cleaner cannot slip in other changes, e.g. new text (principle 4).
        with pytest.raises(ValidationError):
            Decision.model_validate({"block_id": "b1", "reason": "r", "text": "new"})

    def test_is_immutable(self) -> None:
        decision = Decision(block_id="b1", reason="r")
        with pytest.raises(ValidationError):
            decision.reason = "other"  # type: ignore[misc]


class TestApplyDecisions:
    def test_marks_block_removed_with_cleaner_and_reason(self) -> None:
        out = apply_decisions(page("a", "b"), [Decision(block_id="b", reason="noise")], cleaner="c")
        a, b = out.blocks
        assert not a.removed
        assert (b.removed, b.removed_by, b.reason, b.text) == (True, "c", "noise", "text b")

    def test_original_page_is_unchanged(self) -> None:
        original = page("a")
        apply_decisions(original, [Decision(block_id="a", reason="r")], cleaner="c")
        assert not original.blocks[0].removed

    def test_no_decisions_returns_an_equal_page(self) -> None:
        assert apply_decisions(page("a", "b"), [], cleaner="c") == page("a", "b")

    def test_unknown_block_is_refused(self) -> None:
        with pytest.raises(InvalidDecisionError, match="not on the page") as error:
            apply_decisions(page("a"), [Decision(block_id="zz", reason="r")], cleaner="c")
        assert error.value.cleaner == "c"

    def test_same_block_twice_is_refused(self) -> None:
        decisions = [Decision(block_id="a", reason="r1"), Decision(block_id="a", reason="r2")]
        with pytest.raises(InvalidDecisionError, match="more than once"):
            apply_decisions(page("a"), decisions, cleaner="c")

    def test_already_removed_block_is_refused(self) -> None:
        once = apply_decisions(page("a"), [Decision(block_id="a", reason="r")], cleaner="first")
        with pytest.raises(InvalidDecisionError, match="already removed"):
            apply_decisions(once, [Decision(block_id="a", reason="r")], cleaner="second")

    def test_one_invalid_decision_blocks_all_of_them(self) -> None:
        decisions = [Decision(block_id="a", reason="r"), Decision(block_id="zz", reason="r")]
        with pytest.raises(InvalidDecisionError):
            apply_decisions(page("a"), decisions, cleaner="c")

    def test_error_message_does_not_contain_block_ids(self) -> None:
        # Principle 11: ids may one day carry document text; messages stay generic.
        with pytest.raises(InvalidDecisionError) as error:
            apply_decisions(page("a"), [Decision(block_id="secret-id", reason="r")], cleaner="c")
        assert "secret-id" not in str(error.value)

    def test_empty_cleaner_name_is_refused(self) -> None:
        with pytest.raises(ValueError, match="cleaner name"):
            apply_decisions(page("a"), [Decision(block_id="a", reason="r")], cleaner="")


@pytest.mark.invariant
@given(
    ids=st.lists(st.text(min_size=1, max_size=8), min_size=1, max_size=10, unique=True),
    data=st.data(),
)
def test_applying_decisions_never_deletes_or_rewrites(ids: list[str], data: st.DataObject) -> None:
    # Principle 3: every block survives, with its text, and every removal has a reason.
    original = page(*ids)
    chosen = data.draw(st.lists(st.sampled_from(ids), unique=True))
    decisions = [Decision(block_id=i, reason="noise") for i in chosen]
    out = apply_decisions(original, decisions, cleaner="c")
    assert [(b.id, b.text) for b in out.blocks] == [(b.id, b.text) for b in original.blocks]
    assert {b.id for b in out.blocks if b.removed} == set(chosen)
    assert all(b.removed_by == "c" and b.reason == "noise" for b in out.blocks if b.removed)
