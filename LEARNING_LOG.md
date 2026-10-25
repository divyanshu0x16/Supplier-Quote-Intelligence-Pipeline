# Learning Log

## M0 — Project setup
**Concepts:**
- **uv**: one tool for Python versions, venvs, dependency resolution and locking (~ Maven + SDKMAN).
  `uv add/remove` edit pyproject + lock + venv; `uv lock` re-resolves the lock only; `uv sync` installs exactly what the lock says.
- **Virtual env (`.venv/`)**: per-project interpreter + packages, i.e. a per-project classpath on disk.
- **Type hints** are not enforced at runtime. Syntax errors in a hint crash at import
  (`tuple(str, float)`), but a valid-but-wrong hint (`tuple[...]` vs `list[tuple[...]]`) runs silently.
  Only a type checker (Pylance/mypy) catches it. Pydantic enforces hints at runtime, but only on model fields.
- Idioms: `X | None` (~ Optional), `if not xs:` for empty checks, `min(xs, key=lambda ...)` (~ Comparator.comparing),
  `_` for ignored values, return `[]` not `None` for "no results", list comprehensions (~ stream filter/map).
- **dataclass vs Pydantic**: `@dataclass` (~ record / Lombok @Data) stores anything, so `"4.10"` stays a str and
  `"banana"` is accepted. `BaseModel` (~ DTO + Bean Validation) coerces `"4.10"` to `4.1`, and raises a
  `ValidationError` (field, reason, input value) for `-1` with `gt=0` and for `"banana"`. Pydantic needs keyword args.
  Rule: dataclass for trusted internal data, Pydantic at boundaries (LLM output, files, API).
- **Context managers (`with`)** (~ try-with-resources): guaranteed cleanup via `__enter__`/`__exit__`.
  `@contextmanager` + a generator: code before `yield` = setup, after = cleanup. The body's exception is
  re-raised *at the yield*, so cleanup must be in `finally`. Without it, `divide took ...` never printed:
  failed calls go unlogged, so latency stats look better than reality (matters for M3 LLM calls, M5 rollbacks).
- **Generators**: functions with `yield` are lazy, resumable iterators. `Generator[Yield, Send, Return]`;
  usually only the first parameter matters.

**Decisions:**
- `src/` layout + `pyproject.toml` (~ pom.xml/build.gradle) managed by uv.
- Dependencies added per milestone, not up front.
- Commit `uv.lock` (reproducible builds; this is an app, not a library).
- Python pinned to 3.12 via `.python-version` (uv had picked 3.13); matches the planned Docker image.

**Open questions:**
-

## M1 — Synthetic data generator
**Concepts:**
- **Ground truth alongside data**: the generator writes each document AND the correct answers (`ground_truth.jsonl`),
  so we can measure the pipeline exactly (tests in M2-M4, accuracy in M8).
- **Seeded randomness**: `rng` is passed in (like injecting a `Clock`); same seed gives byte-identical output.
- `@dataclass(frozen=True)` (~ record) for reference data; plain `@dataclass` for `Truth` because we edit it after creation.
  `frozen` protects the object, not the dict holding it (~ `final Map` that still allows `put`).
- Idioms: `//` floor division vs `/` always float; f-string format specs `f"{x:,.2f}"`; `x or ""` (careful: `0` is falsy);
  `enumerate(xs, start=1)`; functions as values (~ method references); `xs[-1]` = last; `if __name__ == "__main__":` (~ main).
- `field(default_factory=list)`: each instance gets its own list. `def f(xs=[])` would share ONE list across calls;
  dataclasses refuse `= []` outright.
- Real-world mess we generate: decimal commas + `;` CSVs, dd.mm vs mm/dd dates, "2 wks ARO", quoted-printable emails
  (`€` -> `=E2=82=AC`), PDFs that lose table structure ("a PDF is a drawing, not data"), distractor totals and dates.

**Decisions:**
- Generator moved out of the package (it needs dev-only reportlab): now `scripts/generate_synthetic.py`, run with `uv run python scripts/generate_synthetic.py`.
- reportlab is a dev dependency: only the generator needs it.
- Generated data is gitignored and reproducible from the seed.
- Truth records what the document SAYS (typo'd part stays typo'd); `expected_valid` / `issues` record what M4 should decide.
- Faults are planned (4 types x 2), not random per quote, so every rule is guaranteed something to catch.

