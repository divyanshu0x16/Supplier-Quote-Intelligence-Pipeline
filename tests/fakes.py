"""Test doubles shared by several test files."""

from quote_pipeline.domain.models import ExtractedQuote, Extraction, RawQuote


class FakeExtractor:
    """Satisfies the QuoteExtractor protocol without declaring it: having .extract() is enough."""

    def __init__(self, quotes_by_row: dict[int | None, ExtractedQuote | Exception]):
        self.quotes_by_row = quotes_by_row
        self.calls: list[RawQuote] = []

    def extract(self, raw: RawQuote) -> Extraction:
        self.calls.append(raw)
        result = self.quotes_by_row[raw.row]
        if isinstance(result, Exception):
            raise result
        return Extraction(result, "fake", input_tokens=0, output_tokens=0, latency_ms=0.0, cost_usd=0.0)
