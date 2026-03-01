"""Structured JSON logger for analysis results.

Writes one JSON object per line to the configured log file.
Raw text content is *never* logged (privacy requirement).
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import settings

_logger: logging.Logger | None = None


def _get_logger() -> logging.Logger:
    """Lazily initialise the file-backed JSON logger."""
    global _logger
    if _logger is not None:
        return _logger

    log_path = Path(settings.log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    _logger = logging.getLogger("analysis")
    _logger.setLevel(logging.INFO)
    _logger.propagate = False

    if not _logger.handlers:
        handler = logging.FileHandler(str(log_path), encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(message)s"))
        _logger.addHandler(handler)

    return _logger


def log_result(
    source_url: str,
    matched_strings: list[str],
    classification_label: str,
    confidence: float,
    similarity_score: float,
    is_relevant: bool,
    language_detected: str,
) -> None:
    """Append a structured JSON entry for one analysed page."""
    entry: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source_url": source_url,
        "matched_strings": matched_strings,
        "classification_label": classification_label,
        "confidence": round(confidence, 4),
        "similarity_score": round(similarity_score, 4),
        "is_relevant": is_relevant,
        "language_detected": language_detected,
    }
    _get_logger().info(json.dumps(entry, ensure_ascii=False))
