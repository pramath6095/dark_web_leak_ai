"""Pydantic v2 request/response models for the AI analysis service."""

from __future__ import annotations

from pydantic import BaseModel, Field


# ── Request Models ──────────────────────────────────────────────────────────

class PageInput(BaseModel):
    """A single scraped page submitted for analysis."""

    text: str = Field(..., description="Raw scraped content")
    source_url: str = Field(..., description="Onion URL the content was scraped from")


class AnalyzeRequest(BaseModel):
    """Batch analysis request containing one or more pages.

    ``search_strings`` is optional.  When omitted the analysis service
    fetches detailed search strings from the query-generator automatically.
    """

    pages: list[PageInput] = Field(..., min_length=1)
    search_strings: list[str] | None = Field(
        default=None,
        description="Company names, domains, email suffixes, etc. "
        "Fetched from query-generator when not provided.",
    )


# ── Response Models ─────────────────────────────────────────────────────────

class PageResult(BaseModel):
    """Analysis result for a single page."""

    source_url: str
    is_relevant: bool
    confidence: float = Field(..., ge=0.0, le=1.0)
    matched_strings: list[str]
    classification_label: str
    similarity_score: float = Field(..., ge=0.0, le=1.0)
    summary: str | None = None
    language_detected: str


class AnalyzeResponse(BaseModel):
    """Full batch analysis response."""

    results: list[PageResult]
    total: int
    relevant_count: int


# ── Health ──────────────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    """Response from /health endpoint."""

    status: str
    mode: str  # "local" or "api"
    classifier_loaded: bool
    embedder_loaded: bool
    uptime_seconds: float
