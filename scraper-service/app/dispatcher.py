"""Dispatcher – batches scraped pages and POSTs them to the ai-analysis service.

Filters out scrape errors, groups successful pages into batches of
``settings.batch_size`` (default 5), and sends each batch to
``POST /analyze`` on the analysis service.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import settings

_log = logging.getLogger("scraper.dispatcher")


async def dispatch_to_analysis(scrape_results: dict[str, str]) -> list[dict[str, Any]]:
    """Send scraped pages to the ai-analysis service in batches.

    Parameters
    ----------
    scrape_results : dict[str, str]
        Mapping of ``{url: raw_html_or_error_string}``.

    Returns
    -------
    list[dict]
        List of analysis response dicts (one per batch).
    """
    # Filter out errors — keep only successful scrapes
    pages = [
        {"text": html, "source_url": url}
        for url, html in scrape_results.items()
        if not html.startswith("[ERROR")
    ]

    if not pages:
        _log.info("No successful scrapes to dispatch")
        return []

    _log.info("Dispatching %d pages in batches of %d", len(pages), settings.batch_size)

    # Split into batches
    batches = [
        pages[i : i + settings.batch_size]
        for i in range(0, len(pages), settings.batch_size)
    ]

    responses: list[dict[str, Any]] = []
    analyze_url = f"{settings.analysis_service_url}/analyze"

    async with httpx.AsyncClient(timeout=120.0) as client:
        for batch_num, batch in enumerate(batches, 1):
            payload = {"pages": batch}
            # search_strings omitted — analysis service fetches them
            # from the query-generator itself

            try:
                _log.info(
                    "Sending batch %d/%d (%d pages) to %s",
                    batch_num, len(batches), len(batch), analyze_url,
                )
                resp = await client.post(analyze_url, json=payload)
                resp.raise_for_status()
                data = resp.json()
                responses.append(data)

                relevant = data.get("relevant_count", 0)
                total = data.get("total", 0)
                _log.info(
                    "Batch %d/%d: %d/%d relevant",
                    batch_num, len(batches), relevant, total,
                )
            except Exception as exc:
                _log.error(
                    "Batch %d/%d failed: %s", batch_num, len(batches), exc
                )
                responses.append({"error": str(exc), "batch": batch_num})

    return responses
