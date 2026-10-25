from datetime import date

import psycopg
import pytest

from quote_pipeline.domain.models import ExtractedQuote, Extraction, Outcome

RECEIVED = date(2026, 10, 24)
QUOTE = ExtractedQuote(supplier="Acme Components Inc.", part_number="CN-2201", unit_price=0.38, currency="USD",
                       moq=100, lead_time_days=42, valid_until=date(2027, 1, 22))
EXTRACTION = Extraction(quote=QUOTE, model="claude-haiku-5-5", input_tokens=1650, output_tokens=80,
                        latency_ms=1500.0, cost_usd=0.0002)


def valid(row=None, quote=QUOTE):
    return Outcome("csv/x.csv", row, quote, [], EXTRACTION, raw_text="Part Number: CN-2201 ...")


def review(row=None):
    return Outcome("csv/x.csv", row, QUOTE, ["unit price must be > 0, got 0.0"], EXTRACTION, raw_text="...")


def count(db, table):
    return db.count(table)


def test_same_file_twice_is_stored_once(db):
    before = count(db, "quotes")
    assert db.save_document("csv/x.csv", "hash-1", RECEIVED, [valid()]) is True
    assert db.save_document("csv/x.csv", "hash-1", RECEIVED, [valid()]) is False  # same bytes: skipped
    assert count(db, "quotes") == before + 1


def test_same_name_but_new_content_is_a_new_document(db):
    before = count(db, "documents")
    db.save_document("csv/x.csv", "hash-old", RECEIVED, [valid()])
    db.save_document("csv/x.csv", "hash-new", RECEIVED, [valid()])  # supplier sent an updated price list
    assert count(db, "documents") == before + 2


def test_outcomes_go_to_the_right_table(db):
    q, r = count(db, "quotes"), count(db, "needs_review")
    db.save_document("csv/x.csv", "hash-2", RECEIVED, [valid(row=1), review(row=2)])
    assert (count(db, "quotes"), count(db, "needs_review")) == (q + 1, r + 1)
    reasons = db.conn.execute("SELECT reasons FROM needs_review ORDER BY id DESC LIMIT 1").fetchone()[0]
    assert reasons == ["unit price must be > 0, got 0.0"]  # TEXT[] comes back as a Python list


def test_a_failure_mid_document_leaves_no_trace(db):
    docs, quotes = count(db, "documents"), count(db, "quotes")
    broken = valid(row=2, quote=QUOTE.model_copy(update={"supplier": None}))  # a bug let an incomplete quote through
    with pytest.raises(psycopg.errors.NotNullViolation):  # the database's NOT NULL refuses it
        db.save_document("csv/x.csv", "hash-3", RECEIVED, [valid(row=1), broken])
    assert (count(db, "documents"), count(db, "quotes")) == (docs, quotes)  # row 1 and the document rolled back too
