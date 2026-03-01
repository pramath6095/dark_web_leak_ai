"""Stage 5 – Final relevance decision.

Combines the classification output and the semantic similarity score to
produce a single ``is_relevant`` boolean and an overall confidence score.

Thresholds are read from ``app.config.settings``.
"""

from __future__ import annotations

from app.config import settings


def decide_relevance(
    classification_label: str,
    classification_confidence: float,
    similarity_score: float,
) -> tuple[bool, float]:
    """Return ``(is_relevant, overall_confidence)``.

    A page is considered relevant when **either**:
    * its ``classification_label`` is not ``"irrelevant"`` **and** the
      classification confidence meets the configured threshold, **or**
    * its ``similarity_score`` meets the configured similarity threshold.

    The overall confidence is a weighted average
    (0.6 × classification_confidence + 0.4 × similarity_score).
    """
    conf_threshold = settings.classification_confidence_threshold
    sim_threshold = settings.similarity_threshold

    classified_relevant = (
        classification_label != "irrelevant"
        and classification_confidence >= conf_threshold
    )
    similar_enough = similarity_score >= sim_threshold

    is_relevant = classified_relevant or similar_enough

    # Weighted-average confidence
    overall_confidence = round(
        0.6 * classification_confidence + 0.4 * similarity_score, 4
    )

    return is_relevant, overall_confidence
