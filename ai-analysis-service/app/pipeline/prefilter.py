"""Stage 1 – Rule-based pre-filter.

Check whether *any* of the supplied search strings appear in the page text.
Matching is case-insensitive and Unicode-normalised (NFC).

If no search string matches, the page is flagged as irrelevant and all
downstream ML stages are skipped for efficiency.
"""

from __future__ import annotations

import unicodedata


def prefilter(text: str, search_strings: list[str]) -> list[str]:
    """Return the subset of *search_strings* that appear in *text*.

    Both the text and each search string are NFC-normalised and lower-cased
    before comparison.

    Returns
    -------
    list[str]
        Search strings that matched (preserving original casing).
        Empty list ⇒ page should be treated as irrelevant.
    """
    normalised_text = unicodedata.normalize("NFC", text).lower()

    matched: list[str] = []
    for ss in search_strings:
        normalised_ss = unicodedata.normalize("NFC", ss).lower()
        if normalised_ss in normalised_text:
            matched.append(ss)

    return matched
