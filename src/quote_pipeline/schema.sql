-- Safe to run repeatedly: every statement is IF NOT EXISTS.

CREATE TABLE IF NOT EXISTS documents (
    id          BIGSERIAL PRIMARY KEY,
    source_file TEXT        NOT NULL,
    sha256      TEXT        NOT NULL UNIQUE,  -- fingerprint of the file's bytes: the idempotency key
    received_on DATE        NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Valid quotes only. NOT NULL everywhere validation requires a value: the database rejects an incomplete
-- quote even if the Python code has a bug (defence in depth).
CREATE TABLE IF NOT EXISTS quotes (
    id             BIGSERIAL PRIMARY KEY,
    document_id    BIGNT        NOT NULL REFERENCES documents (id),
    row_num        INT,                     -- CSV data row; NULL for PDFs and emails
    supplier       TEXT          NOT NULL,
    part_number    TEXT          NOT NULL,
    unit_price     NUMERIC(14,4) NOT NULL,  -- money: exact decimal, never float
    currency       CHAR(3)       NOT NULL,
    moq            INT,
    lead_time_days INT           NOT NULL,
    valid_until    DATE          NOT NULL,
    raw_text       TEXT          NOT NULL,  -- what the model saw: lets us re-extract later without the file
    model          TEXT          NOT NULL,
    input_tokens   INT           NOT NULL,
    output_tokens  INT           NOT NULL,
    cost_usd       NUMERIC(10,6) NOT NULL,
    latency_ms     INT           NOT NULL,
    -- One quote per (document, row). NULLS NOT DISTINCT: without it, two NULL row_nums count as different,
    -- so a PDF's quote could be inserted twice.
    UNIQUE NULLS NOT DISTINCT (document_id, row_num)
);

CREATE TABLE IF NOT EXISTS needs_review (
    id          BIGSERIAL PRIMARY KEY,
    document_id BIGINT      NOT NULL REFERENCES documents (id),
    row_num     INT,
    reasons     TEXT[]      NOT NULL,  -- every problem found, in plain English
    extracted   JSONB,                 -- what the model returned, if anything, for the reviewer to correct
    raw_text    TEXT,                  -- NULL when the file couldn't be parsed at all
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE NULLS NOT DISTINCT (document_id, row_num)
);

CREATE INDEX IF NOT EXISTS quotes_part_number_idx ON quotes (part_number);  -- for /compare?part=X in M6
