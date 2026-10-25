"""The API's composition root: how each endpoint gets its dependencies (~ Spring beans + @Autowired).

Tests swap these out with `app.dependency_overrides[...]` (~ @MockBean).
"""

from collections.abc import Iterator
from functools import lru_cache
from typing import Annotated

from fastapi import Depends

from quote_pipeline.config import Settings, get_settings
from quote_pipeline.extraction.extractor import ClaudeExtractor
from quote_pipeline.pipeline import Pipeline
from quote_pipeline.storage.repository import QuoteRepository, connect


def get_repository(settings: Annotated[Settings, Depends(get_settings)]) -> Iterator[QuoteRepository]:
    """One connection per request, closed when the request ends (code after `yield` runs then).

    Fine for a demo; under real load you'd use a connection pool (psycopg_pool) instead.
    """
    with connect(settings.database_url) as conn:
        yield QuoteRepository(conn)


@lru_cache
def get_pipeline() -> Pipeline:
    """One Pipeline (and one Anthropic client) for the whole app: a singleton, like a default Spring bean."""
    settings = get_settings()
    return Pipeline(ClaudeExtractor.from_settings(settings), settings.max_lead_time_days)


Repository = Annotated[QuoteRepository, Depends(get_repository)]
PipelineDep = Annotated[Pipeline, Depends(get_pipeline)]
