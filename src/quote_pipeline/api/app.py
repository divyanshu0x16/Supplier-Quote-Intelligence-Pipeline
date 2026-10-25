"""HTTP API (~ Spring MVC controllers).

Run:  uv run uvicorn quote_pipeline.api.app:app --reload      then open http://localhost:8000/docs
"""

import tempfile
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Annotated

import anthropic
from fastapi import FastAPI, Form, Query, Request, UploadFile
from fastapi.responses import JSONResponse

from quote_pipeline.api.dependencies import PipelineDep, Repository
from quote_pipeline.api.schemas import CompareOut, IngestOut, OutcomeOut, QuoteOut, ReviewItemOut
from quote_pipeline.config import get_settings
from quote_pipeline.domain.fx import to_usd
from quote_pipeline.ingest import ingest_file
from quote_pipeline.storage.repository import QuoteRepository, connect


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Runs once at startup (before `yield`) and once at shutdown (after it)."""
    with connect(get_settings().database_url) as conn:
        QuoteRepository(conn).init_schema()
    yield


app = FastAPI(title="Supplier Quote Intelligence", lifespan=lifespan)


@app.exception_handler(anthropic.APIError)
def llm_unavailable(request: Request, exc: anthropic.APIError) -> JSONResponse:
    # The LLM is down even after the SDK's retries. That's our outage, not a bad document: say "try again".
    return JSONResponse(status_code=503, content={"detail": "Extraction service unavailable, retry later"})


def to_quote_out(row: dict) -> QuoteOut:
    return QuoteOut(**row, unit_price_usd=to_usd(row["unit_price"], row["currency"]))


@app.post("/ingest", response_model=IngestOut)
def ingest(
    file: UploadFile,
    repo: Repository,
    pipeline: PipelineDep,
    supplier: Annotated[str | None, Form(description="Who sent it, if known (used when the text doesn't say)")] = None,
    received_on: Annotated[date | None, Form(description="Defaults to today")] = None,
) -> IngestOut:
    # `def`, not `async def`: the LLM call blocks, so FastAPI runs this in a worker thread instead of
    # stalling the server's event loop.
    name = Path(file.filename or "upload").name  # drop any directories a client put in the name
    source_file = f"upload/{name}"
    with tempfile.TemporaryDirectory() as tmp:  # parsers read from a path; the folder is deleted afterwards
        path = Path(tmp) / name
        path.write_bytes(file.file.read())
        outcomes = ingest_file(repo, pipeline, path, source_file, received_on or date.today(), supplier)

    if outcomes is None:
        return IngestOut(source_file=source_file, skipped=True, outcomes=[], cost_usd=0.0)
    return IngestOut(
        source_file=source_file,
        skipped=False,
        outcomes=[OutcomeOut(row=o.row, status=o.status, issues=o.issues, quote=o.quote) for o in outcomes],
        cost_usd=sum(o.extraction.cost_usd for o in outcomes if o.extraction),
    )


@app.get("/quotes", response_model=list[QuoteOut])
def list_quotes(
    repo: Repository,
    part: str | None = None,
    supplier: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[QuoteOut]:
    return [to_quote_out(r) for r in repo.list_quotes(part, supplier, limit)]


@app.get("/compare", response_model=CompareOut)
def compare(
    repo: Repository,
    part: str,
    max_lead_days: Annotated[int | None, Query(ge=1)] = None,
    valid_on: Annotated[date | None, Query(description="Defaults to today")] = None,
) -> CompareOut:
    """Who can supply this part cheapest, within the lead time, with a quote that hasn't expired?"""
    day = valid_on or date.today()
    offers = [to_quote_out(r) for r in repo.offers_for_part(part, day, max_lead_days)]
    offers.sort(key=lambda q: (q.unit_price_usd is None, q.unit_price_usd))  # unknown currency sorts last
    return CompareOut(part_number=part, valid_on=day, max_lead_days=max_lead_days, offers=offers)


@app.get("/review-queue", response_model=list[ReviewItemOut])
def review_queue(repo: Repository, limit: Annotated[int, Query(ge=1, le=500)] = 100) -> list[ReviewItemOut]:
    return [ReviewItemOut(**r) for r in repo.review_queue(limit)]
