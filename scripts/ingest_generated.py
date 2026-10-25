"""Ingest every generated document into Postgres. Run it twice: the second run should skip everything, for free.

Usage: docker compose up -d && uv run python scripts/ingest_generated.py
"""

from pathlib import Path

from generate_synthetic import QUOTE_DATE  # same folder: Python puts a script's own folder on the path
from run_pipeline import supplier_from_filename

from quote_pipeline.db import connect, init_schema
from quote_pipeline.ingest import ingest_file

DATA = Path("data/generated")
RECEIVED_ON = QUOTE_DATE  # same fixed clock as the generator; see run_pipeline.py


def main() -> None:
    with connect() as conn:
        init_schema(conn)
        loaded = skipped = 0
        for path in sorted(p for p in DATA.rglob("*") if p.suffix in {".eml", ".csv", ".pdf"}):
            source_file = path.relative_to(DATA).as_posix()
            if ingest_file(conn, path, source_file, RECEIVED_ON, supplier_from_filename(source_file)):
                loaded += 1
            else:
                skipped += 1

        counts = {t: conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
                  for t in ("documents", "quotes", "needs_review")}
        cost = conn.execute("SELECT coalesce(sum(cost_usd), 0) FROM quotes").fetchone()[0]

    print(f"This run: {loaded} documents loaded, {skipped} skipped (already in the database)")
    print(f"Database: {counts['documents']} documents, {counts['quotes']} valid quotes, "
          f"{counts['needs_review']} in needs_review; stored extraction cost of valid quotes ${cost:.4f}")


if __name__ == "__main__":
    main()
