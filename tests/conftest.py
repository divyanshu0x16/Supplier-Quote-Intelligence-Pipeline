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
    """A connection to the local Postgres where everything a test writes is rolled back afterwards."""
    import psycopg

    from quote_pipeline.db import connect, init_schema

    try:
        conn = connect()
    except psycopg.OperationalError:
        pytest.skip("Postgres is not running (start it with: docker compose up -d)")
    init_schema(conn)
    with conn.transaction(force_rollback=True):  # the test's writes never reach the real tables
        yield conn
    conn.close()
