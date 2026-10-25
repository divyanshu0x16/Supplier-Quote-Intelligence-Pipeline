from datetime import date

import pytest

from quote_pipeline.domain.models import ExtractedQuote
from quote_pipeline.domain.validation import validate

RECEIVED = date(2026, 10, 24)
MAX_LEAD_DAYS = 180
GOOD = dict(supplier="Acme Components Inc.", part_number="CN-2201", unit_price=0.38, currency="USD",
            moq=None, lead_time_days=42, valid_until=date(2027, 1, 22))


def issues_for(**changes) -> list[str]:
    return validate(ExtractedQuote(**{**GOOD, **changes}), RECEIVED, MAX_LEAD_DAYS)


def test_good_quote_has_no_issues():
    assert issues_for() == []  # also shows a missing MOQ is fine


@pytest.mark.parametrize("changes, expected", [
    ({"part_number": "DS-6100X"}, "unknown part number 'DS-6100X'"),
    ({"unit_price": 0.0}, "unit price must be > 0"),
    ({"lead_time_days": 400}, "lead time 400 days is outside 1-180 days"),
    ({"valid_until": date(2026, 9, 24)}, "before the quote was received"),
    ({"supplier": None}, "supplier not stated"),
    ({"unit_price": None}, "unit_price not stated"),
])
def test_each_rule_reports_a_readable_reason(changes, expected):
    issues = issues_for(**changes)
    assert len(issues) == 1 and expected in issues[0]


def test_several_problems_are_all_reported():
    assert len(issues_for(unit_price=0.0, lead_time_days=400)) == 2  # reviewers see everything at once
