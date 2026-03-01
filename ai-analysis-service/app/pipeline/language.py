"""Stage 2 – Language detection.

Uses the ``langdetect`` library to identify the primary language of a text
sample.  Falls back to ``"unknown"`` when detection fails (e.g. on very
short or binary content).
"""

from __future__ import annotations

from langdetect import detect, LangDetectException

# Maximum characters to feed into the detector – longer texts are truncated
# for speed; 5 000 chars is plenty for reliable detection.
_SAMPLE_LIMIT = 5_000


def detect_language(text: str) -> str:
    """Return an ISO-639-1 language code (e.g. ``"en"``, ``"ru"``).

    Returns ``"unknown"`` when detection is not possible.
    """
    sample = text[:_SAMPLE_LIMIT].strip()
    if not sample:
        return "unknown"

    try:
        return detect(sample)
    except LangDetectException:
        return "unknown"
