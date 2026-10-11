from pathlib import Path

import pytest

from app.ingestion.chunking import chunk_document, estimate_tokens
from app.ingestion.loaders import Block, ParsedDocument, load_file
from scripts.render_docs import DOCS_DIR


def doc(*blocks: Block) -> ParsedDocument:
    return ParsedDocument(source="t", title="Guide", doc_type="manual", blocks=list(blocks))


def h(text: str, level: int) -> Block:
    return Block("heading", text, level=level)


def t(text: str) -> Block:
    return Block("text", text)


def sentence(i: int) -> str:
    return f"Sentence number {i} explains one specific detail about the product clearly."


def test_one_chunk_per_section_with_heading_path():
    chunks = chunk_document(
        doc(h("Guide", 1), t("Intro."), h("Setup", 2), t("Plug in."),
            h("Lights", 3), t("Green is ready."), h("Care", 2), t("Keep dry."))
    )  # fmt: skip

    assert [(c.heading, c.content) for c in chunks] == [
        ("Guide", "Intro."),
        ("Guide > Setup", "Plug in."),
        ("Guide > Setup > Lights", "Green is ready."),
        ("Guide > Care", "Keep dry."),
    ]
    assert [c.index for c in chunks] == [0, 1, 2, 3]
    assert chunks[2].embed_text == "Guide > Setup > Lights\n\nGreen is ready."


def test_heading_without_body_is_folded_into_its_subsections():
    chunks = chunk_document(doc(h("Features", 2), h("Battery", 3), t("40 hours.")))
    assert [c.heading for c in chunks] == ["Guide > Features > Battery"]


def test_long_section_is_split_with_overlap():
    blocks = [h("Long", 2)] + [t(sentence(i)) for i in range(20)]
    chunks = chunk_document(doc(*blocks), max_tokens=100, overlap_tokens=40)

    assert len(chunks) > 1
    assert all(c.token_count <= 100 for c in chunks)
    assert all(c.heading == "Guide > Long" for c in chunks)
    for prev, nxt in zip(chunks, chunks[1:], strict=False):
        prev_paras, next_paras = prev.content.split("\n\n"), nxt.content.split("\n\n")
        shared = [p for p in next_paras if p in prev_paras]
        # The overlap is the tail of the previous chunk, at the start of the next, within budget
        assert shared, "consecutive chunks must overlap"
        assert next_paras[: len(shared)] == shared == prev_paras[-len(shared) :]
        assert sum(estimate_tokens(p) for p in shared) <= 40
    # Nothing is lost: every sentence appears in some chunk
    joined = " ".join(c.content for c in chunks)
    assert all(sentence(i) in joined for i in range(20))


def test_overlap_zero_means_no_repeated_text():
    blocks = [h("Long", 2)] + [t(sentence(i)) for i in range(20)]
    chunks = chunk_document(doc(*blocks), max_tokens=100, overlap_tokens=0)
    paragraphs = [p for c in chunks for p in c.content.split("\n\n")]
    assert len(paragraphs) == len(set(paragraphs)) == 20


def test_oversized_paragraph_is_split_by_sentence():
    big = " ".join(sentence(i) for i in range(30))
    chunks = chunk_document(doc(h("Big", 2), t(big)), max_tokens=100, overlap_tokens=0)

    assert len(chunks) > 1
    assert all(c.token_count <= 100 for c in chunks)
    assert all(c.content.endswith(".") for c in chunks), "splits happen between sentences"


def test_giant_sentence_without_punctuation_is_hard_split():
    chunks = chunk_document(doc(h("X", 2), t("word " * 500)), max_tokens=100, overlap_tokens=0)
    assert len(chunks) > 1 and all(c.token_count <= 100 for c in chunks)


def test_large_table_is_split_by_rows_with_header_repeated():
    rows = "\n".join(f"| Problem {i} | Try solution number {i} and restart |" for i in range(40))
    table = Block("table", f"| Problem | Solution |\n| --- | --- |\n{rows}")
    chunks = chunk_document(doc(h("Troubleshooting", 2), table), max_tokens=120)

    assert len(chunks) > 1
    for c in chunks:
        assert c.content.startswith("| Problem | Solution |\n| --- | --- |\n| Problem")
        assert c.token_count <= 120
    body_rows = [r for c in chunks for r in c.content.splitlines()[2:]]
    assert body_rows == rows.splitlines(), "every row exactly once, in order, never overlapped"


def test_tables_are_never_repeated_as_overlap():
    table = Block("table", "| A | B |\n| --- | --- |\n| 1 | 2 |")
    blocks = [h("S", 2), t(sentence(1)), table] + [t(sentence(i)) for i in range(2, 12)]
    chunks = chunk_document(doc(*blocks), max_tokens=80, overlap_tokens=60)
    assert sum(c.content.count("| A | B |") for c in chunks) == 1


def test_page_of_first_block_is_kept():
    chunks = chunk_document(doc(h("S", 2), Block("text", "On page three.", page=3)))
    assert chunks[0].page == 3


def test_chunking_is_deterministic():
    blocks = [h("Long", 2)] + [t(sentence(i)) for i in range(20)]
    assert chunk_document(doc(*blocks), 100, 40) == chunk_document(doc(*blocks), 100, 40)


def test_estimate_tokens_is_about_four_characters_each():
    assert estimate_tokens("") == 1
    assert estimate_tokens("a" * 400) == 100


REAL_DOCS = sorted(p for p in DOCS_DIR.iterdir() if p.suffix in (".pdf", ".docx", ".html"))


@pytest.mark.parametrize("path", REAL_DOCS, ids=lambda p: p.name)
def test_real_documents_chunk_cleanly(path: Path):
    parsed = load_file(path, path.name)
    chunks = chunk_document(parsed, max_tokens=600, overlap_tokens=80)

    assert chunks
    assert [c.index for c in chunks] == list(range(len(chunks)))
    assert all(c.content.strip() and c.token_count <= 600 for c in chunks)
    assert all(c.heading.startswith(parsed.title) for c in chunks)
    joined = "\n".join(c.content for c in chunks)
    lost = [b.text[:60] for b in parsed.blocks if b.kind != "heading" and b.text not in joined]
    assert not lost, f"blocks missing from chunks: {lost}"
