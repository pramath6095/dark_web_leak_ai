"""Stage 3 – Zero-shot text classification.

Classifies scraped content into one of the configurable labels using either:
* **Local mode** – a HuggingFace ``zero-shot-classification`` pipeline loaded
  from ``LOCAL_CLASSIFIER_PATH``.
* **API mode** – the HuggingFace Inference API at ``HF_CLASSIFIER_URL``.

Long texts are split into 512-token chunks and up to ``MAX_CLASSIFY_CHUNKS``
chunks are classified independently.  The final label is the highest-
confidence *non-irrelevant* result; if every chunk is irrelevant, the
highest-confidence irrelevant result is returned instead.

The switch is entirely config-driven (``USE_LOCAL_MODELS`` env var).
"""

from __future__ import annotations

from typing import Any

import httpx

from app.config import settings

# ── Constants ──────────────────────────────────────────────────────────────
_CHUNK_TOKEN_LIMIT = 512
MAX_CLASSIFY_CHUNKS = 3  # classify at most this many chunks

# ── Module-level state (populated at startup) ──────────────────────────────
_local_pipeline: Any | None = None


# ── Startup / teardown ─────────────────────────────────────────────────────

def load_model() -> None:
    """Load the local classifier model into memory.  No-op in API mode."""
    global _local_pipeline
    if not settings.use_local_models:
        return
    from transformers import pipeline as hf_pipeline  # heavy import – deferred

    _local_pipeline = hf_pipeline(
        "zero-shot-classification",
        model=settings.local_classifier_path,
        device=-1,  # CPU
    )


def is_loaded() -> bool:
    """Return ``True`` if a local model is loaded or API mode is active."""
    if settings.use_local_models:
        return _local_pipeline is not None
    return True  # API is always "loaded"


# ── Chunking helper ────────────────────────────────────────────────────────

def _chunk_for_classification(text: str) -> list[str]:
    """Split *text* into ≤512-token chunks (whitespace-delimited)."""
    tokens = text.split()
    if len(tokens) <= _CHUNK_TOKEN_LIMIT:
        return [text]

    chunks: list[str] = []
    for i in range(0, len(tokens), _CHUNK_TOKEN_LIMIT):
        chunk = " ".join(tokens[i : i + _CHUNK_TOKEN_LIMIT])
        chunks.append(chunk)
    return chunks


# ── Inference ──────────────────────────────────────────────────────────────

def classify(text: str) -> tuple[str, float]:
    """Classify *text* and return ``(label, confidence)``.

    Long texts are chunked into 512-token windows.  Up to
    ``MAX_CLASSIFY_CHUNKS`` chunks are classified and the best
    non-irrelevant result is selected (falling back to the best
    irrelevant result if nothing else matches).
    """
    chunks = _chunk_for_classification(text)[:MAX_CLASSIFY_CHUNKS]
    labels = settings.label_list

    best_relevant: tuple[str, float] | None = None
    best_irrelevant: tuple[str, float] | None = None

    for chunk in chunks:
        if settings.use_local_models:
            label, conf = _classify_local(chunk, labels)
        else:
            label, conf = _classify_api(chunk, labels)

        if label != "irrelevant":
            if best_relevant is None or conf > best_relevant[1]:
                best_relevant = (label, conf)
        else:
            if best_irrelevant is None or conf > best_irrelevant[1]:
                best_irrelevant = (label, conf)

    # Prefer non-irrelevant results
    if best_relevant is not None:
        return best_relevant
    if best_irrelevant is not None:
        return best_irrelevant
    return ("irrelevant", 0.0)


def _classify_local(text: str, labels: list[str]) -> tuple[str, float]:
    if _local_pipeline is None:
        raise RuntimeError("Local classifier not loaded – call load_model() first")
    result = _local_pipeline(text, candidate_labels=labels)
    return result["labels"][0], float(result["scores"][0])


def _classify_api(text: str, labels: list[str]) -> tuple[str, float]:
    payload = {
        "inputs": text,
        "parameters": {"candidate_labels": labels},
    }
    headers = {}
    if settings.hf_api_key:
        headers["Authorization"] = f"Bearer {settings.hf_api_key}"

    resp = httpx.post(
        settings.hf_classifier_url,
        json=payload,
        headers=headers,
        timeout=60.0,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["labels"][0], float(data["scores"][0])
