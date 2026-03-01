"""FastAPI application for the query-generator service.

Endpoints
---------
POST /configure      – Receives company info, triggers initial generation
GET  /queries        – Returns next batch of unsent queries (empty = stop)
GET  /search-strings – Returns detailed matching strings for analysis
GET  /health         – Service status
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.config import settings
from app.state import state
from app.generator import generate_initial_queries, generate_more_queries

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
_log = logging.getLogger("querygen.main")

_start_time: float = 0.0


# ── Startup ──────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _start_time
    _start_time = time.time()

    # If a company info file is configured, load it at startup
    if settings.company_info_file:
        _load_company_file(settings.company_info_file)

    _log.info("Query generator service started")
    yield
    _log.info("Query generator service stopped")


def _load_company_file(filepath: str) -> None:
    """Load company info from a text file.

    Expected format:
        Line 1: Company name
        Lines 2+: Company description
    """
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            lines = f.read().strip().splitlines()
        if not lines:
            _log.warning("Company info file is empty: %s", filepath)
            return

        state.company_name = lines[0].strip()
        state.company_description = "\n".join(lines[1:]).strip()
        state.configured = True

        _log.info("Loaded company info from file: '%s'", state.company_name)
        generate_initial_queries()

    except FileNotFoundError:
        _log.warning("Company info file not found: %s", filepath)
    except Exception as exc:
        _log.error("Error loading company file: %s", exc)


# ── Application ──────────────────────────────────────────────────────────

app = FastAPI(
    title="Query Generator Service",
    version="1.0.0",
    lifespan=lifespan,
)


# ── Request / Response models ────────────────────────────────────────────

class ConfigureRequest(BaseModel):
    company_name: str = Field(..., min_length=1)
    description: str = Field(default="", description="Detailed company description")


class ConfigureResponse(BaseModel):
    message: str
    queries_generated: int
    search_strings_count: int


class QueriesResponse(BaseModel):
    queries: list[str]
    remaining: int
    exhausted: bool


class SearchStringsResponse(BaseModel):
    search_strings: list[str]


class HealthResponse(BaseModel):
    status: str
    configured: bool
    company_name: str
    total_queries: int
    served_queries: int
    exhausted: bool
    generation_round: int
    uptime_seconds: float


# ── Endpoints ────────────────────────────────────────────────────────────

@app.post("/configure", response_model=ConfigureResponse)
def configure(request: ConfigureRequest) -> ConfigureResponse:
    """Receive company info and generate initial queries + search strings."""
    state.company_name = request.company_name
    state.company_description = request.description
    state.configured = True

    # Reset state for fresh generation
    state.all_queries.clear()
    state.served_queries.clear()
    state.search_strings.clear()
    state.generation_round = 0
    state.exhausted = False

    _log.info("Configured for company: '%s'", state.company_name)
    queries = generate_initial_queries()

    return ConfigureResponse(
        message=f"Configured for '{state.company_name}'",
        queries_generated=len(queries),
        search_strings_count=len(state.search_strings),
    )


@app.get("/queries", response_model=QueriesResponse)
def get_queries() -> QueriesResponse:
    """Return the next batch of unsent queries.

    Returns an empty list when all queries have been served and the LLM
    can no longer produce novel ones — this is the **stop signal** for
    the scraper.
    """
    if not state.configured:
        raise HTTPException(
            status_code=409,
            detail="Service not configured. POST /configure first.",
        )

    unserved = state.unserved_queries

    # If we've run out, try to generate more
    if not unserved and not state.exhausted:
        newly_added = generate_more_queries()
        if newly_added > 0:
            unserved = state.unserved_queries

    # Take the next batch
    batch = unserved[: settings.queries_per_batch]
    state.mark_served(batch)

    remaining = len(state.unserved_queries)

    _log.info(
        "Serving %d queries (%d remaining, exhausted=%s)",
        len(batch), remaining, state.exhausted,
    )

    return QueriesResponse(
        queries=batch,
        remaining=remaining,
        exhausted=state.exhausted and remaining == 0,
    )


@app.get("/search-strings", response_model=SearchStringsResponse)
def get_search_strings() -> SearchStringsResponse:
    """Return detailed search strings for the analysis service."""
    if not state.configured:
        raise HTTPException(
            status_code=409,
            detail="Service not configured. POST /configure first.",
        )

    return SearchStringsResponse(search_strings=state.search_strings)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Return service status and generation state."""
    return HealthResponse(
        status="ok",
        configured=state.configured,
        company_name=state.company_name,
        total_queries=len(state.all_queries),
        served_queries=len(state.served_queries),
        exhausted=state.exhausted,
        generation_round=state.generation_round,
        uptime_seconds=round(time.time() - _start_time, 2),
    )
