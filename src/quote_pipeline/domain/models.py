"""Domain models: the data that flows through the pipeline. No I/O here, and no imports from other layers."""

from dataclasses import dataclass, field
from datetime import date
from typing import Protocol

from pydantic import BaseModel


@dataclass(frozen=True)
class RawQuote:
    """One quote's text, as produced by a parser."""

    source_file: str  # stable ID, e.g. "email/acme_006.eml" (not the machine-specific path)
    row: int | None  # 1-based data row for CSVs; None for PDFs and emails
    text: str  # plain text for the extractor to read


class ExtractedQuote(BaseModel):
    """What the LLM reads out of one quote's text: exactly what the document says.

    Every field is nullable but required: the model must say null explicitly, and never has to invent a value
    to satisfy the schema. Business rules live in validation, not here.
    """

    supplier: str | None
    part_number: str | None
    unit_price: float | None
    currency: str | None
    moq: int | None
    lead_time_days: int | None
    valid_until: date | None


@dataclass(frozen=True)
class Extraction:
    """An extracted quote plus what it cost to get it."""

    quote: ExtractedQuote
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: float
    cost_usd: float


class ExtractionError(Exception):
    """The model answered, but not with a usable quote. The pipeline sends that quote to needs_review."""


class QuoteExtractor(Protocol):
    """Anything with this method can be the pipeline's extractor (~ a Java interface, but matched by shape:
    implementations don't have to declare it). The real one calls Claude; tests use a fake."""

    def extract(self, raw: RawQuote) -> Extraction: ...


@dataclass(frozen=True)
class Outcome:
    """The pipeline's verdict on one quote."""

    source_file: str
    row: int | None
    quote: ExtractedQuote | None  # None if the document couldn't be parsed or extracted at all
    issues: list[str] = field(default_factory=list)
    extraction: Extraction | None = None  # tokens, cost and latency, when there was an LLM call
    raw_text: str | None = None  # the text the model saw; None if the file couldn't be parsed

    @property
    def status(self) -> str:
        return "needs_review" if self.issues else "valid"
