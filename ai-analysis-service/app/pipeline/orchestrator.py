"""Pipeline orchestrator – runs all stages in sequence for each page.

Stage 0 (preprocessing) strips raw HTML into clean plain text before any
analysis logic runs.

When ``search_strings`` are not supplied in the request, they are fetched
from the query-generator service via ``GET /search-strings``.
"""

from __future__ import annotations

import logging

import httpx

from app.config import settings
from app.models import AnalyzeRequest, AnalyzeResponse, PageResult
from app.logger import log_result

from app.pipeline.preprocessor import preprocess_html
from app.pipeline.prefilter import prefilter
from app.pipeline.language import detect_language
from app.pipeline.classifier import classify
from app.pipeline.similarity import compute_similarity
from app.pipeline.relevance import decide_relevance

_log = logging.getLogger("analysis.orchestrator")


# ── Search-string resolution ──────────────────────────────────────────────

def _fetch_search_strings() -> list[str]:
    """Fetch detailed search strings from the query-generator service."""
    url = f"{settings.query_service_url}/search-strings"
    try:
        resp = httpx.get(url, timeout=10.0)
        resp.raise_for_status()
        data = resp.json()
        strings = data.get("search_strings", [])
        if strings:
            return strings
        _log.warning("Query service returned empty search_strings")
    except Exception as exc:
        _log.warning("Failed to fetch search strings from %s: %s", url, exc)
    return []


def _resolve_search_strings(request: AnalyzeRequest) -> list[str]:
    """Return search strings from the request, or fetch from query service."""
    if request.search_strings:
        return request.search_strings
    return _fetch_search_strings()


# ── Page-level pipeline ───────────────────────────────────────────────────

def _make_irrelevant_result(
    source_url: str,
    language: str,
    matched_strings: list[str] | None = None,
) -> PageResult:
    """Construct a minimal result for a page that skipped ML inference."""
    return PageResult(
        source_url=source_url,
        is_relevant=False,
        confidence=0.0,
        matched_strings=matched_strings or [],
        classification_label="irrelevant",
        similarity_score=0.0,
        summary=None,
        language_detected=language,
    )


def analyze_page(
    text: str,
    source_url: str,
    search_strings: list[str],
) -> PageResult:
    """Run the full pipeline on a single page.

    Stage 0: Preprocess raw HTML into clean text.
    Stage 1-5: Pre-filter → language → classification → similarity → relevance.
    """

    # Stage 0 – HTML preprocessing
    clean_text = preprocess_html(text)

    # Stage 1 – Pre-filter (on clean text)
    matched = prefilter(clean_text, search_strings)

    # Stage 2 – Language detection (always, even for irrelevant pages)
    language = detect_language(clean_text)

    if not matched:
        result = _make_irrelevant_result(source_url, language)
        log_result(
            source_url=source_url,
            matched_strings=[],
            classification_label="irrelevant",
            confidence=0.0,
            similarity_score=0.0,
            is_relevant=False,
            language_detected=language,
        )
        return result

    # Stage 3 – Classification
    label, cls_confidence = classify(clean_text)

    # Stage 4 – Semantic similarity
    sim_score = compute_similarity(clean_text, search_strings)

    # Stage 5 – Relevance decision
    is_relevant, overall_confidence = decide_relevance(label, cls_confidence, sim_score)

    # Build summary only for relevant pages
    summary: str | None = None
    if is_relevant:
        summary = (
            f"Content appears to contain data referencing "
            f"{', '.join(matched)}. Classified as {label}."
        )

    result = PageResult(
        source_url=source_url,
        is_relevant=is_relevant,
        confidence=overall_confidence,
        matched_strings=matched,
        classification_label=label,
        similarity_score=round(sim_score, 4),
        summary=summary,
        language_detected=language,
    )

    log_result(
        source_url=source_url,
        matched_strings=matched,
        classification_label=label,
        confidence=overall_confidence,
        similarity_score=sim_score,
        is_relevant=is_relevant,
        language_detected=language,
    )

    return result


# ── Batch orchestration ───────────────────────────────────────────────────

def analyze_batch(request: AnalyzeRequest) -> AnalyzeResponse:
    """Process every page in the batch and aggregate results."""
    search_strings = _resolve_search_strings(request)

    results: list[PageResult] = []
    for page in request.pages:
        result = analyze_page(page.text, page.source_url, search_strings)
        results.append(result)

    return AnalyzeResponse(
        results=results,
        total=len(results),
        relevant_count=sum(1 for r in results if r.is_relevant),
    )
