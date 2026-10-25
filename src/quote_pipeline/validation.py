"""Business rules (M4): is an extracted quote good enough to use, or does a human need to look at it?"""

from datetime import date

from quote_pipeline.catalog import KNOWN_PARTS
from quote_pipeline.schema import ExtractedQuote

# A business decision, not an engineering one: agree it with procurement, ideally per part category.
MAX_LEAD_TIME_DAYS = 180


def validate(q: ExtractedQuote, received_on: date) -> list[str]:
    """Return the reasons this quote needs human review. An empty list means it's valid."""
    issues = []

    for field in ("supplier", "part_number", "unit_price", "currency", "lead_time_days", "valid_until"):
        if getattr(q, field) is None:
            issues.append(f"{field} not stated")
    # moq may legitimately be None ("No MOQ"), so it isn't in the list above.

    if q.part_number is not None and q.part_number not in KNOWN_PARTS:
        issues.append(f"unknown part number {q.part_number!r}")
    if q.unit_price is not None and q.unit_price <= 0:
        issues.append(f"unit price must be > 0, got {q.unit_price}")
    if q.lead_time_days is not None and not 0 < q.lead_time_days <= MAX_LEAD_TIME_DAYS:
        issues.append(f"lead time {q.lead_time_days} days is outside 1-{MAX_LEAD_TIME_DAYS} days")
    if q.valid_until is not None and q.valid_until < received_on:
        # Usually a misread date format (dd/mm vs mm/dd) or an old quote forwarded again.
        issues.append(f"valid until {q.valid_until} is before the quote was received ({received_on})")

    return issues
