"""Shared pytest fixtures. pytest loads this file automatically."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent


@pytest.fixture(scope="session")
def generated_data(tmp_path_factory) -> Path:
    """Run the synthetic generator once per test run, into a temp folder; return that folder."""
    script = ROOT / "scripts" / "generate_synthetic.py"
    spec = importlib.util.spec_from_file_location("generate_synthetic", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # scripts/ is not a package, so load the file directly

    out = tmp_path_factory.mktemp("generated")
    module.generate(out)
    return out


@pytest.fixture
def db():
    """A QuoteRepository on the local Postgres; everything a test writes is rolled back afterwards."""
    import psycopg

    from quote_pipeline.config import get_settings
    from quote_pipeline.storage.repository import QuoteRepository, connect

    try:
        conn = connect(get_settings().database_url)
    except psycopg.OperationalError:
        pytest.skip("Postgres is not running (start it with: docker compose up -d)")
    repo = QuoteRepository(conn)
    repo.init_schema()
    with conn.transaction(force_rollback=True):  # the test's writes never reach the real tables
        yield repo
    conn.close()
