"""Heading-aware chunking: split a parsed document into retrieval-sized pieces.

1. Each heading starts a section; a chunk never mixes two sections.
2. A section that fits in `max_tokens` becomes one chunk.
3. A longer section is packed block by block (paragraphs, lists, tables); oversized blocks are
   split by sentence or by table rows (the header row is repeated on every piece).
4. Consecutive chunks of a long section share up to `overlap_tokens` of text, so a fact that
   falls on a boundary is still found with its context.
5. Every chunk carries its heading path ("Manual > Troubleshooting"), which is embedded with it:
   a troubleshooting table that never names the product is still found for that product.
"""

import math
import re
from dataclasses import dataclass

from app.ingestion.loaders import Block, ParsedDocument

SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def estimate_tokens(text: str) -> int:
    """About 4 characters per token for English: close enough for sizing chunks."""
    return max(1, math.ceil(len(text) / 4))


@dataclass
class TextChunk:
    index: int
    heading: str  # "Document title > Section > Subsection"
    content: str
    token_count: int
    page: int | None = None

    @property
    def embed_text(self) -> str:
        """What gets embedded and hashed: the heading path gives the chunk its context."""
        return f"{self.heading}\n\n{self.content}"


@dataclass
class _Unit:
    text: str
    page: int | None
    is_table: bool = False

    @property
    def tokens(self) -> int:
        return estimate_tokens(self.text)


def _sections(doc: ParsedDocument) -> list[tuple[str, list[Block]]]:
    """Group body blocks under their heading path; sections without body text are dropped."""
    sections: list[tuple[str, list[Block]]] = []
    path: list[tuple[int, str]] = []  # (level, heading) for levels >= 2
    body: list[Block] = []

    def close() -> None:
        if body:
            heading = " > ".join([doc.title, *(text for _, text in path)])
            sections.append((heading, body.copy()))
            body.clear()

    for block in doc.blocks:
        if block.kind == "heading":
            close()
            if block.level <= 1:
                path = []
            else:
                path = [(lvl, text) for lvl, text in path if lvl < block.level]
                path.append((block.level, block.text))
        else:
            body.append(block)
    close()
    return sections


def _split_text(text: str, page: int | None, max_tokens: int) -> list[_Unit]:
    # Lists split by item, prose by sentence; a single huge sentence by characters
    pieces = text.split("\n") if "\n" in text else SENTENCE_END.split(text)
    units: list[_Unit] = []
    current = ""
    for piece in pieces:
        candidate = (
            f"{current}\n{piece}" if "\n" in text and current else (f"{current} {piece}".strip())
        )
        if current and estimate_tokens(candidate) > max_tokens:
            units.append(_Unit(current, page))
            current = piece
        else:
            current = candidate
    if current:
        units.append(_Unit(current, page))

    out: list[_Unit] = []
    limit = max_tokens * 4
    for unit in units:
        while estimate_tokens(unit.text) > max_tokens:
            out.append(_Unit(unit.text[:limit], page))
            unit = _Unit(unit.text[limit:], page)
        out.append(unit)
    return out


def _split_table(text: str, page: int | None, max_tokens: int) -> list[_Unit]:
    lines = text.split("\n")
    header, rows = lines[:2], lines[2:]
    units: list[_Unit] = []
    current: list[str] = []
    for row in rows:
        if current and estimate_tokens("\n".join(header + current + [row])) > max_tokens:
            units.append(_Unit("\n".join(header + current), page, is_table=True))
            current = []
        current.append(row)
    units.append(_Unit("\n".join(header + current), page, is_table=True))
    return units


def _units(blocks: list[Block], max_tokens: int) -> list[_Unit]:
    units: list[_Unit] = []
    for block in blocks:
        if estimate_tokens(block.text) <= max_tokens:
            units.append(_Unit(block.text, block.page, is_table=block.kind == "table"))
        elif block.kind == "table":
            units.extend(_split_table(block.text, block.page, max_tokens))
        else:
            units.extend(_split_text(block.text, block.page, max_tokens))
    return units


def _pack(units: list[_Unit], max_tokens: int, overlap_tokens: int) -> list[list[_Unit]]:
    groups: list[list[_Unit]] = []
    current: list[_Unit] = []
    for unit in units:
        size = sum(u.tokens for u in current)
        if current and size + unit.tokens > max_tokens:
            groups.append(current)
            # Carry the last text unit(s) forward as overlap; tables are never repeated
            carry: list[_Unit] = []
            for prev in reversed(current):
                if prev.is_table or sum(u.tokens for u in carry) + prev.tokens > overlap_tokens:
                    break
                carry.insert(0, prev)
            if sum(u.tokens for u in carry) + unit.tokens > max_tokens:
                carry = []
            current = carry
        current.append(unit)
    if current:
        groups.append(current)
    return groups


def chunk_document(
    doc: ParsedDocument, max_tokens: int = 600, overlap_tokens: int = 80
) -> list[TextChunk]:
    chunks: list[TextChunk] = []
    for heading, blocks in _sections(doc):
        for group in _pack(_units(blocks, max_tokens), max_tokens, overlap_tokens):
            content = "\n\n".join(u.text for u in group)
            chunks.append(
                TextChunk(
                    index=len(chunks),
                    heading=heading,
                    content=content,
                    token_count=estimate_tokens(content),
                    page=group[0].page,
                )
            )
    return chunks
