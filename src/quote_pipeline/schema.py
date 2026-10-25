"""The shape of data the LLM must return (M3). Business rules live in validation (M4), not here."""

from datetime import date

from pydantic import BaseModel


class ExtractedQuote(BaseModel):
    """What the LLM reads out of one quote's text: exactly what the document says."""

    supplier: str | None
    part_number: str | None
    unit_price: float | None
    currency: str | None
    moq: int | None
    lead_time_days: int | None
    valid_until: date | None
