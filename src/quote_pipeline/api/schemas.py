"""Request/response models (~ DTOs). FastAPI uses them to validate, serialise, and generate the /docs page."""

from datetime import date, datetime

from pydantic import BaseModel, Field

from quote_pipeline.domain.models import ExtractedQuote


class QuoteOut(BaseModel):
    id: int
    source_file: str
    row_num: int | None
    supplier: str
    part_number: str
    unit_price: float
    currency: str
    unit_price_usd: float | None = Field(description="Approximate, fixed FX rates; for ranking only")
    moq: int | None
    lead_time_days: int
    valid_until: date


class CompareOut(BaseModel):
    part_number: str
    valid_on: date
    max_lead_days: int | None
    offers: list[QuoteOut] = Field(description="Cheapest first (by approximate USD price)")


class ReviewItemOut(BaseModel):
    id: int
    source_file: str
    row_num: int | None
    reasons: list[str]
    extracted: dict | None = Field(description="What the model read, for the reviewer to correct")
    raw_text: str | None
    created_at: datetime


class OutcomeOut(BaseModel):
    row: int | None
    status: str
    issues: list[str]
    quote: ExtractedQuote | None


class IngestOut(BaseModel):
    source_file: str
    skipped: bool = Field(description="True if this exact file was ingested before (nothing was re-processed)")
    outcomes: list[OutcomeOut]
    cost_usd: float
