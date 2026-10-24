# Project: Supplier Quote Intelligence Pipeline

## Who I am
Backend engineer, 3 yrs Java/Spring WebFlux, Kafka, Couchbase, Postgres. New to Python
and data engineering. Building this to learn for an Apple Forward-Deployed Engineer
(Supply Chain) interview, so I must be able to explain and defend every line.

## What we're building
An ETL pipeline for supplier quotes:
1. Ingest messy supplier quotes: PDFs, .eml emails, CSVs (we generate synthetic ones)
2. Parse raw text (pdfplumber, Python email module, pandas)
3. LLM structured extraction into a Pydantic schema: supplier, part_number, unit_price,
   currency, moq, lead_time_days, valid_until, source_file
4. Validate: Pydantic + business rules (price > 0, lead time sane, known part numbers);
   failures go to a needs_review table with the reason
5. Load into PostgreSQL (idempotent: re-running the same file must not duplicate rows)
6. FastAPI endpoints: /quotes, /compare?part=X&max_lead_days=N, /review-queue,
   POST /ingest
7. docker-compose (app + postgres), README written for a business user
8. Eval: hand-label ~20 docs, script that reports per-field extraction accuracy

## Stack
Python 3.12, uv, Pydantic v2, pdfplumber, pandas, SQLAlchemy or psycopg, FastAPI,
pytest, Docker. LLM: Anthropic API with structured output (key in .env, never committed).

## How to work with me (important)
- Teach, don't dump. Before each step, explain the concept in 3-5 lines and relate it
  to Java/Spring where useful (e.g. Pydantic ~ DTO + Bean Validation, FastAPI ~ Spring MVC).
- Make me write the core logic myself: parsing, validation rules, the extraction prompt,
  SQL, the idempotent load. Give me a function signature, a TODO and hints; review my code
  after I write it. You may write boilerplate (config, Dockerfile, test fixtures,
  synthetic data generator).
- Small steps. One milestone at a time; stop and wait for me before moving on.
- After each milestone, ask me 3 interview-style questions about what we built
  (trade-offs, failure modes, "why not X?") and correct my answers.
- Flag Python idioms I'm getting wrong (I'll write Java-style Python).
- Keep a LEARNING_LOG.md: concepts covered, decisions made and why, open questions.

## Milestones
M0 Project setup with uv, Python crash course on what we need (typing, dataclasses vs Pydantic, context managers)
M1 Synthetic data generator: 30-50 quotes across PDF/email/CSV with realistic mess
M2 Parsers -> raw text per document, with tests
M3 LLM extraction with Pydantic schema, retries, cost/latency logging
M4 Validation + needs_review routing
M5 Postgres schema + idempotent load (discuss ETL vs ELT here)
M6 FastAPI endpoints + tests
M7 Docker compose + README
M8 Eval script + accuracy report; discuss how I'd improve weak fields
Stretch: natural-language query endpoint (LLM -> safe parameterized filter, never raw SQL)