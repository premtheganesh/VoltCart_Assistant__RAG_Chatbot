"""Parsing quality: every heading, paragraph and table cell of the source survives extraction."""

import re

import pytest

from app.ingestion.loaders import load_file, normalize_space, table_to_markdown
from scripts.render_docs import (
    DOCS_DIR,
    SOURCE_DIR,
    read_source,
    render_docx,
    render_html,
    render_pdf,
)

FORMATS = {"manuals": ".pdf", "guides": ".docx", "helpcenter": ".html"}
SOURCES = [p for folder in FORMATS for p in sorted((SOURCE_DIR / folder).glob("*.md"))]


def plain(markdown: str) -> str:
    """Markdown inline formatting -> the text a reader sees."""
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", markdown)
    return normalize_space(re.sub(r"\*\*|\*|`", "", text))


def rendered(source) -> object:
    path = DOCS_DIR / f"{source.stem}{FORMATS[source.parent.name]}"
    return load_file(path, path.name)


def flat(doc) -> str:
    return normalize_space(" ".join(b.text.replace("|", " ") for b in doc.blocks))


@pytest.mark.parametrize("source", SOURCES, ids=lambda p: p.name)
def test_metadata_is_extracted(source):
    src, doc = read_source(source), rendered(source)

    assert doc.title == src.title
    assert doc.doc_type == src.meta["doc_type"]
    if source.parent.name != "helpcenter":  # HTML pages carry no product list
        assert doc.products == [s.strip() for s in src.meta["products"].split(",") if s.strip()]
    if source.parent.name != "manuals":  # PDFs from the renderer carry no real date
        assert str(doc.updated) == src.meta["updated"]
    if source.parent.name == "helpcenter":
        assert doc.url == f"https://voltcart.example/help/{source.stem}"


@pytest.mark.parametrize("source", SOURCES, ids=lambda p: p.name)
def test_headings_keep_their_order_and_level(source):
    expected = [
        (len(m.group(1)), plain(m.group(2)))
        for m in re.finditer(r"^(#{1,3}) (.+)$", read_source(source).body, flags=re.M)
    ]
    got = [(b.level, b.text) for b in rendered(source).blocks if b.kind == "heading"]
    assert got == expected


@pytest.mark.parametrize("source", SOURCES, ids=lambda p: p.name)
def test_no_text_is_lost(source):
    """Every paragraph, list item and table cell from the source is in the extracted text."""
    text = flat(rendered(source))
    missing = []
    for line in read_source(source).body.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or re.fullmatch(r"\|[\s|:-]+\|", line):
            continue
        if line.startswith("|"):
            pieces = [plain(cell) for cell in line.strip("|").split("|")]
        else:
            pieces = [plain(re.sub(r"^(\d+\.|-)\s+", "", line))]
        missing += [p for p in pieces if p and p not in text]
    assert not missing, f"lost in extraction: {missing[:5]}"


@pytest.mark.parametrize("source", SOURCES, ids=lambda p: p.name)
def test_tables_stay_tables(source):
    src_tables = len(re.findall(r"^\|[\s|:-]+\|$", read_source(source).body, flags=re.M))
    tables = [b for b in rendered(source).blocks if b.kind == "table"]
    # A PDF table that crosses a page break comes out as two pieces
    assert len(tables) >= src_tables
    assert all(b.text.splitlines()[1].startswith("| ---") for b in tables)


@pytest.mark.parametrize("source", SOURCES, ids=lambda p: p.name)
def test_site_and_page_chrome_is_removed(source):
    text = flat(rendered(source))
    assert "VoltCart |" not in text  # PDF running header
    assert not re.search(r"Page \d+", text)  # PDF footer
    assert "All rights reserved" not in text  # HTML footer
    assert "Help Center ›" not in text  # HTML breadcrumb


SAMPLE = """# Widget Guide

Intro with **bold** text and a [link](https://example.com).

## Setup

1. Plug it in
2. Press the button for 16 seconds

16 GB of memory is a number, not a list item.

### Lights

- Green means ready
- Red means error

| Light | Meaning |
| --- | --- |
| Green | Ready |
| Red | Error |

## Care

Keep it dry.
"""

EXPECTED = [
    ("heading", 1, "Widget Guide"),
    ("text", 0, "Intro with bold text and a link."),
    ("heading", 2, "Setup"),
    ("text", 0, "1. Plug it in\n2. Press the button for 16 seconds"),
    ("text", 0, "16 GB of memory is a number, not a list item."),
    ("heading", 3, "Lights"),
    ("text", 0, "- Green means ready\n- Red means error"),
    ("table", 0, "| Light | Meaning |\n| --- | --- |\n| Green | Ready |\n| Red | Error |"),
    ("heading", 2, "Care"),
    ("text", 0, "Keep it dry."),
]


@pytest.mark.parametrize(
    "render", [render_pdf, render_docx, render_html], ids=["pdf", "docx", "html"]
)
def test_every_format_parses_to_the_same_blocks(tmp_path, render):
    src = tmp_path / "widget.md"
    src.write_text(
        "---\ntitle: Widget Guide\ndoc_type: manual\nupdated: 2026-09-01\n---\n" + SAMPLE
    )
    ext = {"render_pdf": ".pdf", "render_docx": ".docx", "render_html": ".html"}[render.__name__]
    out = tmp_path / f"widget{ext}"
    render(read_source(src), out)

    doc = load_file(out, out.name)
    assert [(b.kind, b.level, b.text) for b in doc.blocks] == EXPECTED


def test_unsupported_file_type_is_rejected(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("hello")
    with pytest.raises(ValueError, match="Unsupported"):
        load_file(path, "notes.txt")


def test_table_to_markdown_pads_short_rows_and_escapes_pipes():
    assert table_to_markdown([["A", "B"], ["x|y"]]) == "| A | B |\n| --- | --- |\n| x/y |  |"
