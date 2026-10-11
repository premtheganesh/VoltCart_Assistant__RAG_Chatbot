"""Load the knowledge base into Postgres (documents + chunks with embeddings).

make ingest                         # incremental: only new or changed sources
make ingest args="--force"          # re-embed everything (e.g. after changing EMBED_MODEL)
make preview f=sample_data/docs/shipping-policy.html   # show chunks, no API calls
"""

import argparse
import logging
import sys
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import PROJECT_ROOT, get_settings
from app.db.session import get_engine
from app.ingestion.chunking import chunk_document
from app.ingestion.loaders import load_file
from app.ingestion.pipeline import ingest
from app.llm.embeddings import embed_model_id, get_embedder


def preview(path: Path) -> None:
    settings = get_settings()
    doc = load_file(path, path.name)
    chunks = chunk_document(doc, settings.chunk_max_tokens, settings.chunk_overlap_tokens)
    print(f"{doc.title}  [{doc.doc_type}]  products={doc.products}  url={doc.url}")
    print(f"{len(doc.blocks)} blocks -> {len(chunks)} chunks\n")
    for c in chunks:
        page = f", page {c.page}" if c.page else ""
        print(f"--- chunk {c.index} ({c.token_count} tokens{page}) ---")
        print(c.embed_text, end="\n\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dir", help="folder to ingest (default: DOCS_DIR from .env)")
    parser.add_argument("--force", action="store_true", help="re-embed every chunk")
    parser.add_argument("--no-catalog", action="store_true", help="skip catalog products")
    parser.add_argument("--preview", type=Path, help="print one file's chunks and exit")
    args = parser.parse_args()

    if args.preview:
        preview(args.preview if args.preview.is_absolute() else PROJECT_ROOT / args.preview)
        return

    settings = get_settings()
    logging.basicConfig(level=settings.log_level, format="%(message)s")
    for noisy in ("httpx", "httpcore", "pdfminer"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    docs_dir = PROJECT_ROOT / (args.dir or settings.docs_dir)
    if not docs_dir.is_dir():
        sys.exit(f"Folder not found: {docs_dir}")

    print(f"Ingesting {docs_dir.relative_to(PROJECT_ROOT)} with {embed_model_id(settings)} ...")
    with Session(get_engine()) as session, session.begin():
        report = ingest(
            session,
            get_embedder(settings),
            embed_model_id(settings),
            docs_dir,
            source_root=PROJECT_ROOT,
            include_catalog=not args.no_catalog,
            force=args.force,
            max_tokens=settings.chunk_max_tokens,
            overlap_tokens=settings.chunk_overlap_tokens,
            batch_size=settings.embed_batch_size,
        )
    for label, sources in [("added", report.added), ("updated", report.updated),
                           ("deleted", report.deleted)]:  # fmt: skip
        for source in sources:
            print(f"  {label:8} {source}")
    print(report.summary())


if __name__ == "__main__":
    main()
