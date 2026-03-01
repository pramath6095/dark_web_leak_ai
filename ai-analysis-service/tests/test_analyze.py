"""Integration test for the /analyze endpoint.

Mocks all ML inference (classifier, embedder, language detection) so the
test runs without GPU, model downloads, or heavy dependencies.

Validates the full pipeline end-to-end with a two-page batch:
  1. A credential dump *embedded in raw HTML* that matches the search strings
     → is_relevant: True  (tests both HTML preprocessing and ML path)
  2. An unrelated cooking recipe in HTML → filtered out by pre-filter
     → is_relevant: False
"""

from __future__ import annotations

import os
from unittest.mock import patch, MagicMock

import pytest

# Force API mode so the test never tries to load real models
os.environ["USE_LOCAL_MODELS"] = "false"
os.environ["LOG_PATH"] = "/tmp/test_analysis.log"

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


# ── Fixtures / helpers ──────────────────────────────────────────────────────

CREDENTIAL_PAGE_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <title>Leaked Data</title>
    <style>body { background: #000; color: #0f0; }</style>
    <script>console.log("tracker");</script>
</head>
<body>
    <nav><a href="/">Home</a> <a href="/about">About</a></nav>
    <header><h1>Free Data Dump</h1></header>

    <div class="content">
        <p>Here are leaked credentials for company.com employees:</p>
        <pre>
            alice@company.com : P@ssw0rd123
            bob@company.com   : hunter2
            charlie@company.com : qwerty!
        </pre>
    </div>

    <form action="/search">
        <input type="text" name="q" placeholder="Search more leaks" />
        <button type="submit">Go</button>
    </form>

    <footer>
        <p>Hosted on Tor | Donate BTC: 1A2b3C4d5E</p>
        <p>Contact: admin@darksite.onion</p>
    </footer>
</body>
</html>
"""

COOKING_PAGE_HTML = """
<!DOCTYPE html>
<html lang="en">
<head><title>Recipes</title></head>
<body>
    <nav><a href="/">Home</a></nav>
    <h1>Grandma's Chocolate Chip Cookies</h1>
    <p>Mix 2 cups flour, 1 cup sugar, 1/2 cup butter...</p>
    <p>Bake at 350°F for 12 minutes.</p>
    <footer><p>Copyright 2024 CookingSite</p></footer>
</body>
</html>
"""

SEARCH_STRINGS = ["company.com", "CompanyName", "@company.com"]


def _mock_classify(text: str) -> tuple[str, float]:
    """Fake classifier that always returns credential_leak with 0.92."""
    return ("credential_leak", 0.92)


def _mock_similarity(text: str, search_strings: list[str]) -> float:
    """Fake similarity that always returns 0.87."""
    return 0.87


def _mock_detect_language(text: str) -> str:
    """Fake language detector returning English."""
    return "en"


# ── Tests ───────────────────────────────────────────────────────────────────

@patch("app.pipeline.orchestrator.classify", side_effect=_mock_classify)
@patch("app.pipeline.orchestrator.compute_similarity", side_effect=_mock_similarity)
@patch("app.pipeline.orchestrator.detect_language", side_effect=_mock_detect_language)
def test_analyze_batch_two_pages(
    mock_lang: MagicMock,
    mock_sim: MagicMock,
    mock_cls: MagicMock,
):
    """POST /analyze with one relevant HTML page and one irrelevant HTML page."""
    payload = {
        "pages": [
            {
                "text": CREDENTIAL_PAGE_HTML,
                "source_url": "http://example.onion/page1",
            },
            {
                "text": COOKING_PAGE_HTML,
                "source_url": "http://example.onion/page2",
            },
        ],
        "search_strings": SEARCH_STRINGS,
    }

    response = client.post("/analyze", json=payload)
    assert response.status_code == 200

    data = response.json()

    # ── Top-level aggregates ────────────────────────────────────────────
    assert data["total"] == 2
    assert data["relevant_count"] == 1

    # ── Page 1: credential dump – should be relevant ────────────────────
    r1 = data["results"][0]
    assert r1["source_url"] == "http://example.onion/page1"
    assert r1["is_relevant"] is True
    assert r1["classification_label"] == "credential_leak"
    assert "company.com" in r1["matched_strings"]
    assert "@company.com" in r1["matched_strings"]
    assert r1["confidence"] > 0
    assert r1["similarity_score"] > 0
    assert r1["summary"] is not None
    assert r1["language_detected"] == "en"

    # ── Page 2: cooking recipe – should be filtered out ─────────────────
    r2 = data["results"][1]
    assert r2["source_url"] == "http://example.onion/page2"
    assert r2["is_relevant"] is False
    assert r2["classification_label"] == "irrelevant"
    assert r2["matched_strings"] == []
    assert r2["confidence"] == 0.0
    assert r2["similarity_score"] == 0.0
    assert r2["summary"] is None

    # ── ML should NOT have been called for the filtered page ────────────
    # classify and compute_similarity are only called for page 1
    mock_cls.assert_called_once()
    mock_sim.assert_called_once()

    # language detection is called for both pages
    assert mock_lang.call_count == 2

    # ── Verify the classifier received clean text, not raw HTML ─────────
    classified_text = mock_cls.call_args[0][0]
    assert "<script>" not in classified_text
    assert "<form" not in classified_text
    assert "<nav>" not in classified_text
    assert "company.com" in classified_text  # content preserved


def test_health_endpoint():
    """GET /health returns mode and model status."""
    response = client.get("/health")
    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "ok"
    assert data["mode"] == "api"  # we forced USE_LOCAL_MODELS=false
    assert isinstance(data["classifier_loaded"], bool)
    assert isinstance(data["embedder_loaded"], bool)
    assert data["uptime_seconds"] >= 0
