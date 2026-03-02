"""Stage 4 – Semantic similarity via BGE-M3 embeddings.

Embeds both the scraped text (chunked if long) and a dynamically constructed
query string, then returns the **maximum** cosine similarity across chunks.

Supports local ``sentence-transformers`` model or HuggingFace Inference API.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import httpx

from app.config import settings

# ── Module-level state ─────────────────────────────────────────────────────
_local_model: Any | None = None


# ── Startup / teardown ─────────────────────────────────────────────────────

def load_model() -> None:
    """Load the local embedding model into memory.  No-op in API mode."""
    global _local_model
    if not settings.use_local_models:
        return
    from sentence_transformers import SentenceTransformer  # heavy import

    _local_model = SentenceTransformer(settings.local_embedding_path)


def is_loaded() -> bool:
    if settings.use_local_models:
        return _local_model is not None
    return True


# ── Chunking ───────────────────────────────────────────────────────────────

def _chunk_text(
    text: str,
    chunk_size: int | None = None,
    overlap: int | None = None,
) -> list[str]:
    """Split *text* into overlapping token windows (whitespace-split)."""
    chunk_size = chunk_size or settings.chunk_size
    overlap = overlap or settings.chunk_overlap

    tokens = text.split()
    if len(tokens) <= chunk_size:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(tokens):
        end = start + chunk_size
        chunks.append(" ".join(tokens[start:end]))
        start += chunk_size - overlap
    return chunks


# ── Query builder ──────────────────────────────────────────────────────────

def _build_query(search_strings: list[str]) -> str:
    joined = ", ".join(search_strings)
    return f"Data related to {joined}"


# ── Cosine similarity ─────────────────────────────────────────────────────

def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    dot = float(np.dot(a, b))
    norm = float(np.linalg.norm(a) * np.linalg.norm(b))
    if norm == 0:
        return 0.0
    return dot / norm


# ── Inference ──────────────────────────────────────────────────────────────

def compute_similarity(text: str, search_strings: list[str]) -> float:
    """Return max cosine similarity between query and text chunks."""
    query = _build_query(search_strings)
    chunks = _chunk_text(text)

    if settings.use_local_models:
        return _similarity_local(query, chunks)
    return _similarity_api(query, chunks)


def _similarity_local(query: str, chunks: list[str]) -> float:
    if _local_model is None:
        raise RuntimeError("Local embedder not loaded – call load_model() first")

    all_texts = [query] + chunks
    embeddings = _local_model.encode(all_texts, normalize_embeddings=True)
    query_emb = embeddings[0]

    max_sim = 0.0
    for chunk_emb in embeddings[1:]:
        sim = _cosine_similarity(query_emb, chunk_emb)
        max_sim = max(max_sim, sim)
    return max_sim


def _similarity_api(query: str, chunks: list[str]) -> float:
    """Use HuggingFace sentence-similarity API (source_sentence + sentences)."""
    headers = {}
    if settings.hf_api_key:
        headers["Authorization"] = f"Bearer {settings.hf_api_key}"

    payload = {
        "inputs": {
            "source_sentence": query,
            "sentences": chunks,
        }
    }

    resp = httpx.post(
        settings.hf_embedding_url,
        json=payload,
        headers=headers,
        timeout=120.0,
    )
    resp.raise_for_status()

    # API returns a list of similarity scores, one per sentence
    scores = resp.json()
    return float(max(scores)) if scores else 0.0
