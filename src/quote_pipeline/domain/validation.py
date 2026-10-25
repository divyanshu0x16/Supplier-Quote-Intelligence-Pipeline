"""Business rules: is an extracted quote good enough to use, or does a human need to look at it?"""

from datetime import date

from quote_pipeline.domain.catalog import KNOWN_PARTS
from quote_pipeline.domain.models import ExtractedQuote


def validate(q: ExtractedQuote, received_on: date, max_lead_time_days: int) -> list[str]:
    """Return the reasons this quote needs human review. An empty list means it's valid.

    `max_lead_time_days` is a business decision (Settings), ideally per part category.
    """
    issues = []

    for field in ("supplier", "part_number", "unit_price", "currency", "lead_time_days", "valid_until"):
        if getattr(q, field) is None:
            issues.append(f"{field} not stated")
    # moq may legitimately be None ("No MOQ"), so it isn't in the list above.

    if q.part_number is not None and q.part_number not in KNOWN_PARTS:
        issues.append(f"unknown part number {q.part_number!r}")
    if q.unit_price is not None and q.unit_price <= 0:
        issues.append(f"unit price must be > 0, got {q.unit_price}")
    if q.lead_time_days is not None and not 0 < q.lead_time_days <= max_lead_time_days:
        issues.append(f"lead time {q.lead_time_days} days is outside 1-{max_lead_time_days} days")
    if q.valid_until is not None and q.valid_until < received_on:
        # Usually a misread date format (dd/mm vs mm/dd) or an old quote forwarded again.
        issues.append(f"valid until {q.valid_until} is before the quote was received ({received_on})")

    return issues
