"""Postgres storage (M5): schema setup and the idempotent, all-or-nothing load of one document."""

import hashlib
import os
from datetime import date
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg.types.json import Jsonb

from quote_pipeline.pipeline import Outcome

load_dotenv()
SCHEMA_SQL = Path(__file__).with_name("schema.sql")


def connect() -> psycopg.Connection:
    # autocommit: each statement commits on its own unless it's inside an explicit `with conn.transaction()`.
    # (psycopg's default silently opens a transaction that's only saved on conn.commit(): easy to lose data.)
    url = os.environ.get("DATABASE_URL", "postgresql://quotes:quotes@localhost:5432/quotes")
    return psycopg.connect(url, autocommit=True, connect_timeout=3)


def init_schema(conn: psycopg.Connection) -> None:
    conn.execute(SCHEMA_SQL.read_text())


def file_sha256(path: Path) -> str:
    """Fingerprint of the file's bytes: the same file always gives the same hash, whatever it's called."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def is_loaded(conn: psycopg.Connection, sha256: str) -> bool:
    return conn.execute("SELECT 1 FROM documents WHERE sha256 = %s", (sha256,)).fetchone() is not None


def load_document(conn: psycopg.Connection, source_file: str, sha256: str, received_on: date,
                  outcomes: list[Outcome]) -> bool:
    """Store a document and all its quotes in ONE transaction. Returns False if it was already loaded."""
    with conn.transaction():  # commit if the block finishes, roll back everything if anything raises
        row = conn.execute(
            "INSERT INTO documents (source_file, sha256, received_on) VALUES (%s, %s, %s) "
            "ON CONFLICT (sha256) DO NOTHING RETURNING id",  # already there (e.g. a parallel run): skip
            (source_file, sha256, received_on),
        ).fetchone()
        if row is None:
            return False
        document_id = row[0]

        for o in outcomes:
            if o.status == "valid":
                ex = o.extraction
                conn.execute(
                    """
                    INSERT INTO quotes (document_id, row_num, supplier, part_number, unit_price, currency, moq,
                                        lead_time_days, valid_until, raw_text, model, input_tokens,
                                        output_tokens, cost_usd, latency_ms)
                    VALUES (%(document_id)s, %(row_num)s, %(supplier)s, %(part_number)s, %(unit_price)s,
                            %(currency)s, %(moq)s, %(lead_time_days)s, %(valid_until)s, %(raw_text)s,
                            %(model)s, %(input_tokens)s, %(output_tokens)s, %(cost_usd)s, %(latency_ms)s)
                    """,
                    {**o.quote.model_dump(), "document_id": document_id, "row_num": o.row,
                     "raw_text": o.raw_text, "model": ex.model, "input_tokens": ex.input_tokens,
                     "output_tokens": ex.output_tokens, "cost_usd": ex.cost_usd,
                     "latency_ms": round(ex.latency_ms)},
                )
            else:
                extracted = Jsonb(o.quote.model_dump(mode="json")) if o.quote else None
                conn.execute(
                    "INSERT INTO needs_review (document_id, row_num, reasons, extracted, raw_text) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (document_id, o.row, o.issues, extracted, o.raw_text),
                )
    return True
