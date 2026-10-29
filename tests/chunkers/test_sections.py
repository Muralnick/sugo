"""Tests for the section chunker: sections, size limit, splitting, ids and no lost text."""

from collections.abc import Sequence

from hypothesis import given, settings
from hypothesis import strategies as st

from sugo.chunkers.sections import SectionChunker, document_id
from sugo.core.chunks import Chunk
from sugo.core.models import Block, BlockFlag, BlockType, Page, PageOrigin, Table, TableCell
from sugo.metrics.tokenizer import count_tokens
from sugo.serializers.markdown import render

SHA = "a" * 64
CONFIG = "b" * 64


def heading(block_id: str, text: str, level: int = 1) -> Block:
    return Block(
        id=block_id, type=BlockType.HEADING, text=text, heading_level=level, origin_engine="t"
    )


def para(block_id: str, text: str) -> Block:
    return Block(id=block_id, type=BlockType.PARAGRAPH, text=text, origin_engine="t")


def page(index: int, *blocks: Block) -> Page:
    return Page(index=index, width=595, height=842, origin=PageOrigin.NATIVE, blocks=blocks)


def chunk(
    pages: Sequence[Page], *, max_tokens: int = 512, source: str | None = "doc.pdf", sha: str = SHA
) -> list[Chunk]:
    chunker = SectionChunker(
        source=source,
        source_sha256=sha,
        sugo_version="0.0.0",
        config_hash=CONFIG,
        max_tokens=max_tokens,
    )
    out = [c for p in pages for c in chunker.add(p)]
    return out + list(chunker.finish())


def words(text: str) -> list[str]:
    return text.split()


def test_sections_become_chunks_with_their_heading_path() -> None:
    chunks = chunk(
        [
            page(0, heading("h1", "Agreement"), heading("h2", "Art. 1", 2), para("p1", "First.")),
            page(1, heading("h3", "Art. 2", 2), para("p2", "Second.")),
        ]
    )
    assert [(c.text, c.heading_path, c.pages) for c in chunks] == [
        ("# Agreement\n\n## Art. 1\n\nFirst.", ("Agreement", "Art. 1"), (1,)),
        ("## Art. 2\n\nSecond.", ("Agreement", "Art. 2"), (2,)),
    ]


def test_chunk_spanning_a_page_break_lists_both_pages() -> None:
    (only,) = chunk([page(3, para("a", "Start of a thought")), page(4, para("b", "and its end."))])
    assert only.pages == (4, 5)


def test_removed_blocks_are_left_out_like_in_the_markdown() -> None:
    gone = para("x", "Page 3").mark_removed("page_numbers", "page number")
    (only,) = chunk([page(0, para("a", "Kept."), gone)])
    assert only.text == "Kept."


def test_illegible_blocks_stay_marked() -> None:
    blank = Block(id="i", type=BlockType.PARAGRAPH, origin_engine="t", flags=(BlockFlag.ILLEGIBLE,))
    (only,) = chunk([page(0, para("a", "Before."), blank)])
    assert only.text == "Before.\n\n[illegible]"


def test_blocks_fill_chunks_up_to_the_limit() -> None:
    sentence = "This sentence has about ten tokens in it, more or less."
    chunks = chunk([page(0, *(para(f"p{n}", sentence) for n in range(30)))], max_tokens=64)
    assert len(chunks) > 1
    assert all(c.tokens <= 64 for c in chunks)
    assert all(c.tokens == count_tokens(c.text) for c in chunks)


def test_long_paragraph_is_split_at_sentences() -> None:
    text = " ".join(f"Sentence number {n} is here." for n in range(60))
    chunks = chunk([page(0, para("p", text))], max_tokens=40)
    assert all(c.tokens <= 40 for c in chunks)
    assert all(c.text.endswith(".") for c in chunks)
    assert words(" ".join(c.text for c in chunks)) == words(text)


def test_word_longer_than_the_limit_is_cut() -> None:
    blob = "Z" * 3000
    chunks = chunk([page(0, para("p", blob))], max_tokens=40)
    assert all(c.tokens <= 40 for c in chunks)
    assert "".join(c.text for c in chunks) == blob


def test_long_code_is_split_at_lines_and_stays_fenced() -> None:
    code = "\n".join(f"value_{n} = compute({n})" for n in range(80))
    block = Block(id="c", type=BlockType.CODE, text=code, origin_engine="t")
    chunks = chunk([page(0, block)], max_tokens=64)
    assert len(chunks) > 1
    assert all(c.tokens <= 64 for c in chunks)
    assert all(c.text.startswith("```\n") and c.text.endswith("\n```") for c in chunks)
    lines = [line for c in chunks for line in c.text.splitlines() if line != "```"]
    assert lines == code.splitlines()


def test_table_is_never_split() -> None:
    cells = tuple(
        TableCell(row=r, col=c, text=f"cell {r} {c} with some words")
        for r in range(20)
        for c in range(3)
    )
    table = Block(
        id="t",
        type=BlockType.TABLE,
        table=Table(n_rows=20, n_cols=3, cells=cells),
        origin_engine="t",
    )
    chunks = chunk([page(0, para("a", "Before."), table, para("b", "After."))], max_tokens=64)
    assert [c.tokens > 64 for c in chunks] == [False, True, False]


def test_heading_at_the_end_is_kept() -> None:
    chunks = chunk([page(0, para("a", "Text."), heading("h", "Appendix"))])
    assert [c.text for c in chunks] == ["Text.", "# Appendix"]


def test_ids_are_stable_and_distinct() -> None:
    pages = [page(0, para("a", "Same text."), heading("h", "Next"), para("b", "Same text."))]
    first = chunk(pages)
    assert [c.id for c in first] == [c.id for c in chunk(pages)]
    assert len({c.id for c in first}) == len(first)


