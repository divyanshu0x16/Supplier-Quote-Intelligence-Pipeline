"""API tests: real FastAPI app and real Postgres (rolled back), fake extractor (no LLM calls, no cost)."""

from datetime import date, timedelta

import anthropic
import httpx2
import pytest
from fakes import FakeExtractor
from fastapi.testclient import TestClient

from quote_pipeline.api.app import app
from quote_pipeline.api.dependencies import get_pipeline, get_repository
from quote_pipeline.domain.models import ExtractedQuote, Extraction, Outcome
from quote_pipeline.pipeline import Pipeline

TODAY = date(2026, 10, 24)
PART = "TEST-9999"  # not in the generated data, so these tests see only their own rows


def make_quote(**changes) -> ExtractedQuote:
    base = dict(supplier="Acme Components Inc.", part_number="CN-2201", unit_price=0.38, currency="USD",
                moq=None, lead_time_days=14, valid_until=TODAY + timedelta(days=60))
    return ExtractedQuote(**{**base, **changes})


@pytest.fixture
def client(db):
    """The app with the test's database and a given fake extractor injected (~ Spring's @MockBean)."""
    def make(extractor=None):
        app.dependency_overrides[get_repository] = lambda: db
        app.dependency_overrides[get_pipeline] = lambda: Pipeline(extractor or FakeExtractor({}), 180)
        return TestClient(app)
    yield make
    app.dependency_overrides.clear()


def seed(db, sha, **changes):
    """Store one valid quote directly, bypassing extraction."""
    q = make_quote(part_number=PART, **changes)
    outcome = Outcome(f"test/{sha}.pdf", None, q, [], Extraction(q, "fake", 0, 0, 0.0, 0.0), raw_text="...")
    db.save_document(f"test/{sha}.pdf", sha, TODAY, [outcome])


def test_compare_ranks_by_usd_and_drops_expired_and_slow_offers(client, db):
    seed(db, "eur", supplier="Müller", unit_price=1.00, currency="EUR")  # ~ $1.087
    seed(db, "usd", supplier="Acme", unit_price=1.05, currency="USD")  # $1.05
    seed(db, "jpy", supplier="Kanto", unit_price=150, currency="JPY", lead_time_days=60)  # $1.00
    seed(db, "expired", supplier="Old", unit_price=0.50, valid_until=TODAY - timedelta(days=1))
    seed(db, "slow", supplier="Slow", unit_price=0.60, lead_time_days=90)

    r = client().get("/compare", params={"part": PART, "max_lead_days": 60, "valid_on": TODAY.isoformat()})

    assert r.status_code == 200
    assert [o["supplier"] for o in r.json()["offers"]] == ["Kanto", "Acme", "Müller"]  # cheapest first, in USD
    assert r.json()["offers"][0]["unit_price"] == 150  # the original price is kept alongside the USD estimate


def test_ingest_routes_rows_and_skips_a_repeat_upload(client):
    fake = FakeExtractor({1: make_quote(supplier=None), 2: make_quote(supplier=None, unit_price=0.0)})
    api = client(fake)
    csv = "Part Number;Unit Price;Note\nCN-2201;0,38;api-test\nCN-2201;0,00;api-test\n".encode()
    upload = {"file": ("mueller_pricelist.csv", csv, "text/csv")}
    form = {"supplier": "Müller Präzisionsteile GmbH", "received_on": TODAY.isoformat()}

    first = api.post("/ingest", files=upload, data=form).json()
    assert first["skipped"] is False
    assert [o["status"] for o in first["outcomes"]] == ["valid", "needs_review"]
    assert first["outcomes"][0]["quote"]["supplier"] == "Müller Präzisionsteile GmbH"  # filled from the form

    second = api.post("/ingest", files=upload, data=form).json()
    assert second["skipped"] is True and second["outcomes"] == []  # same bytes: no re-processing, no cost
    assert len(fake.calls) == 2  # the extractor ran only for the first upload

    queue = api.get("/review-queue", params={"limit": 1}).json()
    assert queue[0]["reasons"] == ["unit price must be > 0, got 0.0"]


def test_llm_outage_is_a_503_not_a_bad_document(client):
    outage = anthropic.APIConnectionError(request=httpx2.Request("POST", "https://api.anthropic.com"))
    api = client(FakeExtractor({1: outage}))
    upload = {"file": ("x.csv", b"Part Number;Note\nCN-2201;outage-test\n", "text/csv")}

    r = api.post("/ingest", files=upload)

    assert r.status_code == 503  # "try again later", and nothing was stored for this file


def test_quotes_can_be_filtered_by_part(client, db):
    seed(db, "listed", supplier="Acme")
    r = client().get("/quotes", params={"part": PART})
    assert r.status_code == 200 and [q["supplier"] for q in r.json()] == ["Acme"]
