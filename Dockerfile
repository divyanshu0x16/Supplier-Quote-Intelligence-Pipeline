FROM python:3.12-slim

# uv, pinned to the version used locally, copied from its official image
COPY --from=ghcr.io/astral-sh/uv:0.13.5 /uv /usr/local/bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

# 1. Dependencies first: this layer is cached and only rebuilt when pyproject.toml / uv.lock change.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

# 2. Then our code: editing a .py file only rebuilds from here, which takes seconds.
COPY src ./src
RUN uv sync --locked --no-dev

ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
# No --reload in a container. Secrets (ANTHROPIC_API_KEY) come from the environment at run time, never the image.
CMD ["uvicorn", "quote_pipeline.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
