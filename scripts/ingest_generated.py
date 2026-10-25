"""Ingest every generated document into Postgres. Run it twice: the second run should skip everything, for free.

Usage: docker compose up -d && uv run python scripts/ingest_generated.py
"""

from common import RECEIVED_ON, build_pipeline, generated_documents, setup_logging, supplier_from_filename

from quote_pipeline.config import get_settings
from quote_pipeline.ingest import ingest_file
from quote_pipeline.storage.repository import QuoteRepository, connect


def main() -> None:
    setup_logging()
    settings = get_settings()
    pipeline = build_pipeline(settings)

    with connect(settings.database_url) as conn:
        repo = QuoteRepository(conn)
        repo.init_schema()
        loaded = skipped = 0
        for path, source_file in generated_documents():
            if ingest_file(repo, pipeline, path, source_file, RECEIVED_ON, supplier_from_filename(source_file)):
                loaded += 1
            else:
                skipped += 1
        counts = {t: repo.count(t) for t in ("documents", "quotes", "needs_review")}

    print(f"This run: {loaded} documents loaded, {skipped} skipped (already in the database)")
    print(f"Database: {counts['documents']} documents, {counts['quotes']} valid quotes, "
          f"{counts['needs_review']} in needs_review")


if __name__ == "__main__":
    main()