**Open questions:**
- Faults landed 6 in CSVs, 2 in PDFs, 0 in emails (seed 42). Plan faults per format instead?
- ~~Expiry: compare against quote date or "now"?~~ **Both, for different questions.** "Still usable?" = `valid_until >= today`, computed at query time in M6 (a stored flag would go stale). "Makes sense?" = `valid_until >= quote date`, an M4 needs_review rule that catches dd/mm vs mm/dd misreads and re-forwarded old quotes.

## M2 — Parsers
**Concepts:**
- A parser only gets the words out; it doesn't interpret (`0,40` stays `"0,40"`). Interpretation is M3's job.
- Email: `message_from_bytes(..., policy=policy.default)` + `get_body(...)` + `get_content()` decodes quoted-printable.
  Headers: `msg["From"]` or `msg.get("From")`, not both (`msg.get["From"]` -> "not subscriptable").
- CSV: `utf-8-sig` strips Excel's BOM; `csv.Sniffer` detects `,` vs `;`; `DictReader` maps header -> value.
  Built-in `csv` instead of pandas, because pandas infers types (`1000` -> `1000.0`, empty -> NaN).
- PDF: pdfplumber reads text per page; table structure is lost ("a PDF is a drawing, not data").
- pytest: `tmp_path` fixture (~ `@TempDir`), injected by parameter name; `parametrize` (~ `@ParameterizedTest`);
  `pytest.raises` (~ `assertThrows`); session-scoped fixtures in `conftest.py`.

**Decisions:**
- Every parser returns `list[RawQuote]` (one per quote): PDF/email -> 1, CSV -> 1 per row. `(source_file, row)` is the
  same key as ground truth.
- `path` (where to read, machine-specific) vs `source_file` (stable ID for ground truth / DB / users).
- Fail loudly with a reason (`ValueError`) for attachment-only emails and text-less (scanned) PDFs. The ingest step
  will catch it per file and route the file to needs_review.
- Two date checks: "still usable?" = valid_until >= today, at query time (M6); "makes sense?" = valid_until >= quote
  date, at load time (M4).
- `pdfplumber` is a runtime dependency; reportlab stays dev-only.
- `parse_file` dispatches on extension via a dict of functions (strategy pattern).
- End-to-end test: parsed `(source_file, row)` keys must equal ground truth's exactly (not just the count).

**Open questions:**
- Parsers take a `Path`; `POST /ingest` (M6) receives bytes. Change to accept bytes?
- Attachment-only emails: parse the attached PDF instead of rejecting.
- Scanned PDFs need OCR (out of scope; mention in interviews).
- Faults landed in 0 emails (seed 42); plan faults per format.

## M3 — LLM extraction
**Decisions:**
- The extraction schema (`ExtractedQuote`) has shape and types only; no business rules (`gt=0` would hide a zero price
  as an extraction error). Validation is M4.
- Every field is nullable but required (`x: T | None`, no default): the model must say `null` explicitly, and it never
  has to invent a value to satisfy the schema. Missing values become needs_review reasons, not hallucinations.
- Don't ask the LLM for what we already know: `source_file` / `row` come from the parser. **The supplier for CSV rows
  comes from ingestion metadata** (sender / upload form), not from the model guessing from a file name. The prompt
  still allows `null`.
- Structured outputs (`client.messages.parse(output_format=ExtractedQuote)`): the schema is enforced by the API, so
  there's no "please return JSON" prompting or `json.loads`.
- Model: `claude-haiku-5-5` (cheapest, $0.10 / $0.50 per MTok) at `effort: "low"`. Upgrade only if M8 shows a weak field.
- First tries with a one-line prompt: 20/21 fields correct on the 3 trickiest files. Judge prompt changes with M8 numbers,
  not by eye.
- Retries: the SDK already retries 429 / 5xx / timeouts / connection errors with backoff (`max_retries=4`). 400s are
  never retried (our bug). An APIError that survives retries is re-raised: it's an outage, not a bad document, so it
  must not land in needs_review.
- `ExtractionError` (own exception type) when the model answered but unusably: `stop_reason` max_tokens / refusal, or
  output that doesn't parse. The pipeline catches it per quote and routes to needs_review. Own type so we never
  accidentally swallow real bugs with a broad `except Exception`.
