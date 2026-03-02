"""Centralised, env-driven configuration using pydantic-settings."""

from __future__ import annotations

from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """All tunables are loaded from environment variables (or .env file)."""

    # ── Model mode ──────────────────────────────────────────────────────────
    use_local_models: bool = Field(default=True, alias="USE_LOCAL_MODELS")

    # ── Local model paths (mounted at /models inside Docker) ────────────────
    local_classifier_path: str = Field(
        default="./models/bge-m3-zeroshot-v2.0", alias="LOCAL_CLASSIFIER_PATH"
    )
    local_embedding_path: str = Field(
        default="./models/bge-m3", alias="LOCAL_EMBEDDING_PATH"
    )

    # ── API fallback ────────────────────────────────────────────────────────
    openrouter_api_key: str = Field(default="", alias="OPENROUTER_API_KEY")
    openrouter_model: str = Field(
        default="cognitivecomputations/dolphin-mistral-24b-venice-edition:free",
        alias="OPENROUTER_MODEL",
    )
    hf_api_key: str = Field(default="", alias="HF_API_KEY")
    hf_classifier_url: str = Field(
        default="https://router.huggingface.co/hf-inference/models/MoritzLaurer/bge-m3-zeroshot-v2.0",
        alias="HF_CLASSIFIER_URL",
    )
    hf_embedding_url: str = Field(
        default="https://router.huggingface.co/hf-inference/models/BAAI/bge-m3",
        alias="HF_EMBEDDING_URL",
    )

    # ── Thresholds ──────────────────────────────────────────────────────────
    similarity_threshold: float = Field(default=0.75, alias="SIMILARITY_THRESHOLD")
    classification_confidence_threshold: float = Field(
        default=0.65, alias="CLASSIFICATION_CONFIDENCE_THRESHOLD"
    )

    # ── Classification labels (comma-separated) ────────────────────────────
    classification_labels: str = Field(
        default="credential_leak,database_dump,internal_document,general_mention,irrelevant",
        alias="CLASSIFICATION_LABELS",
    )

    # ── Chunking ────────────────────────────────────────────────────────────
    chunk_size: int = Field(default=400, alias="CHUNK_SIZE")
    chunk_overlap: int = Field(default=50, alias="CHUNK_OVERLAP")

    # ── Query service (for fetching search strings) ─────────────────────────
    query_service_url: str = Field(
        default="http://query-generator:8001", alias="QUERY_SERVICE_URL"
    )

    # ── Logging ─────────────────────────────────────────────────────────────
    log_path: str = Field(default="/logs/analysis.log", alias="LOG_PATH")

    model_config = {
        "env_file": ".env",
        "populate_by_name": True,
        "extra": "ignore",
    }

    @property
    def label_list(self) -> list[str]:
        """Return classification labels as a Python list."""
        return [l.strip() for l in self.classification_labels.split(",") if l.strip()]


# Module-level singleton – import this everywhere
settings = Settings()
