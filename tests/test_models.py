from datetime import date

import pytest
from pydantic import ValidationError

from quote_pipeline.domain.models import ExtractedQuote

FULL = {
    "supplier": "Müller Präzisionsteile GmbH",
    "part_number": "AX-4410",
    "unit_price": 0.09,
    "currency": "EUR",
    "moq": 500,
    "lead_time_days": 14,
    "valid_until": "2026-11-23",
}


def test_full_quote_parses_with_types():
    q = ExtractedQuote.model_validate(FULL)
    assert q.valid_until == date(2026, 11, 23)  # ISO string -> real date
    assert q.moq == 500


def test_business_rules_are_not_enforced_here():
    # A zero price and a typo'd part are what the document SAYS; M4 decides they're bad.
    q = ExtractedQuote.model_validate({**FULL, "unit_price": 0.0, "part_number": "AX-4410X"})
    assert q.unit_price == 0.0


@pytest.mark.parametrize("field", list(FULL))
def test_every_field_may_be_null_but_not_missing(field):
    # null = "the document doesn't say" (M4 sends it to review); missing key = the model skipped the field
    assert getattr(ExtractedQuote.model_validate({**FULL, field: None}), field) is None
    with pytest.raises(ValidationError):
        ExtractedQuote.model_validate({k: v for k, v in FULL.items() if k != field})
