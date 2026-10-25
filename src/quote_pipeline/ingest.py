"""The entry point for one incoming document: skip it if seen before, otherwise process and store it."""

import hashlib
from datetime import date
from pathlib import Path

from quote_pipeline.pipeline import Pipeline
from quote_pipeline.storage.repository import QuoteRepository


def file_sha256(path: Path) -> str:
    """Fingerprint of the file's bytes: the same file always gives the same hash, whatever it's called."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ingest_file(repo: QuoteRepository, pipeline: Pipeline, path: Path, source_file: str,
                received_on: date, supplier: str | None = None) -> bool:
    """Returns True if the document was processed and stored, False if it was already in the database."""
    sha256 = file_sha256(path)
    if repo.is_loaded(sha256):  # checked BEFORE extraction, so a re-run costs no LLM calls
        return False
    outcomes = pipeline.process_file(path, source_file, received_on, supplier)
    return repo.save_document(source_file, sha256, received_on, outcomes)
