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
