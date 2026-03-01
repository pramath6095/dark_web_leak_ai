"""Centralised configuration for the query-generator service."""

from __future__ import annotations

from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """All tunables loaded from environment variables (or .env file)."""

    # ── LLM (OpenRouter) ──────────────────────────────────────────────────
    openrouter_api_key: str = Field(default="", alias="OPENROUTER_API_KEY")
    openrouter_model: str = Field(
        default="cognitivecomputations/dolphin-mistral-24b-venice-edition:free",
        alias="OPENROUTER_MODEL",
    )

    # ── Query generation ──────────────────────────────────────────────────
    queries_per_batch: int = Field(default=5, alias="QUERIES_PER_BATCH")
    max_generation_rounds: int = Field(default=5, alias="MAX_GENERATION_ROUNDS")
    initial_query_count: int = Field(default=20, alias="INITIAL_QUERY_COUNT")

    # ── Quality gate ──────────────────────────────────────────────────────
    duplicate_threshold: float = Field(
        default=0.5,
        alias="DUPLICATE_THRESHOLD",
        description="If > this fraction of new queries are duplicates, stop.",
    )

    # ── Company info file (optional, read at startup) ─────────────────────
    company_info_file: str = Field(default="", alias="COMPANY_INFO_FILE")

    model_config = {
        "env_file": ".env",
        "populate_by_name": True,
        "extra": "ignore",
    }


# Module-level singleton
settings = Settings()
