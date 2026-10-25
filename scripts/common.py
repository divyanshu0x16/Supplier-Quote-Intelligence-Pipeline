"""Shared wiring for the dev scripts: the "composition root" where real objects are built and connected
(~ Spring's application context). Library code never builds its own dependencies; this is the one place that does.
"""

import logging
from pathlib import Path

from generate_synthetic import QUOTE_DATE  # same folder: Python puts a script's own folder on the path

from quote_pipeline.config import Settings
from quote_pipeline.domain.catalog import SUPPLIERS
from quote_pipeline.extraction.extractor import ClaudeExtractor
from quote_pipeline.pipeline import Pipeline

DATA = Path("data/generated")
# Generated quotes are frozen at the generator's fake "today". date.today() would make results depend on the
# day you run (quotes "expire" over time). Real ingestion (M6's POST /ingest) uses the actual received date.
RECEIVED_ON = QUOTE_DATE


def setup_logging() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("quote_pipeline").setLevel(logging.INFO)  # our logs, not every HTTP request


def build_pipeline(settings: Settings) -> Pipeline:
    return Pipeline(ClaudeExtractor.from_settings(settings), settings.max_lead_time_days)


def generated_documents() -> list[tuple[Path, str]]:
    """(path on disk, stable source_file ID) for every generated document."""
    paths = sorted(p for p in DATA.rglob("*") if p.suffix in {".eml", ".csv", ".pdf"})
    return [(p, p.relative_to(DATA).as_posix()) for p in paths]


def supplier_from_filename(source_file: str) -> str | None:
    """Stand-in for "who sent it": our generated files are named <supplier-slug>_..."""
    slug = Path(source_file).name.split("_")[0]
    return next((s.name for s in SUPPLIERS if s.slug == slug), None)
