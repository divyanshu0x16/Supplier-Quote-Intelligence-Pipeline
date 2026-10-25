"""All configuration in one place (~ Spring's @ConfigurationProperties). Values come from env vars or .env."""

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")  # env var DATABASE_URL -> database_url

    # LLM
    anthropic_api_key: SecretStr | None = None  # None: the SDK falls back to its own credential lookup
    llm_model: str = "claude-haiku-5-5"  # cheapest current model; change only with M8 evidence
    llm_max_retries: int = 4  # SDK retries 429 / 5xx / timeouts / connection errors with backoff

    # Storage
    database_url: str = "postgresql://quotes:quotes@localhost:5432/quotes"

    # Business rules (decisions for procurement to confirm, not engineering constants)
    max_lead_time_days: int = 180


@lru_cache
def get_settings() -> Settings:
    """Read the settings once and reuse them (FastAPI will inject this in M6)."""
    return Settings()
