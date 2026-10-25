"""Postgres storage (~ a Spring repository): schema setup and the idempotent, all-or-nothing load of a document."""

from datetime import date
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from quote_pipeline.domain.models import Outcome

SCHEMA_SQL = Path(__file__).with_name("schema.sql")
QUOTE_COLUMNS = """q.id, d.source_file, q.row_num, q.supplier, q.part_number, q.unit_price, q.currency, q.moq,
                   q.lead_time_days, q.valid_until"""


def connect(database_url: str) -> psycopg.Connection:
    # autocommit: each statement commits on its own unless it's inside an explicit `with conn.transaction()`.
    # (psycopg's default silently opens a transaction that's only saved on conn.commit(): easy to lose data.)
    return psycopg.connect(database_url, autocommit=True, connect_timeout=3)


class QuoteRepository:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    def init_schema(self) -> None:
        self.conn.execute(SCHEMA_SQL.read_text())

    def is_loaded(self, sha256: str) -> bool:
        return self.conn.execute("SELECT 1 FROM documents WHERE sha256 = %s", (sha256,)).fetchone() is not None

    def list_quotes(self, part_number: str | None = None, supplier: str | None = None,
                    limit: int = 100) -> list[dict]:
        # "%(x)s IS NULL OR column = %(x)s": one query where each filter is optional
        return self._rows(
            f"""
            SELECT {QUOTE_COLUMNS} FROM quotes q JOIN documents d ON d.id = q.document_id
            WHERE (%(part)s::text IS NULL OR q.part_number = %(part)s)
              AND (%(supplier)s::text IS NULL OR q.supplier = %(supplier)s)
            ORDER BY q.part_number, q.id
            LIMIT %(limit)s
            """,
            {"part": part_number, "supplier": supplier, "limit": limit},
        )

    def offers_for_part(self, part_number: str, valid_on: date, max_lead_days: int | None = None) -> list[dict]:
        """Quotes still valid on `valid_on` (expiry checked at QUERY time, so it never goes stale)."""
        return self._rows(
            f"""
            SELECT {QUOTE_COLUMNS} FROM quotes q JOIN documents d ON d.id = q.document_id
            WHERE q.part_number = %(part)s
              AND q.valid_until >= %(valid_on)s
              AND (%(max_lead)s::int IS NULL OR q.lead_time_days <= %(max_lead)s)
            """,
            {"part": part_number, "valid_on": valid_on, "max_lead": max_lead_days},
        )

    def review_queue(self, limit: int = 100) -> list[dict]:
        return self._rows(
            """
            SELECT r.id, d.source_file, r.row_num, r.reasons, r.extracted, r.raw_text, r.created_at
            FROM needs_review r JOIN documents d ON d.id = r.document_id
            ORDER BY r.id DESC  -- newest first (created_at can tie: now() is fixed within a transaction)
            LIMIT %(limit)s
            """,
            {"limit": limit},
        )

    def _rows(self, sql: str, params: dict) -> list[dict]:
        with self.conn.cursor(row_factory=dict_row) as cur:  # rows as {"column": value} instead of tuples
            return cur.execute(sql, params).fetchall()

    def count(self, table: str) -> int:
        assert table in {"documents", "quotes", "needs_review"}  # never put untrusted text into SQL
        return self.conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]

    def save_document(self, source_file: str, sha256: str, received_on: date, outcomes: list[Outcome]) -> bool:
        """Store a document and all its quotes in ONE transaction. Returns False if it was already stored."""
        with self.conn.transaction():  # commit if the block finishes, roll back everything if anything raises
            row = self.conn.execute(
                "INSERT INTO documents (source_file, sha256, received_on) VALUES (%s, %s, %s) "
                "ON CONFLICT (sha256) DO NOTHING RETURNING id",  # already there (e.g. a parallel run): skip
                (source_file, sha256, received_on),
            ).fetchone()
            if row is None:
                return False
            document_id = row[0]
            for o in outcomes:
                if o.status == "valid":
                    self._insert_quote(document_id, o)
                else:
                    self._insert_review(document_id, o)
        return True

    def _insert_quote(self, document_id: int, o: Outcome) -> None:
        ex = o.extraction
        self.conn.execute(
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
             "output_tokens": ex.output_tokens, "cost_usd": ex.cost_usd, "latency_ms": round(ex.latency_ms)},
        )

    def _insert_review(self, document_id: int, o: Outcome) -> None:
        extracted = Jsonb(o.quote.model_dump(mode="json")) if o.quote else None
        self.conn.execute(
            "INSERT INTO needs_review (document_id, row_num, reasons, extracted, raw_text) "
            "VALUES (%s, %s, %s, %s, %s)",
            (document_id, o.row, o.issues, extracted, o.raw_text),
        )
