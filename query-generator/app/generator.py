"""LLM-based query generation for dark web monitoring.

Uses the OpenRouter API (Dolphin-Mistral or configurable model) to produce
diverse dark-web search queries from a company name and description.

Includes deduplication and a quality gate that stops generation when the
LLM can no longer produce novel queries.
"""

from __future__ import annotations

import json
import logging
import re

import httpx

from app.config import settings
from app.state import state

_log = logging.getLogger("querygen.generator")

HF_INFERENCE_URL = "https://router.huggingface.co/v1/chat/completions"


# ── Prompt templates ──────────────────────────────────────────────────────

_INITIAL_PROMPT = """\
You are an OSINT expert helping monitor the dark web for data leaks.

Company name: {company_name}
Company description: {description}

Generate exactly {count} diverse dark-web search queries that could find \
leaked data, credentials, databases, or internal documents related to this \
company. Include variations like:
- Domain-based queries (e.g., "company.com data breach")
- Email-based queries (e.g., "@company.com leaked")
- Brand-name queries (e.g., "CompanyName database dump")
- Product/service-specific queries
- Credential-related queries
- Paste-site style queries

Return ONLY a JSON array of strings, nothing else. Example:
["query one", "query two", "query three"]
"""

_MORE_QUERIES_PROMPT = """\
You are an OSINT expert. You have already used these search queries to \
monitor the dark web for leaks related to "{company_name}":

{used_queries}

Generate exactly {count} NEW and DIFFERENT dark-web search queries for the \
same company. Do NOT repeat any of the queries listed above. Think of \
different angles, keywords, and phrasings.

Company description: {description}

Return ONLY a JSON array of strings, nothing else.
"""

_SEARCH_STRINGS_PROMPT = """\
You are a data-leak detection expert. Given a company's information, \
extract all strings that should be searched for when analyzing scraped \
dark-web content to determine if it relates to this company.

Company name: {company_name}
Company description: {description}

Extract strings like:
- Company domain(s) (e.g., "company.com")
- Email suffixes (e.g., "@company.com")
- Brand names and variations
- Product names
- Key employee names if publicly known
- Internal system names if mentioned

Return ONLY a JSON array of strings, nothing else. Example:
["company.com", "@company.com", "CompanyName", "Company Name"]
"""


import time as _time


def _call_llm(prompt: str, max_retries: int = 3) -> str:
    """Send a prompt to HuggingFace Inference API and return the response text.

    Retries with exponential backoff on 429 Too Many Requests.
    """
    url = HF_INFERENCE_URL
    headers = {
        "Authorization": f"Bearer {settings.hf_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.hf_model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 2048,
        "temperature": 0.8,
    }

    last_exc = None
    for attempt in range(max_retries):
        try:
            resp = httpx.post(
                url,
                json=payload,
                headers=headers,
                timeout=90.0,
            )
            if resp.status_code in (429, 503):
                wait = 5 * (3 ** attempt)  # 5s, 15s, 45s
                _log.warning(
                    "HuggingFace %d, retrying in %ds (attempt %d/%d)",
                    resp.status_code,
                    wait, attempt + 1, max_retries,
                )
                _time.sleep(wait)
                continue
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (429, 503):
                wait = 5 * (3 ** attempt)
                _log.warning("Rate limited, retrying in %ds", wait)
                _time.sleep(wait)
                last_exc = exc
                continue
            raise
        except Exception as exc:
            last_exc = exc
            _log.warning("LLM call attempt %d failed: %s", attempt + 1, exc)
            _time.sleep(2)

    raise last_exc or RuntimeError("All LLM retries exhausted")


def _parse_json_array(text: str) -> list[str]:
    """Extract a JSON array of strings from LLM output.

    Handles common LLM quirks like markdown code fences.
    """
    # Strip markdown fences
    cleaned = re.sub(r"```(?:json)?\s*", "", text)
    cleaned = cleaned.strip()

    # Try to find a JSON array in the text
    match = re.search(r"\[.*\]", cleaned, re.DOTALL)
    if match:
        try:
            result = json.loads(match.group())
            if isinstance(result, list):
                return [str(item).strip() for item in result if str(item).strip()]
        except json.JSONDecodeError:
            pass

    # Fallback: split by newlines, strip quotes/dashes
    lines = cleaned.split("\n")
    queries = []
    for line in lines:
        line = line.strip().strip("-").strip("•").strip('"').strip("'").strip(",").strip()
        if line and not line.startswith("[") and not line.startswith("]"):
            queries.append(line)
    return queries


