"""One document in, one Outcome per quote out: parse -> extract -> fill metadata -> validate."""

from datetime import date
from pathlib import Path

from quote_pipeline.domain.models import ExtractionError, Outcome, QuoteExtractor
from quote_pipeline.domain.validation import validate
from quote_pipeline.parsing import parse_file


class Pipeline:
    def __init__(self, extractor: QuoteExtractor, max_lead_time_days: int):
        self.extractor = extractor  # any object with .extract(raw): Claude in production, a fake in tests
        self.max_lead_time_days = max_lead_time_days

    def process_file(self, path: Path, source_file: str, received_on: date,
                     supplier: str | None = None) -> list[Outcome]:
        """Run one document through the pipeline.

        `received_on` and `supplier` are ingestion metadata: what we know about the document from how it
        arrived (e.g. the email it came in), not from reading it.
        """
        try:
            raws = parse_file(path, source_file)
        except ValueError as e:  # scanned PDF, attachment-only email, unsupported type: a human must look
            return [Outcome(source_file, None, None, [str(e)])]

        outcomes = []
        for raw in raws:
            try:
                result = self.extractor.extract(raw)
            except ExtractionError as e:
                outcomes.append(Outcome(raw.source_file, raw.row, None, [str(e)], raw_text=raw.text))
                continue

            quote = result.quote
            if quote.supplier is None and supplier is not None:
                quote = quote.model_copy(update={"supplier": supplier})  # a new object; the original is untouched
            issues = validate(quote, received_on, self.max_lead_time_days)
            outcomes.append(Outcome(raw.source_file, raw.row, quote, issues, result, raw_text=raw.text))
        return outcomes
