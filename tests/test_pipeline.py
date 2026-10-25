"""The whole pipeline (parse -> extract -> fill supplier -> validate) offline, with a fake extractor.

Possible only because Pipeline receives its extractor instead of creating one: dependency injection.
"""

from datetime import date

from fakes import FakeExtractor

from quote_pipeline.domain.models import ExtractedQuote, ExtractionError
from quote_pipeline.pipeline import Pipeline

RECEIVED = date(2026, 10, 24)
QUOTE = ExtractedQuote(supplier=None, part_number="CN-2201", unit_price=0.38, currency="EUR",
                       moq=None, lead_time_days=14, valid_until=date(2026, 12, 23))


def write_csv(tmp_path):
    path = tmp_path / "mueller_pricelist.csv"
    path.write_text("Part Number;Unit Price\nCN-2201;0,38\nCN-2201;0,00\nCN-2201;0,41\n", encoding="utf-8")
    return path


def test_csv_rows_are_filled_validated_and_routed(tmp_path):
    fake = FakeExtractor({
        1: QUOTE,
        2: QUOTE.model_copy(update={"unit_price": 0.0}),
        3: ExtractionError("csv/mueller_pricelist.csv row 3: no usable output (stop_reason=max_tokens)"),
    })
    pipeline = Pipeline(fake, max_lead_time_days=180)

    outcomes = pipeline.process_file(write_csv(tmp_path), "csv/mueller_pricelist.csv", RECEIVED,
                                     supplier="Müller Präzisionsteile GmbH")

    assert [o.status for o in outcomes] == ["valid", "needs_review", "needs_review"]
    assert outcomes[0].quote.supplier == "Müller Präzisionsteile GmbH"  # filled from ingestion metadata
    assert outcomes[1].issues == ["unit price must be > 0, got 0.0"]
    assert "stop_reason=max_tokens" in outcomes[2].issues[0]  # an ExtractionError becomes a review reason
    assert outcomes[2].raw_text  # the reviewer still gets the text the model saw
    assert len(fake.calls) == 3  # one extraction per CSV row


def test_unparseable_file_goes_to_review_without_calling_the_llm(tmp_path):
    path = tmp_path / "quote.docx"
    path.write_bytes(b"")
    fake = FakeExtractor({})

    [outcome] = Pipeline(fake, max_lead_time_days=180).process_file(path, "other/quote.docx", RECEIVED)

    assert outcome.status == "needs_review" and "unsupported file type" in outcome.issues[0]
    assert fake.calls == []  # no tokens spent on a file we can't read
