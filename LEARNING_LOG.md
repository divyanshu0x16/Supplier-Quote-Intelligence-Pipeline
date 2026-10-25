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
- Fill null currency from supplier master data?
- Sequential run takes ~60 s for 42 calls; concurrency (thread pool) or the Batches API (50% cheaper) for bulk.
