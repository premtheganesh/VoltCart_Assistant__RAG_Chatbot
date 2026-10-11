"""Render Markdown sources into the real files the chatbot ingests.

    sample_data/source/manuals/*.md     -> sample_data/docs/*.pdf
    sample_data/source/guides/*.md      -> sample_data/docs/*.docx
    sample_data/source/helpcenter/*.md  -> sample_data/docs/*.html
    sample_data/source/test_only/*.md   -> sample_data/test_only/*.html

Output is deterministic (fixed timestamps), so re-rendering unchanged sources gives identical files.
Run: make render-docs
"""

import html
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from docx import Document
from docx.shared import Pt, RGBColor
from markdown_it import MarkdownIt
from markdown_it.token import Token
from reportlab import rl_config
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    ListFlowable,
    ListItem,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.config import PROJECT_ROOT

rl_config.invariant = 1  # no random IDs / timestamps inside PDFs

SOURCE_DIR = PROJECT_ROOT / "sample_data" / "source"
DOCS_DIR = PROJECT_ROOT / "sample_data" / "docs"
TEST_ONLY_DIR = PROJECT_ROOT / "sample_data" / "test_only"
BRAND = "VoltCart"
STRIPE = colors.HexColor("#f2f4f7")

md = MarkdownIt("commonmark").enable("table")


# ---------- Markdown -> simple block model ----------


@dataclass
class Run:
    text: str
    bold: bool = False
    italic: bool = False


@dataclass
class Block:
    kind: str  # heading | paragraph | list | table
    level: int = 0
    ordered: bool = False
    runs: list[Run] = field(default_factory=list)
    items: list[list[Run]] = field(default_factory=list)
    rows: list[list[list[Run]]] = field(default_factory=list)  # first row = header


@dataclass
class SourceDoc:
    path: Path
    meta: dict[str, str]
    body: str

    @property
    def title(self) -> str:
        return self.meta["title"]

    @property
    def updated(self) -> datetime:
        return datetime.fromisoformat(self.meta.get("updated") or "2026-01-01")


def read_source(path: Path) -> SourceDoc:
    """Split '---' front matter (simple key: value lines) from the Markdown body."""
    text = path.read_text(encoding="utf-8")
    meta: dict[str, str] = {}
    if text.startswith("---"):
        _, header, text = text.split("---", 2)
        for line in header.strip().splitlines():
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip()
    if "title" not in meta:
        raise ValueError(f"{path.name}: front matter must include a title")
    return SourceDoc(path=path, meta=meta, body=text.strip())


def inline_runs(token: Token) -> list[Run]:
    runs: list[Run] = []
    bold = italic = False
    for child in token.children or []:
        match child.type:
            case "strong_open" | "strong_close":
                bold = child.type == "strong_open"
            case "em_open" | "em_close":
                italic = child.type == "em_open"
            case "text" | "code_inline":
                runs.append(Run(child.content, bold, italic))
            case "softbreak" | "hardbreak":
                runs.append(Run(" ", bold, italic))
    return runs


def to_blocks(markdown: str) -> list[Block]:
    tokens = md.parse(markdown)
    blocks: list[Block] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok.type == "heading_open":
            blocks.append(Block("heading", level=int(tok.tag[1]), runs=inline_runs(tokens[i + 1])))
            i += 3
        elif tok.type == "paragraph_open":
            blocks.append(Block("paragraph", runs=inline_runs(tokens[i + 1])))
            i += 3
        elif tok.type in ("bullet_list_open", "ordered_list_open"):
            block = Block("list", ordered=tok.type == "ordered_list_open")
            close = tok.type.replace("_open", "_close")
            i += 1
            while tokens[i].type != close:
                if tokens[i].type == "inline":
                    block.items.append(inline_runs(tokens[i]))
                i += 1
            blocks.append(block)
            i += 1
        elif tok.type == "table_open":
            block = Block("table")
            i += 1
            while tokens[i].type != "table_close":
                if tokens[i].type == "tr_open":
                    block.rows.append([])
                elif tokens[i].type == "inline":
                    block.rows[-1].append(inline_runs(tokens[i]))
                i += 1
            blocks.append(block)
            i += 1
        else:
            i += 1
    return blocks


