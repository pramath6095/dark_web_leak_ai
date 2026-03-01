"""HTML preprocessor – cleans raw HTML into analysis-ready plain text.

Strips boilerplate elements (forms, scripts, styles, navs, footers, headers,
ads), extracts visible text, and normalises whitespace. This runs before any
pipeline stage touches the content.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup, Comment

# Elements that are almost always boilerplate / spam on dark-web pages
_STRIP_TAGS = {
    "script", "style", "noscript",    # code / styling
    "form", "input", "button",        # forms
    "nav", "footer", "header",        # site chrome
    "iframe", "object", "embed",      # embedded content
    "svg", "canvas",                  # graphics
    "aside",                          # sidebars / ads
}

# Regex to collapse excessive whitespace into a single space
_MULTI_SPACE = re.compile(r"[ \t]+")
# Collapse 3+ consecutive newlines into 2
_MULTI_NEWLINE = re.compile(r"\n{3,}")


def preprocess_html(raw_html: str) -> str:
    """Convert raw HTML to clean plain text suitable for analysis.

    Steps
    -----
    1. Parse with BeautifulSoup (html.parser — no extra C dependency).
    2. Remove boilerplate elements (scripts, styles, forms, nav, footer, …).
    3. Remove HTML comments.
    4. Extract visible text.
    5. Normalise whitespace.

    Parameters
    ----------
    raw_html : str
        The raw HTML content straight from the scraper.

    Returns
    -------
    str
        Cleaned plain text.  May be empty if the page had no meaningful
        content after stripping.
    """
    if not raw_html or not raw_html.strip():
        return ""

    soup = BeautifulSoup(raw_html, "html.parser")

    # Remove boilerplate tags and their contents
    for tag_name in _STRIP_TAGS:
        for element in soup.find_all(tag_name):
            element.decompose()

    # Remove HTML comments
    for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
        comment.extract()

    # Extract text – separator keeps block-level elements readable
    text = soup.get_text(separator="\n")

    # Normalise whitespace
    lines = text.splitlines()
    cleaned_lines: list[str] = []
    for line in lines:
        line = _MULTI_SPACE.sub(" ", line).strip()
        if line:
            cleaned_lines.append(line)

    result = "\n".join(cleaned_lines)
    result = _MULTI_NEWLINE.sub("\n\n", result)

    return result.strip()
