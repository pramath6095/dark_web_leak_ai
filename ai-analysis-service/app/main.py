"""FastAPI application – AI analysis microservice.

Endpoints
---------
POST /analyze   – batch-analyse scraped pages
GET  /health    – model status and service info
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings
from app.models import AnalyzeRequest, AnalyzeResponse, HealthResponse
from app.pipeline import classifier, similarity
from app.pipeline.orchestrator import analyze_batch

# ── Lifespan (model loading at startup) ─────────────────────────────────────

_start_time: float = 0.0


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load heavy ML models once at startup, release on shutdown."""
    global _start_time
    _start_time = time.time()

    classifier.load_model()
    similarity.load_model()

    yield  # app is running

    # Cleanup (nothing to do – models are GC'd)


# ── Application ─────────────────────────────────────────────────────────────

app = FastAPI(
    title="AI Dark-Web Leak Analyzer",
    version="1.0.0",
    lifespan=lifespan,
)


@app.post("/analyze", response_model=AnalyzeResponse)
def analyze(request: AnalyzeRequest) -> AnalyzeResponse:
    """Analyse a batch of scraped pages against the supplied search strings."""
    response = analyze_batch(request)
    _write_results(response)
    return response


def _write_results(response: AnalyzeResponse) -> None:
    """Append analysis results to the output file."""
    import os
    from datetime import datetime, timezone
    from pathlib import Path

    output_path = Path("/output/results.txt")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "a", encoding="utf-8") as f:
        for r in response.results:
            if r.is_relevant:
                f.write(f"\n{'='*70}\n")
                f.write(f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}]\n")
                f.write(f"URL:            {r.source_url}\n")
                f.write(f"Classification: {r.classification_label}\n")
                f.write(f"Confidence:     {r.confidence:.2f}\n")
                f.write(f"Similarity:     {r.similarity_score:.2f}\n")
                f.write(f"Matched:        {', '.join(r.matched_strings)}\n")
                f.write(f"Language:       {r.language_detected}\n")
                if r.summary:
                    f.write(f"Summary:        {r.summary}\n")
                f.write(f"{'='*70}\n")


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Return service health and model-load status."""
    mode = "local" if settings.use_local_models else "api"
    return HealthResponse(
        status="ok",
        mode=mode,
        classifier_loaded=classifier.is_loaded(),
        embedder_loaded=similarity.is_loaded(),
        uptime_seconds=round(time.time() - _start_time, 2),
    )