def plain(runs: list[Run]) -> str:
    return "".join(r.text for r in runs)


# ---------- PDF ----------


def _markup(runs: list[Run]) -> str:
    out = []
    for r in runs:
        text = html.escape(r.text, quote=False)
        if r.bold:
            text = f"<b>{text}</b>"
        if r.italic:
            text = f"<i>{text}</i>"
        out.append(text)
    return "".join(out)


def render_pdf(doc: SourceDoc, out: Path) -> None:
    styles = getSampleStyleSheet()
    body = ParagraphStyle("Body", parent=styles["BodyText"], fontSize=10, leading=14)
    cell = ParagraphStyle("Cell", parent=body, fontSize=8.5, leading=11, alignment=TA_LEFT)
    head_cell = ParagraphStyle("HeadCell", parent=cell, textColor=colors.white)
    heading_styles = {1: styles["Title"], 2: styles["Heading2"], 3: styles["Heading3"]}

    story = []
    for block in to_blocks(doc.body):
        if block.kind == "heading":
            story.append(Paragraph(_markup(block.runs), heading_styles[min(block.level, 3)]))
        elif block.kind == "paragraph":
            story.append(Paragraph(_markup(block.runs), body))
        elif block.kind == "list":
            items = [
                ListItem(Paragraph(_markup(item), body), leftIndent=12) for item in block.items
            ]
            story.append(
                ListFlowable(
                    items,
                    bulletType="1" if block.ordered else "bullet",
                    start="1" if block.ordered else "•",
                    leftIndent=14,
                )
            )
        elif block.kind == "table":
            data = [
                [Paragraph(_markup(c), head_cell if r == 0 else cell) for c in row]
                for r, row in enumerate(block.rows)
            ]
            ncols = max(len(row) for row in data)
            table = Table(data, colWidths=[(7.0 * inch) / ncols] * ncols, repeatRows=1)
            table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f3a5f")),
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#b0b7c3")),
                        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, STRIPE]),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ]
                )
            )
            story.append(table)
        story.append(Spacer(1, 6))

    def header_footer(canvas, pdf):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.grey)
        canvas.drawString(0.75 * inch, LETTER[1] - 0.5 * inch, f"{BRAND} | {doc.title}")
        canvas.drawRightString(LETTER[0] - 0.75 * inch, 0.5 * inch, f"Page {pdf.page}")
        canvas.restoreState()

    SimpleDocTemplate(
        str(out),
        pagesize=LETTER,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.8 * inch,
        bottomMargin=0.8 * inch,
        title=doc.title,
        author=BRAND,
        subject=doc.meta.get("doc_type", ""),
        keywords=doc.meta.get("products", ""),
    ).build(story, onFirstPage=header_footer, onLaterPages=header_footer)


# ---------- DOCX ----------


def _add_runs(paragraph, runs: list[Run]) -> None:
    for r in runs:
        run = paragraph.add_run(r.text)
        run.bold = r.bold or None
        run.italic = r.italic or None


def render_docx(doc: SourceDoc, out: Path) -> None:
    document = Document()
    document.styles["Normal"].font.name = "Calibri"
    document.styles["Normal"].font.size = Pt(11)
    props = document.core_properties
    props.title, props.author = doc.title, BRAND
    props.subject = doc.meta.get("doc_type", "")
    props.keywords = doc.meta.get("products", "")
    props.created = props.modified = doc.updated

    for block in to_blocks(doc.body):
        if block.kind == "heading":
            heading = document.add_heading(level=0 if block.level == 1 else block.level - 1)
            _add_runs(heading, block.runs)
        elif block.kind == "paragraph":
            _add_runs(document.add_paragraph(), block.runs)
        elif block.kind == "list":
            style = "List Number" if block.ordered else "List Bullet"
            for item in block.items:
                _add_runs(document.add_paragraph(style=style), item)
        elif block.kind == "table":
            ncols = max(len(row) for row in block.rows)
            table = document.add_table(rows=len(block.rows), cols=ncols, style="Table Grid")
            for r, row in enumerate(block.rows):
                for c, runs in enumerate(row):
                    paragraph = table.cell(r, c).paragraphs[0]
                    _add_runs(paragraph, [Run(x.text, x.bold or r == 0, x.italic) for x in runs])
                    for run in paragraph.runs:
                        run.font.size = Pt(9)
                        if r == 0:
                            run.font.color.rgb = RGBColor(0x1F, 0x3A, 0x5F)
            document.add_paragraph()

    document.save(str(out))