- Every call logs latency, tokens and cost; `Extraction` carries them so M5 can store them per quote.
- Measured: ~1,650 input / ~80 output tokens, ~1.3-1.9 s, ~$0.0002 per quote (all 42 ~ $0.01). Input is mostly the
  fixed prompt + schema: at scale that's the prompt-caching candidate.

**Concepts:**
- `logging.getLogger(__name__)` (~ SLF4J `LoggerFactory.getLogger(X.class)`); libraries create loggers, only the
  entry point configures them. Gotcha: under `python -m`, `__name__` is `"__main__"`.
- Dependency injection by default argument (`client=default_client`) lets tests pass a fake: offline, free, no key.
- A context manager can `yield` a value (`with timed() as timer:`), like `with open(...) as f`.

**Open questions:**
- Wire it together: parse -> extract -> fill supplier from ingestion metadata -> validate (M4).

## M4 — Validation + needs_review
**Built:** `validation.validate(quote, received_on) -> list[str]` (empty = valid); `pipeline.process_file()` =
parse -> extract -> fill supplier from metadata -> validate, one `Outcome` per quote; `scripts/run_pipeline.py`
runs all 42 and compares with ground truth.

**Result (seed 42, Haiku 5.5):** routing 41/42 correct, all 8 planted faults caught; field accuracy 7/7 fields at
42/42 except currency 41/42; total cost $0.0089.

**Interview cheat sheet:**
- *Two kinds of error:* a false alarm (valid quote -> review) costs a reviewer seconds; a silent error (wrong value
  marked valid) costs money and nobody notices. The design deliberately trades silent errors for false alarms.
- *The one miss:* `¥16` with no country clue -> the model returned `currency: null` as the prompt instructs ->
  review. Correct, cautious behaviour; the ground truth assumed JPY. Possible fix: fill null currency from supplier
  master data (same pattern as supplier). Left as-is on purpose.
- *Rules return reasons, not booleans:* the reason is what a reviewer reads, and all reasons are reported at once.
- *Thresholds are business decisions:* `MAX_LEAD_TIME_DAYS = 180` needs procurement's sign-off, ideally per category.
- *Expiry:* load-time check = `valid_until >= received_on` (catches dd/mm misreads, stale forwards). "Still usable
  today?" is a query-time filter in M6, because a stored flag goes stale.
- *Failure routing:* bad document (parser ValueError, ExtractionError) -> needs_review; infrastructure failure
  (APIError after retries) -> stop the run; never blame a document for an outage.
- *Metadata beats inference:* supplier (and received date) come from how the document arrived, not from the LLM.

**Open questions:**
- ~~Fill null currency from supplier master data?~~ **Decided: no.** Keep the honest flag: an ambiguous `¥` goes to review (33 valid / 9 review vs the ideal 34 / 8). A wrong currency would be a 20x price error nobody notices.
- Sequential run takes ~60 s for 42 calls; concurrency (thread pool) or the Batches API (50% cheaper) for bulk.

## M5 — Postgres + idempotent load
**Built:** `docker-compose.yml` (pgvector/pgvector:pg17), `schema.sql` (documents / quotes / needs_review),
`db.py` (connect, init_schema, load_document), `ingest.py` (`ingest_file`: hash -> skip or process + load),
`scripts/ingest_generated.py`. Driver: psycopg 3, plain SQL.

**Result:** run 1 = 27 documents, 33 valid quotes, 9 in review, 79 s, $0.0069 stored cost. Run 2 = 0 loaded,
27 skipped, 1 s, $0.

**Interview cheat sheet:**
- *Idempotency key = SHA-256 of the file's bytes,* not the file name. Same bytes -> skipped before any LLM call
  (no duplicates AND no cost). Same name with new content -> a new document (an updated price list).
- *One transaction per document* (all-or-nothing). A crash mid-CSV leaves no trace; a re-run resumes after the
  last finished document. That's checkpointing for free (the answer to "API dies at quote 2,000").
- *Belt and braces:* `ON CONFLICT (sha256) DO NOTHING` covers two runs racing past the `is_loaded` check;
  `NOT NULL` columns make the database reject an incomplete "valid" quote even if Python has a bug.
- *`UNIQUE NULLS NOT DISTINCT (document_id, row_num)`:* by default SQL treats NULLs as all different, so a PDF's
  quote (row NULL) could be inserted twice. Postgres 15+ fixes that with NULLS NOT DISTINCT.
