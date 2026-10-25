"""LLM extraction: RawQuote text -> ExtractedQuote, using Claude structured outputs (M3)."""

import logging
import time
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass

import anthropic
from dotenv import load_dotenv

from quote_pipeline.parsers import RawQuote
from quote_pipeline.schema import ExtractedQuote

load_dotenv()  # copies ANTHROPIC_API_KEY from .env into the environment, where the SDK looks for it
logger = logging.getLogger(__name__)

MODEL = "claude-haiku-5-5"  # cheapest current model
PRICE_PER_MTOK = {"claude-haiku-5-5": (0.10, 0.50)}  # USD per million tokens: (input, output)
SYSTEM_PROMPT = """\
You extract data from supplier price quotations for a procurement team that compares offers across suppliers.

The input is the plain text of ONE quote. It is one of:
- an email (headers, then the body),
- text extracted from a PDF, where table layout is lost and columns are separated only by spaces,
- one row of a CSV price list, shown as "Header: value" lines.

The team makes purchasing decisions on what you return, so report exactly what the document states.

Field rules:
- supplier: the company making the offer, as written in the document. Not the buyer. Do not infer it from a file
  name or an email address. If the document does not name it, use null.
- part_number: copy it exactly as written, character for character, even if it looks like a typo. Never correct it.
- unit_price: the price for ONE unit, as a plain number. Not a total, an extended price, or a price for the whole MOQ.
  Many European suppliers write a comma as the decimal separator and a dot for thousands: "0,09" is 0.09 and
  "1.234,56" is 1234.56. A price of 0 is a real value: return 0, not null. "Price on request", "TBD" or "POA" -> null.
- currency: the ISO 4217 code (USD, EUR, JPY, CNY, ...). "$" or "US$" -> USD, "€" -> EUR, "RMB" -> CNY.
  "¥" is used for both JPY and CNY: decide from the supplier's country or other clues in the document, and use null
  if it is still unclear.
- moq: the minimum order quantity in units, as an integer. "No MOQ", "n/a", "-" or not stated -> null.
- lead_time_days: the delivery lead time in calendar days. Convert weeks to days (1 week = 7 days).
  "ARO" means "after receipt of order". If a range is given (e.g. "4-6 weeks"), use the longer end.
- valid_until: the date the quote expires, as YYYY-MM-DD. Not the quotation date and not the email's sent date.
  Read dates in the supplier's own convention: "23.11.2026" (German) is day.month.year, "11/23/2026" (US) is
  month/day/year, "2026/11/23" (Japanese) is year/month/day. If only a duration is given (e.g. "valid for 30 days"),
  use null.

If a value is not stated, or you are not sure, use null. Never guess, and never calculate or correct a value beyond
the conversions above. A null goes to a human for review; a wrong value may never be caught.
"""

# The SDK itself retries rate limits (429), server errors (5xx), timeouts and dropped connections,
# with exponential backoff. 4 retries rides out a short outage; a 400 (our bug) is never retried.
default_client = anthropic.Anthropic(max_retries=4)


class ExtractionError(Exception):
    """The model answered, but not with a usable quote. The pipeline sends that quote to needs_review."""


@dataclass(frozen=True)
class Extraction:
    """An extracted quote plus what it cost to get it."""

    quote: ExtractedQuote
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: float
    cost_usd: float


@dataclass
class Timer:
    ms: float = 0.0


@contextmanager
def timed() -> Generator[Timer, None, None]:
    """M0's timed(), but it yields a Timer so the caller can read the duration afterwards."""
    timer = Timer()
    start = time.perf_counter()
    try:
        yield timer
    finally:
        timer.ms = (time.perf_counter() - start) * 1000  # recorded even if the block raised


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    price_in, price_out = PRICE_PER_MTOK[model]
    return (input_tokens * price_in + output_tokens * price_out) / 1_000_000


def extract(raw: RawQuote, client: anthropic.Anthropic = default_client) -> Extraction:
    """Send one quote's text to Claude and get back a validated ExtractedQuote, with cost and latency."""
    where = f"{raw.source_file} row {raw.row}" if raw.row else raw.source_file
    try:
        with timed() as timer:
            response = client.messages.parse(
                model=MODEL,
                max_tokens=2048,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": raw.text}],
                output_format=ExtractedQuote,  # the response is constrained to this schema
                output_config={"effort": "low"},  # reading one short document doesn't need deep reasoning
            )
    except anthropic.APIError as e:
        # Still failing after the SDK's retries: an outage or a bug, not a bad document. Don't blame the quote.
        logger.error("%s: API call failed after %.0f ms: %s", where, timer.ms, e)
        raise
    except ValueError as e:  # the output didn't parse into ExtractedQuote (e.g. JSON cut off mid-way)
        raise ExtractionError(f"{where}: model output did not match the schema: {e}") from e

    usage = response.usage
    cost = cost_usd(MODEL, usage.input_tokens, usage.output_tokens)
    logger.info("%s: %.0f ms, %d in / %d out tokens, $%.5f",
                where, timer.ms, usage.input_tokens, usage.output_tokens, cost)

    # "max_tokens" = output cut off; "refusal" = model declined. Either way there's no trustworthy quote.
    if response.stop_reason != "end_turn" or response.parsed_output is None:
        raise ExtractionError(f"{where}: no usable output (stop_reason={response.stop_reason})")

    return Extraction(
        quote=response.parsed_output,
        model=MODEL,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        latency_ms=timer.ms,
        cost_usd=cost,
    )


if __name__ == "__main__":
    # Usage: uv run python -m quote_pipeline.extract pdf/mueller_009.pdf [csv-row-number]
    import sys
    from pathlib import Path

    from quote_pipeline.parsers import parse_file

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    # Our logs only, not every HTTP request. Run with -m, this module's __name__ is "__main__", not
    # "quote_pipeline.extract", so its logger isn't under "quote_pipeline" and needs enabling too.
    for name in ("quote_pipeline", __name__):
        logging.getLogger(name).setLevel(logging.INFO)

    source_file = sys.argv[1] if len(sys.argv) > 1 else "email/acme_002.eml"
    row = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    quotes = parse_file(Path("data/generated") / source_file, source_file)
    raw = quotes[row - 1]  # PDFs and emails have one quote; for CSVs, pick the row
    print(raw.text, "\n---")
    print(extract(raw).quote)