# ---------- HTML (help center page with realistic site chrome) ----------

HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title} | {brand} Help Center</title>
  <meta name="description" content="{brand} help center: {title}">
  <meta name="doc_type" content="{doc_type}">
  <meta name="updated" content="{updated}">
  <link rel="canonical" href="https://voltcart.example/help/{slug}">
  <style>
    body {{ font-family: system-ui, sans-serif; max-width: 860px; margin: 0 auto;
           padding: 0 16px; color: #1d2433; }}
    header, footer {{ border-color: #e3e6eb; color: #5b6475; font-size: 14px; }}
    header {{ border-bottom: 1px solid #e3e6eb; padding: 12px 0; }}
    footer {{ border-top: 1px solid #e3e6eb; padding: 16px 0; margin-top: 48px; }}
    nav a {{ margin-right: 16px; color: #1f3a5f; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border: 1px solid #d5d9e0; padding: 6px 8px; text-align: left; vertical-align: top; }}
    th {{ background: #f2f4f7; }}
  </style>
</head>
<body>
  <header>
    <strong>{brand}</strong> Help Center
    <nav aria-label="Help topics">
      <a href="/help/shipping-policy">Shipping</a>
      <a href="/help/returns-and-refunds">Returns</a>
      <a href="/help/warranty-policy">Warranty</a>
      <a href="/help/order-tracking-help">Orders</a>
      <a href="/help/contact-and-support-hours">Contact us</a>
    </nav>
  </header>
  <main>
    <p class="breadcrumb"><a href="/help">Help Center</a> &rsaquo; {title}</p>
{content}
    <p class="updated">Last updated: {updated_human}</p>
  </main>
  <footer>
    <p>&copy; 2026 {brand}, Inc. All rights reserved.
      | <a href="/privacy">Privacy</a> | <a href="/terms">Terms</a></p>
    <p>Need more help? Chat with us 24/7 or call 1-800-555-0199.</p>
  </footer>
</body>
</html>
"""


def render_html(doc: SourceDoc, out: Path) -> None:
    content = "\n".join("    " + line for line in md.render(doc.body).splitlines())
    out.write_text(
        HTML_TEMPLATE.format(
            title=html.escape(doc.title),
            brand=BRAND,
            doc_type=doc.meta.get("doc_type", ""),
            updated=doc.updated.date().isoformat(),
            updated_human=doc.updated.strftime("%B %-d, %Y"),
            slug=doc.path.stem,
            content=content,
        ),
        encoding="utf-8",
    )


# ---------- Driver ----------

JOBS = [
    ("manuals", DOCS_DIR, ".pdf", render_pdf),
    ("guides", DOCS_DIR, ".docx", render_docx),
    ("helpcenter", DOCS_DIR, ".html", render_html),
    ("test_only", TEST_ONLY_DIR, ".html", render_html),
]


def render_all() -> list[Path]:
    written = []
    for folder, out_dir, ext, renderer in JOBS:
        out_dir.mkdir(parents=True, exist_ok=True)
        for src in sorted((SOURCE_DIR / folder).glob("*.md")):
            out = out_dir / f"{src.stem}{ext}"
            renderer(read_source(src), out)
            written.append(out)
    return written


def main() -> None:
    written = render_all()
    for path in written:
        print(f"  {path.relative_to(PROJECT_ROOT)}  ({path.stat().st_size // 1024} KB)")
    print(f"Rendered {len(written)} documents.")


if __name__ == "__main__":
    main()
