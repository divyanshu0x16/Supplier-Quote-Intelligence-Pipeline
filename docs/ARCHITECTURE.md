# Architecture

Technical overview for engineers. For how to *use* the tool, see the [README](../README.md).

---

## The problem

Suppliers send quotes in whatever format they like:

- a PDF with a price table on page 2
- an email that says *"we can do $4.10/unit if you take 500+, ~3 weeks"*
- a CSV export with inconsistent column names and currencies

Comparing these by hand is slow and error-prone. This pipeline reads them, pulls out
the facts that matter, checks them, and stores them in one place you can query.

## What gets extracted

Every quote is reduced to the same set of fields:

| Field            | Example            | Meaning                                  |
|------------------|--------------------|------------------------------------------|
| `supplier`       | Acme Components    | Who sent the quote                       |
| `part_number`    | AX-4410            | Which part is being quoted               |
| `unit_price`     | 4.10               | Price per unit                           |
| `currency`       | USD                | Currency of the price                    |
| `moq`            | 500                | Minimum order quantity                   |
| `lead_time_days` | 21                 | Days from order to delivery              |
| `valid_until`    | 2026-12-31         | Date the quote expires                   |
| `source_file`    | acme_q3.pdf        | Original document, for traceability      |

---

## How the pipeline works

```mermaid
flowchart LR
    subgraph Ingest
        A1[PDF quotes]
        A2[.eml emails]
        A3[CSV files]
    end

    subgraph Parse
        P1[pdfplumber]
        P2[Python email module]
        P3[Python csv module]
    end

    A1 --> P1
    A2 --> P2
    A3 --> P3

    P1 & P2 & P3 --> T[Raw text per document]
    T --> L[LLM extraction<br/>Claude → Pydantic schema]
    L --> V{Validation<br/>schema + business rules}
    V -- valid --> DB[(PostgreSQL<br/>quotes)]
    V -- invalid --> R[(PostgreSQL<br/>needs_review)]
    DB --> API[FastAPI]
    R --> API
    API --> U[Buyer / dashboard]
```

### Stage by stage

1. **Ingest:** collect documents from a folder or via `POST /ingest`. Each file is fingerprinted (SHA-256);
   a file seen before is skipped before any LLM call.
2. **Parse:** convert each format to plain text. Nothing is interpreted yet.
3. **Extract:** an LLM (Anthropic Claude, structured output) reads the text and fills
   in the fields above. The output must match a strict Pydantic schema.
4. **Validate:** schema checks (types, required fields) plus business rules:
   - price must be greater than 0
   - lead time must be in a sane range
   - part number must be a known part

   Anything that fails goes to a **review queue** along with the reason, so it is never
   silently dropped.
5. **Load:** write to PostgreSQL. Loading is **idempotent**, so re-processing the same
   file never creates duplicate rows.
6. **Serve:** a REST API for querying, comparing and reviewing quotes.

### What happens to a single quote

```mermaid
sequenceDiagram
    participant S as Supplier file
    participant P as Parser
    participant L as LLM extractor
    participant V as Validator
    participant DB as PostgreSQL

    S->>P: acme_q3.pdf
    P->>L: raw text
    L->>V: {supplier, part_number, unit_price, ...}
    alt passes all checks
        V->>DB: insert into quotes
    else fails a check
        V->>DB: insert into needs_review (with reason)
    end
```

---

## API

```bash
docker compose up -d --build                           # Postgres + API in containers
# or, for development with auto-reload:
docker compose up -d db && uv run uvicorn quote_pipeline.api.app:app --reload
```

| Method | Endpoint                                 | Purpose                                        |
|--------|------------------------------------------|------------------------------------------------|
| POST   | `/ingest`                                | Upload a PDF, email or CSV; returns each quote's verdict. Re-uploading the same file is skipped. |
| GET    | `/quotes?part=CN-2201`                   | Validated quotes, optionally filtered by part or supplier |
| GET    | `/compare?part=CN-2201&max_lead_days=30` | Offers still valid today, cheapest first (approximate USD for ranking across currencies) |
| GET    | `/review-queue`                          | Quotes that need a person, with the reasons and what was extracted |

---

## Measuring quality

A synthetic data generator writes 42 deliberately messy quotes together with their correct answers
(`ground_truth.jsonl`). `scripts/evaluate.py` runs the pipeline on them and reports routing accuracy and
**accuracy per field**, so any prompt or model change is measured. Current result (Claude Haiku 5.5):
41/42 routed as expected, all 8 planted faults caught, about $0.01 for the whole run.

---

## Tech stack

| Concern         | Tool                                 |
|-----------------|--------------------------------------|
| Language        | Python 3.12                          |
| Packaging       | uv                                   |
| Schema / validation | Pydantic v2                      |
| Parsing         | pdfplumber, `email` and `csv` (stdlib) |
| LLM             | Anthropic API (structured output)    |
| Database        | PostgreSQL                           |
| API             | FastAPI                              |
| Tests           | pytest                               |
| Deployment      | Docker Compose (app + Postgres)      |

## Project layout

```
.
├── src/quote_pipeline/   # the pipeline itself (only code that ships to production)
│   ├── config.py         #   all settings in one place (env vars / .env)
│   ├── domain/           #   models, catalog, business rules: pure logic, no I/O
│   ├── parsing.py        #   email / CSV / PDF -> text
│   ├── extraction/       #   Claude extractor + the extraction prompt
│   ├── storage/          #   Postgres repository + schema.sql
│   ├── pipeline.py       #   parse -> extract -> validate (extractor injected)
│   └── ingest.py         #   skip already-seen files, otherwise process + store
├── scripts/              # dev tools: data generator, pipeline runs (and the wiring of real objects)
├── Dockerfile            # the API image
├── docker-compose.yml    # Postgres (with pgvector) + the API
├── learning/             # crash-course exercises
├── data/generated/       # generated sample documents (gitignored)
├── tests/                # pytest suite
├── pyproject.toml        # dependencies and tool config
├── .env.example          # copy to .env and fill in secrets
└── LEARNING_LOG.md       # concepts, decisions, open questions
```

---

## Developer setup

```bash
brew install uv                                  # once
uv sync                                          # create venv and install dependencies
cp .env.example .env                             # then add your ANTHROPIC_API_KEY
docker compose up -d db                          # Postgres (the DB tests skip without it)
uv run pytest                                    # run tests (no LLM calls, no cost)
uv run python scripts/generate_synthetic.py      # sample documents + ground truth
uv run python scripts/evaluate.py                # accuracy report (~$0.01)
uv run python scripts/ingest_generated.py        # load samples into Postgres
```