# ── Public API ────────────────────────────────────────────────────────────

def generate_initial_queries() -> list[str]:
    """Generate the first batch of search queries from company info.

    Also generates search strings. Stores everything in state.
    """
    if not state.company_name:
        _log.warning("No company configured, cannot generate queries")
        return []

    _log.info("Generating initial queries for '%s'", state.company_name)

    # Generate search queries
    prompt = _INITIAL_PROMPT.format(
        company_name=state.company_name,
        description=state.company_description,
        count=settings.initial_query_count,
    )

    try:
        raw = _call_llm(prompt)
        queries = _parse_json_array(raw)
        added = state.add_queries(queries)
        state.generation_round = 1
        _log.info("Generated %d initial queries (%d unique)", len(queries), added)
    except Exception as exc:
        _log.error("Failed to generate initial queries: %s", exc)
        # Fall back to basic queries
        _generate_fallback_queries()

    # Generate search strings
    _generate_search_strings()

    return state.all_queries.copy()


def generate_more_queries() -> int:
    """Ask the LLM for additional queries. Returns count of new queries added.

    Returns 0 if the LLM can no longer produce novel queries (quality gate).
    """
    if state.exhausted:
        return 0

    if state.generation_round >= settings.max_generation_rounds:
        _log.info("Reached max generation rounds (%d), stopping",
                   settings.max_generation_rounds)
        state.exhausted = True
        return 0

    used_list = "\n".join(f'- "{q}"' for q in state.all_queries)
    prompt = _MORE_QUERIES_PROMPT.format(
        company_name=state.company_name,
        description=state.company_description,
        used_queries=used_list,
        count=settings.initial_query_count,
    )

    try:
        raw = _call_llm(prompt)
        queries = _parse_json_array(raw)
        total_generated = len(queries)
        added = state.add_queries(queries)
        state.generation_round += 1

        duplicate_ratio = (total_generated - added) / max(total_generated, 1)
        _log.info(
            "Round %d: generated %d, new %d, duplicate ratio %.0f%%",
            state.generation_round, total_generated, added, duplicate_ratio * 100,
        )

        # Quality gate: if too many duplicates, stop
        if duplicate_ratio > settings.duplicate_threshold:
            _log.info("Duplicate ratio %.0f%% exceeds threshold %.0f%%, stopping",
                       duplicate_ratio * 100, settings.duplicate_threshold * 100)
            state.exhausted = True
            return added

        return added

    except Exception as exc:
        _log.error("Failed to generate more queries: %s", exc)
        state.exhausted = True
        return 0


def _generate_search_strings() -> None:
    """Generate detailed search strings from company info via LLM."""
    prompt = _SEARCH_STRINGS_PROMPT.format(
        company_name=state.company_name,
        description=state.company_description,
    )

    try:
        raw = _call_llm(prompt)
        strings = _parse_json_array(raw)
        # Always include basic derived strings
        basics = _derive_basic_strings()
        all_strings = basics + [s for s in strings if s not in basics]
        state.set_search_strings(all_strings)
        _log.info("Generated %d search strings", len(state.search_strings))
    except Exception as exc:
        _log.error("Failed to generate search strings via LLM: %s", exc)
        state.set_search_strings(_derive_basic_strings())


def _derive_basic_strings() -> list[str]:
    """Derive obvious search strings from the company name without LLM."""
    name = state.company_name.strip()
    if not name:
        return []

    strings = [name]
    # If it looks like a domain
    if "." in name:
        strings.append(f"@{name}")
    else:
        # Try common domain
        lower = name.lower().replace(" ", "")
        strings.append(f"{lower}.com")
        strings.append(f"@{lower}.com")

    return strings


def _generate_fallback_queries() -> None:
    """Create basic queries without LLM access."""
    name = state.company_name
    patterns = [
        f"{name} data breach",
        f"{name} leaked database",
        f"{name} credentials leak",
        f"{name} data dump",
        f"{name} hacked",
        f"{name} password leak",
        f"{name} internal documents",
        f"{name} employee data",
        f"{name} customer data leak",
        f"{name} database dump dark web",
    ]

    # Add domain-based queries if description mentions a domain
    desc = state.company_description.lower()
    import re as _re
    domains = _re.findall(r"[a-z0-9.-]+\.[a-z]{2,}", desc)
    for domain in domains[:3]:
        patterns.append(f"{domain} data breach")
        patterns.append(f"@{domain} leaked credentials")

    state.add_queries(patterns)
    state.generation_round = 1
    _log.info("Generated %d fallback queries (no LLM)", len(patterns))
