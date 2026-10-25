"""One document in, one outcome per quote out: parse -> extract -> fill metadata -> validate (M4)."""

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from quote_pipeline.extract import Extraction, ExtractionError, extract
from quote_pipeline.parsers import parse_file
from quote_pipeline.schema import ExtractedQuote
from quote_pipeline.validation import validate


@dataclass(frozen=True)
class Outcome:
    source_file: str
    row: int | None
    quote: ExtractedQuote | None  # None if the document couldn't be parsed or extracted at all
    issues: list[str] = field(default_factory=list)
    extraction: Extraction | None = None  # tokens, cost and latency, when there was an LLM call

    @property
    def status(self) -> str:
        return "needs_review" if self.issues else "valid"


def process_file(path: Path, source_file: str, received_on: date,
                 supplier: str | None = None) -> list[Outcome]:
    """Run one document through the pipeline.

    `received_on` and `supplier` are ingestion metadata: what we know about the document from how it arrived
    (e.g. the email it came in), not from reading it.
    """
    try:
        raws = parse_file(path, source_file)
    except ValueError as e:  # scanned PDF, attachment-only email, unsupported type: the whole file needs a human
        return [Outcome(source_file, None, None, [str(e)])]

    outcomes = []
    for raw in raws:
        try:
            result = extract(raw)
        except ExtractionError as e:
            outcomes.append(Outcome(raw.source_file, raw.row, None, [str(e)]))
            continue

        quote = result.quote
        if quote.supplier is None and supplier is not None:
            quote = quote.model_copy(update={"supplier": supplier})  # frozen-style update: a new object
        outcomes.append(Outcome(raw.source_file, raw.row, quote, validate(quote, received_on), result))
    return outcomes