def test_new_edition_keeps_the_ids_of_unchanged_chunks() -> None:
    old = chunk(
        [
            page(0, heading("h1", "One"), para("a", "Unchanged.")),
            page(1, heading("h2", "Two"), para("b", "Old.")),
        ],
        sha="1" * 64,
    )
    new = chunk(
        [
            page(0, heading("h1", "One"), para("a", "Unchanged.")),
            page(1, heading("h2", "Two"), para("b", "New.")),
        ],
        sha="2" * 64,
    )
    assert old[0].id == new[0].id
    assert old[1].id != new[1].id
    assert old[0].document_id == new[0].document_id


def test_same_text_in_another_document_has_another_id() -> None:
    pages = [page(0, para("a", "Shared paragraph."))]
    assert chunk(pages, source="a.pdf")[0].id != chunk(pages, source="b.pdf")[0].id


def test_document_without_a_name_is_identified_by_content() -> None:
    assert document_id(None, SHA) != document_id(None, "c" * 64)
    assert document_id("doc.pdf", SHA) == document_id("doc.pdf", "c" * 64)


def test_empty_document_has_no_chunks() -> None:
    assert chunk([page(0)]) == []


_TEXT = st.text(
    alphabet=st.characters(categories=["L", "N", "P", "Zs"], exclude_characters="\\`*_#[]<>|"),
    min_size=1,
    max_size=400,
).filter(lambda text: text.strip() != "")


@settings(max_examples=40, deadline=None)
@given(st.lists(_TEXT, min_size=1, max_size=8), st.integers(min_value=32, max_value=120))
def test_no_text_is_lost_and_no_chunk_is_too_big(texts: list[str], max_tokens: int) -> None:
    blocks = [para(f"p{n}", text) for n, text in enumerate(texts)]
    chunks = chunk([page(0, *blocks)], max_tokens=max_tokens)
    assert all(c.tokens <= max_tokens for c in chunks)

    # Every character of the Markdown output is in the chunks, in order
    # (principle 3). A piece cut mid-line may start with a character that
    # Markdown needs escaped there, so escape backslashes are set aside; the
    # alphabet has no backslash of its own.
    def letters(text: str) -> str:
        return "".join(words(text)).replace("\\", "")

    assert letters(" ".join(c.text for c in chunks)) == letters(render(blocks))


def test_long_word_before_others_is_cut_within_the_limit() -> None:
    chunks = chunk([page(0, para("p", "x" * 600 + " b c d"))], max_tokens=40)
    assert all(c.tokens <= 40 for c in chunks)
    assert "".join(c.text for c in chunks).replace(" ", "") == "x" * 600 + "bcd"


def test_split_keeps_cjk_text_exactly() -> None:
    text = "这是第一句话。" * 60
    chunks = chunk([page(0, para("p", text))], max_tokens=40)
    assert len(chunks) > 1
    assert "".join(c.text for c in chunks) == text


def test_split_keeps_line_breaks() -> None:
    text = "\n".join(f"Address line {n}, Street {n}" for n in range(40))
    chunks = chunk([page(0, para("p", text))], max_tokens=40)
    assert len(chunks) > 1
    assert "\n".join(c.text for c in chunks) == text


def test_heading_stays_with_a_long_first_paragraph() -> None:
    long = " ".join(f"Sentence {n} of the opening paragraph." for n in range(40))
    chunks = chunk([page(0, heading("h", "Introduction"), para("p", long))], max_tokens=64)
    assert chunks[0].text.startswith("# Introduction\n\nSentence 0")
    assert all(c.tokens <= 64 for c in chunks)
    assert not any(c.text == "# Introduction" for c in chunks)


def test_heading_stays_with_a_paragraph_that_fits_only_alone() -> None:
    sentence = "Words that fill the chunk almost to the limit. " * 5
    chunks = chunk(
        [page(0, heading("h", "Title of the section"), para("p", sentence))], max_tokens=60
    )
    assert chunks[0].text.startswith("# Title of the section\n\nWords")
    assert all(c.tokens <= 60 for c in chunks)


def test_split_list_item_stays_one_item() -> None:
    item = Block(
        id="l",
        type=BlockType.LIST_ITEM,
        text=" ".join(f"Point {n} of a very long bullet." for n in range(30)),
        origin_engine="t",
    )
    chunks = chunk([page(0, item)], max_tokens=40)
    assert len(chunks) > 1
    assert [c.text.startswith("- ") for c in chunks] == [True] + [False] * (len(chunks) - 1)


def test_heading_path_names_every_heading_in_the_chunk() -> None:
    chunks = chunk([page(0, heading("a", "A", 2), heading("b", "B", 1), para("p", "Text."))])
    assert [(c.text, c.heading_path) for c in chunks] == [
        ("## A", ("A",)),
        ("# B\n\nText.", ("B",)),
    ]


_PLAIN = st.text(
    alphabet=st.sampled_from([*"abcdefgh ,.!?\n", "这", "。"]), min_size=1, max_size=600
)


@settings(max_examples=40, deadline=None)
@given(_PLAIN.filter(lambda text: text.strip() != ""), st.integers(min_value=32, max_value=80))
def test_pieces_are_exact_slices_of_the_paragraph(text: str, max_tokens: int) -> None:
    chunks = chunk([page(0, para("p", text))], max_tokens=max_tokens)
    rendered = render([para("p", text)])
    position = 0
    for c in chunks:
        found = rendered.index(c.text, position)
        # Only whitespace is dropped, and only between pieces.
        assert rendered[position:found].strip() == ""
        position = found + len(c.text)
    assert rendered[position:].strip() == ""
    assert all(c.tokens <= max_tokens for c in chunks)