- *Money is `NUMERIC`, never float.* (0.1 + 0.2 != 0.3 in floating point.)
- *psycopg 3 gotcha:* the default connection silently opens a transaction that only saves on `commit()`. We use
  `autocommit=True` plus explicit `with conn.transaction():` blocks.
- *Tests* run inside `conn.transaction(force_rollback=True)`: real database, nothing left behind.

**ETL vs ELT:**
- *ETL* (Extract, Transform, Load): transform BEFORE loading. That's us: parse + LLM + validate, then store clean rows.
- *ELT:* load raw data first, transform later inside the database/warehouse (dbt, Snowflake, BigQuery).
  Re-transforming is cheap because the raw data is already there.
- *Why ETL here:* the transform is an LLM call, not SQL, so it can't run inside the database; and the business
  wants clean, validated rows, not raw documents.
- *The ELT idea we kept:* `raw_text` is stored with every quote. A better prompt or model (M8/M9) can re-extract
  everything from the database without the original files.

**Open questions:**
- An updated price list (same name, new hash) adds new rows, but the old quotes stay. Supersede them
  (valid_from / valid_to, or keep only the latest document per supplier + part)?
- Schema changes: `CREATE TABLE IF NOT EXISTS` is fine for now; production would use migrations (Alembic ~ Flyway).

## Refactor — layers, config, dependency injection (before M6)
**Why:** flat modules were fine while small, but there were real problems: an API client and `load_dotenv()` ran
at import time, configuration was spread over four files, and `process_file()` was hard-wired to Claude (no
offline pipeline tests).

**Layout (dependencies point inward; domain imports nothing else):**
```
domain/ (models, catalog, validation)  <-  parsing, extraction/, storage/  <-  pipeline, ingest  <-  scripts / API
```

**What changed:**
- `config.Settings` (pydantic-settings, ~ @ConfigurationProperties) is the single source of configuration;
  `get_settings()` is cached. python-dotenv removed.
- No side effects at import: `ClaudeExtractor.from_settings()` and `connect()` are called by entry points.
- Classes only where something holds dependencies: `ClaudeExtractor` (client), `QuoteRepository` (connection),
  `Pipeline` (extractor). Stateless logic (`validate`, parsers) stays as plain functions.
- `QuoteExtractor` is a `typing.Protocol` (~ a Java interface, but structural: a class matches by having
  `.extract()`, without declaring `implements`). `Pipeline` depends on the protocol, not on Claude.
- `scripts/common.py` is the composition root (~ Spring application context): the only place that builds real
  objects. The extraction prompt now lives in `extraction/prompt.py`.
- New `tests/test_pipeline.py`: the whole pipeline offline with a `FakeExtractor`.

**Python vs Java structure (interview / sanity):** module = unit of organisation; functions are first-class
(a one-method interface is usually just a function); DI by constructor/default args, no container; flat over
nested until it hurts. Structure is added when it pays for itself, not up front.

## M6 — FastAPI
**Built:** `api/app.py` (routes), `api/schemas.py` (response DTOs), `api/dependencies.py` (the API's composition
root), `domain/fx.py`, repository queries (`list_quotes`, `offers_for_part`, `review_queue`). Run:
`uv run uvicorn quote_pipeline.api.app:app --reload`, then http://localhost:8000/docs.

**Interview cheat sheet:**
- *FastAPI ~ Spring MVC:* decorators ~ `@GetMapping`; Pydantic response models ~ DTOs, and they generate the
  OpenAPI `/docs` page; `Depends()` ~ `@Autowired`; `app.dependency_overrides` ~ `@MockBean` in tests.
- *`def` vs `async def`:* the ingest endpoint blocks on the LLM call, so it's a plain `def`; FastAPI runs it in a
  worker thread instead of stalling the event loop. `async def` + a blocking call would freeze every request.
- *Dependency lifetimes:* repository = one connection per request (a `yield` dependency closes it afterwards,
  like a context manager); pipeline = singleton via `lru_cache` (one Anthropic client). Production: a connection pool.
- *Comparing across currencies:* rank by approximate USD (fixed rates), but always return the original price and
  currency. Real system: daily FX table, convert at the quote date.
- *Expiry at query time:* `/compare` filters `valid_until >= today` when asked, so results never go stale.
- *Outage -> 503:* an `anthropic.APIError` after retries becomes "retry later"; nothing is stored for that file,
  so the retry processes it cleanly (one transaction per document).
