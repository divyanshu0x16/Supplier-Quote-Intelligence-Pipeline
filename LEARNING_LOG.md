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
