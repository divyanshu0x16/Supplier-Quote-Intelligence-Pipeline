"""ClaudeExtractor tests with a fake Anthropic client: no network, no API key, no cost."""

from types import SimpleNamespace

import pytest

from quote_pipeline.domain.models import ExtractedQuote, ExtractionError, RawQuote
from quote_pipeline.extraction.extractor import ClaudeExtractor, cost_usd

RAW = RawQuote(source_file="csv/mueller_pricelist.csv", row=4, text="Part Number: AX-4410 ...")
QUOTE = ExtractedQuote(supplier=None, part_number="AX-4410", unit_price=0.0, currency="EUR",
                       moq=None, lead_time_days=42, valid_until="2026-11-23")


def extractor(stop_reason="end_turn", parsed=QUOTE, error=None) -> ClaudeExtractor:
    """Something shaped like anthropic.Anthropic: client.messages.parse(**kwargs) -> response."""
    def parse(**kwargs):
        if error:
            raise error
        usage = SimpleNamespace(input_tokens=1000, output_tokens=200)
        return SimpleNamespace(stop_reason=stop_reason, parsed_output=parsed, usage=usage)
    return ClaudeExtractor(SimpleNamespace(messages=SimpleNamespace(parse=parse)), "claude-haiku-5-5")


def test_cost_is_computed_from_token_counts():
    # Haiku 5.5: 1000 * $0.10/M + 200 * $0.50/M = $0.0001 + $0.0001
    assert cost_usd("claude-haiku-5-5", 1000, 200) == pytest.approx(0.0002)


def test_success_returns_quote_with_cost_and_latency():
    result = extractor().extract(RAW)
    assert result.quote == QUOTE
    assert (result.input_tokens, result.output_tokens) == (1000, 200)
    assert result.cost_usd == pytest.approx(0.0002)
    assert result.latency_ms >= 0


@pytest.mark.parametrize("stop_reason", ["max_tokens", "refusal"])
def test_unusable_stop_reason_raises_extraction_error(stop_reason):
    with pytest.raises(ExtractionError, match=f"stop_reason={stop_reason}"):
        extractor(stop_reason=stop_reason).extract(RAW)


def test_unparseable_output_raises_extraction_error():
    with pytest.raises(ExtractionError, match="did not match the schema"):
        extractor(error=ValueError("Unterminated string")).extract(RAW)