- *Uploads:* parsers read from a path, so uploads go to a temporary folder that's deleted afterwards (the
  bytes-vs-path open question from M2). Directory parts of the client's filename are dropped.
- *A test found a real bug:* `csv.Sniffer` raises `csv.Error` (not a ValueError) on a single-column file, which
  would have crashed the upload instead of routing it to review. Fixed with a fallback to comma + a regression test.

**Open questions:**
- Upload size limit and file-type checks before parsing; authentication (who may ingest / review?).
- A "resolve" endpoint for the review queue (a reviewer corrects a quote, it moves to `quotes`), which is also
  where M9's human-reviewed examples would come from.

## M7 — Docker + README
**Built:** `Dockerfile` (python:3.12-slim + uv 0.13.5), `.dockerignore`, an `app` service in `docker-compose.yml`;
`README.md` rewritten for a buyer; the technical README moved to `docs/ARCHITECTURE.md`.

**Interview cheat sheet:**
- *Layer caching:* copy `pyproject.toml` + `uv.lock` and install dependencies BEFORE copying the code, so a code
  change rebuilds in seconds (verified: the dependency layer shows CACHED).
- *`uv sync --locked --no-dev`:* exactly the lockfile (fails if it's stale), no test tools in production.
- *Secrets at run time, not build time:* `.env` is in `.dockerignore`; compose passes it with `env_file`. Anyone
  with an image can read what's baked into it.
- *Service names, not localhost:* inside Docker, `localhost` is the container itself; the app reaches Postgres
  at `db:5432`. `depends_on: condition: service_healthy` waits for Postgres to accept connections.
- *`--host 0.0.0.0`:* listen on all interfaces, or the API is unreachable from outside the container.
- *Image size* 595 MB, mostly PDF libraries; a multi-stage build could shrink it.
- *Two audiences, two documents:* README for the user (what it does, how to read results, limits, the
  data-privacy note that quotes go to an AI service); ARCHITECTURE.md for engineers.

**Open questions:**
- Production hardening: non-root user in the image, healthcheck on the app, multiple uvicorn workers,
  HTTPS via a reverse proxy, authentication.

## M9 — RAG: designed, not built (revision notes)
Decided not to build: the fundamentals are the same as an earlier RAG project; only the stack differs.

**The pattern:** Retrieve relevant text -> Augment the prompt with it -> Generate.

| Block | What it does | Typical | In this project's design |
|---|---|---|---|
| Embedding model | text -> vector; similar meaning = nearby vectors | OpenAI embeddings | Voyage AI (Anthropic's recommended provider; Anthropic has no embeddings model) or a local model |
| Vector store | store vectors, find nearest fast | Pinecone | pgvector inside the existing Postgres (no new database) |
| Retrieval | k most similar items | chunks of one document | verified past quotes + their correct extraction |
| Augmentation | put results in the prompt | "answer using this context" | "here's how similar quotes were correctly read" |
| Orchestration | glue | LangChain | ~30 lines of own code; a framework would hide more than it helps |

**Retrieval-augmented extraction (dynamic few-shot):** retrieve human-verified quotes similar to the new one
(same supplier habits: decimal commas, "wks ARO", which ¥) and include them as worked examples. Examples come
from resolved review-queue items, so the system improves with use (e.g. kanto_004's ¥ resolved once helps every
later Kanto quote).

**Traps an interviewer will probe:**
1. *Leakage:* a test quote must never retrieve its own answer. Split examples and eval data (train/test).
2. *Is vector search needed?* Try the simple version first: "last 3 verified quotes from the same supplier"
   (a SQL filter, no embeddings). Realistic answer: filter by supplier, then rank by similarity.
3. *Cost:* examples lengthen every prompt (more input tokens); the eval decides whether the gain is worth it.

**Why it wasn't measurable here:** the M8 eval is saturated (98-100% per field), so RAG could show no real gain.
The honest line: "on harder real-world data I'd expect a gain; my synthetic set saturated, so I'd harden the
eval first."

**Classic RAG vocabulary to revise:** chunking (size / overlap), embedding dimensions, cosine similarity, top-k,
HNSW / IVF indexes (approximate nearest neighbour), hybrid search (keyword BM25 + vectors), re-ranking,
metadata filters, evaluating retrieval (recall@k) separately from generation.
