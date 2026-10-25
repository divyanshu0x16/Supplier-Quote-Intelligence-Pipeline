"""The entry point for one incoming document: skip it if seen before, otherwise process and store it (M5)."""

from datetime import date
from pathlib import Path

import psycopg

from quote_pipeline.db import file_sha256, is_loaded, load_document
from quote_pipeline.pipeline import process_file


def ingest_file(conn: psycopg.Connection, path: Path, source_file: str, received_on: date,
                supplier: str | None = None) -> bool:
    """Returns True if the document was processed and stored, False if it was already in the database."""
    sha256 = file_sha256(path)
    if is_loaded(conn, sha256):  # checked BEFORE extraction, so a re-run costs no LLM calls
        return False
    outcomes = process_file(path, source_file, received_on, supplier)
    return load_document(conn, source_file, sha256, received_on, outcomes)
