"""Centralised, env-driven configuration for the scraper service."""

from __future__ import annotations

from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """All tunables are loaded from environment variables (or .env file)."""

    # ── Tor proxy ──────────────────────────────────────────────────────────
    tor_proxy_host: str = Field(default="127.0.0.1", alias="TOR_PROXY_HOST")
    tor_proxy_port: str = Field(default="9050", alias="TOR_PROXY_PORT")

    # ── Concurrency ────────────────────────────────────────────────────────
    max_workers: int = Field(default=3, alias="MAX_WORKERS")
    num_engines: int = Field(default=17, alias="NUM_ENGINES")
    scrape_limit: int = Field(default=20, alias="SCRAPE_LIMIT")

    # ── Inter-service URLs ─────────────────────────────────────────────────
    query_service_url: str = Field(
        default="http://query-generator:8001", alias="QUERY_SERVICE_URL"
    )
    analysis_service_url: str = Field(
        default="http://ai-analysis:8000", alias="ANALYSIS_SERVICE_URL"
    )

    # ── Batching ───────────────────────────────────────────────────────────
    batch_size: int = Field(default=5, alias="BATCH_SIZE")

    # ── Polling ────────────────────────────────────────────────────────────
    poll_interval_seconds: int = Field(default=300, alias="POLL_INTERVAL_SECONDS")

    model_config = {
        "env_file": ".env",
        "populate_by_name": True,
        "extra": "ignore",
    }


# Module-level singleton
settings = Settings()
