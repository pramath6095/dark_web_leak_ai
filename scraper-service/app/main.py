"""FastAPI application for the scraper service.

Endpoints
---------
GET  /health   – service status and Tor connectivity
POST /trigger  – manually trigger one scrape cycle

Background
----------
A polling loop runs on startup that periodically fetches queries from
the query-generator, searches the dark web, scrapes discovered pages,
and dispatches results to the ai-analysis service.
"""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI, BackgroundTasks
from pydantic import BaseModel

from app.config import settings
from app.search import search_dark_web
from app.scrape import scrape_all
from app.dispatcher import dispatch_to_analysis

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
_log = logging.getLogger("scraper.main")

# ── State ──────────────────────────────────────────────────────────────────

_start_time: float = 0.0
_last_poll_time: float | None = None
_cycle_running: bool = False
_poll_task: asyncio.Task | None = None
_scraped_urls: set[str] = set()  # global dedup across all cycles


# ── Query fetching ─────────────────────────────────────────────────────────

async def _fetch_queries() -> tuple[list[str], bool]:
    """GET /queries from the query-generator service.

    Returns (queries, exhausted). When exhausted=True and queries is empty,
    the scraper should stop polling.
    """
    url = f"{settings.query_service_url}/queries"
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
            queries = data.get("queries", [])
            exhausted = data.get("exhausted", False)
            if queries:
                _log.info("Fetched %d queries from query service", len(queries))
            elif exhausted:
                _log.info("Query service exhausted — no more queries")
            else:
                _log.warning("Query service returned empty queries list")
            return queries, exhausted
    except Exception as exc:
        _log.warning("Could not reach query service at %s: %s", url, exc)
    return [], False


# ── Single scrape cycle ──────────────────────────────────────────────────

async def run_scrape_cycle() -> tuple[list[dict[str, Any]], bool]:
    """Run one full cycle: fetch queries → search → scrape → dispatch.

    Returns (responses, should_stop).
    """
    global _last_poll_time, _cycle_running

    if _cycle_running:
        _log.warning("Scrape cycle already running, skipping")
        return []

    _cycle_running = True
    all_responses: list[dict[str, Any]] = []

    try:
        queries, exhausted = await _fetch_queries()
        if not queries:
            if exhausted:
                _log.info("All queries exhausted — stopping")
                return [], True  # signal to stop
            _log.info("No queries to process, skipping cycle")
            return [], False

        for query in queries:
            _log.info("── Processing query: '%s' ──", query)

            # Step 1: Search dark web
            urls = await search_dark_web(query)
            if not urls:
                _log.info("No URLs found for query: '%s'", query)
                continue

            # Dedup: skip URLs we've already scraped
            new_urls = [u for u in urls if u not in _scraped_urls]
            _scraped_urls.update(new_urls)
            if not new_urls:
                _log.info("All %d URLs already scraped, skipping query", len(urls))
                continue
            _log.info("Found %d URLs, %d new (after dedup)", len(urls), len(new_urls))

            # Step 2: Scrape discovered pages (raw HTML)
            scrape_results = await scrape_all(new_urls)

            # Step 3: Dispatch to analysis in batches of 5
            responses = await dispatch_to_analysis(scrape_results)
            all_responses.extend(responses)

        _last_poll_time = time.time()
        _log.info("Scrape cycle complete. %d batch responses collected.",
                   len(all_responses))

    except Exception as exc:
        _log.error("Scrape cycle failed: %s", exc)
    finally:
        _cycle_running = False

    return all_responses, False  # not exhausted yet


# ── Polling loop ─────────────────────────────────────────────────────────

async def _polling_loop() -> None:
    """Continuously run scrape cycles with a sleep interval."""
    _log.info(
        "Polling loop started (interval: %ds)", settings.poll_interval_seconds
    )
    while True:
        try:
            _, should_stop = await run_scrape_cycle()
            if should_stop:
                _log.info("Query service exhausted, polling loop stopped.")
                return
        except Exception as exc:
            _log.error("Polling iteration error: %s", exc)

        _log.info(
            "Next cycle in %d seconds...", settings.poll_interval_seconds
        )
        await asyncio.sleep(settings.poll_interval_seconds)


# ── Lifespan ─────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _start_time, _poll_task
    _start_time = time.time()

    # Start the background polling loop
    _poll_task = asyncio.create_task(_polling_loop())
    _log.info("Scraper service started")

    yield

    # Cancel polling on shutdown
    if _poll_task:
        _poll_task.cancel()
        try:
            await _poll_task
        except asyncio.CancelledError:
            pass
    _log.info("Scraper service stopped")


# ── Application ──────────────────────────────────────────────────────────

app = FastAPI(
    title="Dark Web Scraper Service",
    version="1.0.0",
    lifespan=lifespan,
)


# ── Response models ──────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str
    uptime_seconds: float
    last_poll_time: float | None
    cycle_running: bool
    query_service_url: str
    analysis_service_url: str
    tor_proxy: str
    poll_interval_seconds: int


class TriggerResponse(BaseModel):
    message: str
    batch_responses: list[dict[str, Any]]


# ── Endpoints ────────────────────────────────────────────────────────────

@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Return service status and configuration."""
    return HealthResponse(
        status="ok",
        uptime_seconds=round(time.time() - _start_time, 2),
        last_poll_time=_last_poll_time,
        cycle_running=_cycle_running,
        query_service_url=settings.query_service_url,
        analysis_service_url=settings.analysis_service_url,
        tor_proxy=f"{settings.tor_proxy_host}:{settings.tor_proxy_port}",
        poll_interval_seconds=settings.poll_interval_seconds,
    )


@app.post("/trigger", response_model=TriggerResponse)
async def trigger() -> TriggerResponse:
    """Manually trigger one scrape cycle."""
    responses, stopped = await run_scrape_cycle()
    msg = "Scrape cycle completed"
    if stopped:
        msg += " (queries exhausted)"
    return TriggerResponse(
        message=msg,
        batch_responses=responses,
    )
