"""The real QuoteExtractor: RawQuote text -> ExtractedQuote via Claude structured outputs."""

import logging
import time
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass

import anthropic

from quote_pipeline.config import Settings
from quote_pipeline.domain.models import Extraction, ExtractedQuote, ExtractionError, RawQuote
from quote_pipeline.extraction.prompt import SYSTEM_PROMPT

logger = logging.getLogger(__name__)

PRICE_PER_MTOK = {"claude-haiku-5-5": (0.10, 0.50)}  # USD per million tokens: (input, output)


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    price_in, price_out = PRICE_PER_MTOK[model]
    return (input_tokens * price_in + output_tokens * price_out) / 1_000_000


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


class ClaudeExtractor:
    """Implements the QuoteExtractor protocol (domain/models.py) with Claude."""

    def __init__(self, client: anthropic.Anthropic, model: str):
        self.client = client  # injected: tests pass a fake, so they run offline and for free
        self.model = model

    @classmethod
    def from_settings(cls, settings: Settings) -> "ClaudeExtractor":
        """Build the real client. Called by the program's entry point, never at import time."""
        key = settings.anthropic_api_key.get_secret_value() if settings.anthropic_api_key else None
        client = anthropic.Anthropic(api_key=key, max_retries=settings.llm_max_retries)
        return cls(client, settings.llm_model)

    def extract(self, raw: RawQuote) -> Extraction:
        """Send one quote's text to Claude and get back a validated ExtractedQuote, with cost and latency."""
        where = f"{raw.source_file} row {raw.row}" if raw.row else raw.source_file
        try:
            with timed() as timer:
                response = self.client.messages.parse(
                    model=self.model,
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
        cost = cost_usd(self.model, usage.input_tokens, usage.output_tokens)
        logger.info("%s: %.0f ms, %d in / %d out tokens, $%.5f",
                    where, timer.ms, usage.input_tokens, usage.output_tokens, cost)

        # "max_tokens" = output cut off; "refusal" = model declined. Either way there's no trustworthy quote.
        if response.stop_reason != "end_turn" or response.parsed_output is None:
            raise ExtractionError(f"{where}: no usable output (stop_reason={response.stop_reason})")

        return Extraction(
            quote=response.parsed_output,
            model=self.model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            latency_ms=timer.ms,
            cost_usd=cost,
        )
