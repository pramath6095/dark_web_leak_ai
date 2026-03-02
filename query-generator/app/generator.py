"""LLM-based query generation for dark web monitoring.

Uses the HuggingFace Inference API to produce diverse dark-web search
queries from a detailed organization profile.

Includes deduplication and a quality gate that stops generation when the
LLM can no longer produce novel queries.
"""

from __future__ import annotations

import json
import logging
import re
import time as _time

import httpx

from app.config import settings
from app.state import state

_log = logging.getLogger("querygen.generator")

HF_INFERENCE_URL = "https://router.huggingface.co/v1/chat/completions"


# ── Prompt templates ──────────────────────────────────────────────────────

_INITIAL_PROMPT = """\
You are a specialized OSINT analyst and threat intelligence researcher with deep expertise \
in dark web monitoring, data breach investigation, and cybercriminal marketplace behavior. \
Your task is to generate realistic dark web search queries to detect potential data leaks \
related to a specific organization.

---

ORGANIZATION PROFILE:
- Company name: {company_name}
- Primary domain: {primary_domain}
- Alternative domains: {alt_domains}
- Email suffix: {email_suffix}
- Brand names / products: {brands}
- Industry: {industry}
- Description: {description}
- Known aliases or abbreviations: {aliases}

---

CONTEXT:
Dark web forums, paste sites, and marketplaces use specific vocabulary and conventions \
when advertising or discussing stolen data. Effective queries must reflect how threat \
actors actually communicate — not how security professionals write about breaches.

Common dark web conventions to reflect in queries:
- "combolist" or "combo" refers to credential pairs (email:password or user:pass)
- "fullz" refers to complete identity records including SSN, DOB, financial data
- "configs" refers to credential stuffing config files targeting specific services
- "logs" refers to stealer malware output containing saved credentials
- "OG" refers to original, first-time leaked data (not reshared)
- "fresh" indicates recently obtained data
- "valid" or "checked" indicates credentials have been verified as working
- "dump" refers to a full database export
- "dox" refers to personal information exposure on an individual or organization
- Threat actors frequently use l33tspeak, abbreviations, and intentional misspellings \
  to evade keyword filters (e.g., "p4ssw0rd", "cr3dz", "l3ak")
- Paste sites (Pastebin, Ghostbin, PrivateBin) are commonly referenced
- Forums like BreachForums, RaidForums (archived), Exploit.in use specific posting styles

---

QUERY CATEGORIES TO COVER:
Generate queries that span ALL of the following categories. Distribute the \
{count} queries across categories — do not cluster them all in one type.

1. DOMAIN-BASED (direct)
   Queries using the company's primary and alternative domains.
   Examples: "{{domain}} database dump", "{{domain}} breached", "site:{{domain}} leaked"

2. DOMAIN-BASED (l33tspeak / evasion variants)
   Slight character substitutions threat actors use to evade moderation.
   Examples: "{{d0main}} l3ak", "{{domain}} cr3dz"

3. EMAIL-BASED
   Queries targeting credential dumps containing the company's email suffix.
   Examples: "{{email_suffix}} combolist", "@{{domain}} fullz", "{{email_suffix}}:password"

4. BRAND / COMPANY NAME
   Queries using the company name, abbreviations, and known aliases.
   Examples: "{{company}} internal documents", "{{alias}} data breach 2024"

5. CREDENTIAL & ACCESS SALE
   Queries reflecting how access and credentials are sold on dark web marketplaces.
   Examples: "{{company}} RDP access", "{{company}} admin panel", \
             "{{company}} VPN credentials", "initial access {{domain}}"

6. DATABASE & DUMP SPECIFIC
   Queries targeting SQL dumps, database exports, and structured data leaks.
   Examples: "{{company}} SQL dump", "{{domain}} users table", \
             "{{company}} customer database", "{{domain}} .sql download"

7. DOCUMENT & INTERNAL DATA
   Queries targeting internal documents, financial records, or proprietary files.
   Examples: "{{company}} internal memo", "{{company}} financial report leak",\
             "{{company}} employee records", "{{domain}} confidential"

8. RANSOMWARE & EXTORTION
   Queries reflecting ransomware gang leak site postings and extortion language.
   Examples: "{{company}} ransomware", "{{company}} lockbit", \
             "{{domain}} stolen data", "{{company}} pay or publish"

9. STEALER LOG SPECIFIC
   Queries targeting output from infostealer malware (RedLine, Raccoon, Vidar etc.)
   Examples: "{{domain}} stealer logs", "{{company}} redline logs", \
             "{{email_suffix}} raccoon stealer"

10. PASTE SITE STYLE
    Short, raw queries mimicking how data is posted on paste sites.
    Examples: "{{domain}}:pass", "{{email_suffix}} leaked txt", \
              "{{company_abbrev}} dump pastebin"

11. MULTILINGUAL VARIANTS
    Queries in languages relevant to major dark web forum communities.
    Generate variants in Russian and German at minimum.
    Russian examples: "{{company}} утечка", "{{domain}} база данных", "{{company}} взлом"
    German examples: "{{company}} datenleck", "{{domain}} gehackt", "{{company}} datenbank"

12. FORUM-SPECIFIC CONTEXTUAL
    Queries that include forum context, sale indicators, or proof language.
    Examples: "{{company}} db for sale", "{{domain}} sample proof", \
              "{{company}} escrow accepted", "{{domain}} verified seller"

---

QUALITY RULES:
- Each query must be distinct — no paraphrasing of the same query
- Queries should be 2–7 words long, matching real search behavior
- Do not use overly formal or academic language — match threat actor vocabulary
- Include at least 3 queries with intentional misspellings or l33tspeak variants
- Include at least 4 non-English queries if {count} >= 15
- Do not include any explanatory text, numbering, or category labels in output
- Do not generate queries that are generic enough to apply to any company — \
  every query must be specific enough that it would only surface results \
  related to {company_name} or its infrastructure

---

OUTPUT FORMAT:
Return ONLY a valid JSON array of strings. No preamble, no explanation, \
no markdown formatting, no code fences. The array must contain exactly {count} items.

Correct output format:
["query one", "query two", "query three"]

Any response that is not a raw JSON array will be rejected and retried.\
"""

_MORE_QUERIES_PROMPT = """\
You are a specialized OSINT analyst and threat intelligence researcher with deep expertise \
in dark web monitoring, data breach investigation, and cybercriminal marketplace behavior.

---

ORGANIZATION PROFILE:
- Company name: {company_name}
- Primary domain: {primary_domain}
- Email suffix: {email_suffix}
- Brand names / products: {brands}
- Industry: {industry}
- Description: {description}
- Known aliases or abbreviations: {aliases}

---

CONTEXT:
You are in an iterative monitoring session. A first batch of search queries has already \
been deployed against dark web sources and paste sites. Those queries are now exhausted — \
meaning they have already been searched and their results processed. Your task is to \
think from entirely new angles to maximize coverage of sources that the first batch \
may have missed.

Effective dark web monitoring requires diversifying across:
- Different threat actor vocabularies and slang generations
- Different forum communities (each has its own posting conventions)
- Different data types that may be leaked (not just credentials)
- Different time references (old breaches being reshared vs. fresh leaks)
- Different attacker motivations (financial, hacktivist, nation-state, insider)

---

ALREADY USED QUERIES (DO NOT REPEAT OR PARAPHRASE ANY OF THESE):
{used_queries}

---

INSTRUCTIONS FOR GENERATING NEW QUERIES:
Analyze the used queries above and identify which angles, categories, and \
vocabulary styles have already been covered. Then deliberately generate queries \
that approach the target from angles NOT yet represented.

Specifically, for this new batch you must explore angles that were missed or \
underrepresented in the first batch. Use the following as a checklist — \
if a category was already well covered in the used queries, skip it and \
prioritize categories that were not touched at all:

1. TEMPORAL VARIANTS
   Queries referencing specific time periods, suggesting fresh or recent leaks.
   Examples: "{{company}} breach 2024", "{{domain}} leak january", \
             "{{company}} fresh dump 2025", "{{domain}} new combolist"

2. ATTACKER MOTIVATION VARIANTS
   Queries reflecting different attacker profiles and their language.
   - Financial/criminal: "{{company}} for sale", "{{domain}} buy access"
   - Hacktivist: "{{company}} exposed", "{{company}} ops", "#{{company}}leak"
   - Insider threat: "{{company}} employee leak", "{{domain}} insider data"
   - Ransomware: "{{company}} encrypted", "{{company}} negotiate", \
                 "{{company}} lockbit site:onion"

3. SPECIFIC DATA TYPE VARIANTS
   Queries targeting specific categories of data beyond generic credentials.
   Examples: \
   - "{{company}} HR records", "{{company}} payroll data"
   - "{{company}} source code", "{{domain}} git leak", "{{company}} github exposed"
   - "{{company}} customer PII", "{{domain}} GDPR breach"
   - "{{company}} intellectual property", "{{company}} trade secrets"
   - "{{company}} financial statements", "{{domain}} accounting leak"
   - "{{company}} board documents", "{{company}} M&A data"
   - "{{company}} API keys", "{{domain}} secrets exposed", "{{company}} .env leak"
   - "{{company}} network diagrams", "{{domain}} infrastructure map"

4. INFRASTRUCTURE & TECHNICAL VARIANTS
   Queries targeting technical artifacts rather than data content.
   Examples: "{{domain}} subdomain takeover", "{{company}} exposed server",\
             "{{domain}} open directory", "{{company}} unprotected S3",\
             "{{domain}} firebase exposed", "{{company}} Jenkins leak",\
             "{{domain}} elasticsearch dump", "{{company}} kibana open"

5. THIRD-PARTY & SUPPLY CHAIN VARIANTS
   Queries targeting leaks that originated from vendors, partners, or \
   third-party services used by the company rather than the company itself.
   Examples: "{{company}} vendor breach", "{{company}} third party leak",\
             "{{domain}} CRM dump", "{{company}} Salesforce data",\
             "{{company}} AWS credentials", "{{domain}} cloud leak"

6. FORUM-SPECIFIC POSTING STYLE VARIANTS
   Different forums have different conventions. Generate queries mimicking \
   posting styles from communities not covered in the first batch.
   - Exploit.in style: formal, Russian-language, structured offers
   - BreachForums style: English, reputation-based, sample-first
   - Telegram channel style: short, urgent, "FREE LEAK" framing
   - XSS.is style: technical, Russian, access-sale focused
   Examples: "{{company}} продам базу", "{{domain}} акк продам",\
             "FREE {{company}} combo", "{{domain}} checker config",\
             "{{company}} access shop", "vouched {{domain}} fullz"

7. REPOST & ARCHIVE VARIANTS
   Queries targeting reshared or archived versions of old breaches \
   being recirculated as new.
   Examples: "{{company}} repost", "{{domain}} old breach", \
             "{{company}} 2019 2020 2021 dump", "archive {{domain}} leak",\
             "{{company}} combo refresh", "{{domain}} previously leaked"

8. OBFUSCATION & EVASION VARIANTS
   More aggressive character substitution and obfuscation than the first batch.
   Use different substitution patterns not already in the used queries.
   Examples: "{{c0mpany}} l3ak", "{{d0ma1n}} cr3dz", "{{company_abbrev}} pwn3d",\
             "{{company}} @dmin", "{{domain}} 0day", "{{company}} 0wned"

9. SOCIAL PROOF & VERIFICATION VARIANTS
   Queries reflecting how sellers prove legitimacy to buyers.
   Examples: "{{company}} sample download", "{{domain}} proof pack",\
             "{{company}} verified leak", "{{domain}} checker valid",\
             "{{company}} checked combos", "{{domain}} live accounts"

10. CROSS-LANGUAGE EXPANSION
    If the first batch covered Russian and German, now expand to:
    - French: "{{company}} fuite de données", "{{domain}} base de données volée"
    - Spanish: "{{company}} base de datos filtrada", "{{domain}} brecha"
    - Portuguese: "{{company}} vazamento", "{{domain}} dados expostos"
    - Chinese: "{{company}} 数据泄露", "{{domain}} 数据库"
    - Arabic: "{{company}} تسريب بيانات"

11. PASTE SITE & CLEARNET CROSSOVER VARIANTS
    Queries targeting content that leaks across clearnet paste and \
    sharing sites before being picked up on dark web forums.
    Examples: "{{domain}} pastebin 2024", "{{company}} ghostbin",\
              "{{domain}} privatebin", "{{company}} hastebin leak",\
              "{{domain}} justpaste", "{{company}} telegra.ph"

12. IDENTITY & EXECUTIVE TARGETING VARIANTS
    Queries targeting executives or specific individuals associated \
    with the company, which often accompany corporate breaches.
    Examples: "{{company}} CEO dox", "{{company}} executive leak",\
              "{{domain}} employee directory", "{{company}} HR database",\
              "{{company}} Active Directory dump", "{{domain}} LDAP export"

---

QUALITY RULES:
- Analyze the used queries list carefully — any query that is a synonym, \
  rephrasing, or close variant of a used query is INVALID and must not appear
- Each new query must represent a genuinely different search angle or vocabulary
- Queries should be 2–7 words, matching real dark web search behavior
- Do not use overly formal or academic phrasing — match threat actor vocabulary
- Every query must be specific enough to only surface results related to \
  {company_name} — no generic queries that could match any organization
- At least {multilingual_count} queries must be non-English
- At least 2 queries must use obfuscation or l33tspeak variants
- At least 3 queries must target data types other than credentials \
  (documents, source code, infrastructure, PII etc.)

---

DEDUPLICATION CHECK:
Before finalizing your output, review your generated queries one final time \
against the used queries list. Remove any query that:
- Is identical to a used query
- Is a direct rephrasing of a used query  
- Uses the same core keyword combination as a used query with only filler words changed

Replace removed queries with genuinely new ones until you have exactly {count}.

---

OUTPUT FORMAT:
Return ONLY a valid JSON array of strings. No preamble, no explanation, \
no markdown formatting, no code fences. The array must contain exactly {count} items.

Correct output format:
["query one", "query two", "query three"]

Any response that is not a raw JSON array will be rejected and retried.\
"""

_SEARCH_STRINGS_PROMPT = """\
You are a specialized threat intelligence analyst and data-leak detection expert with \
deep expertise in corporate OSINT, dark web monitoring, and breach investigation. \
Your task is to extract every possible string identifier that could link scraped \
dark web content back to a specific organization.

---

ORGANIZATION PROFILE:
- Company name: {company_name}
- Primary domain: {primary_domain}
- Alternative domains: {alt_domains}
- Email suffix: {email_suffix}
- Brand names / products: {brands}
- Industry: {industry}
- Headquarters country: {country}
- Description: {description}

---

CONTEXT:
Search strings are used in two ways in this pipeline:

1. RULE-BASED PRE-FILTER — fast exact/substring matching against raw scraped text.
   These strings need to be specific enough to avoid false positives but broad \
   enough to catch variations in how threat actors reference the organization.

2. SEMANTIC SIMILARITY ANCHOR — the string list is combined into a profile \
   query that gets embedded and compared against document embeddings.
   These strings need to capture the full semantic fingerprint of the organization.

Both uses require different types of strings, so your output must cover both \
categories — precise identifiers AND descriptive contextual strings.

---

EXTRACTION CATEGORIES:
Extract strings across ALL of the following categories. Every category must \
be represented in the output.

1. DOMAIN IDENTIFIERS (highest priority — always include)
   Extract every domain variant that could appear in leaked content.
   - Primary domain: "company.com"
   - Without TLD: "company" (if distinctive enough to not cause false positives)
   - With common subdomains: "mail.company.com", "vpn.company.com", \
     "remote.company.com", "portal.company.com", "intranet.company.com"
   - Alternative TLDs if known: "company.io", "company.net", "company.co"
   - Country-specific TLDs if relevant: "company.de", "company.co.uk"

2. EMAIL IDENTIFIERS
   Extract every email pattern associated with the organization.
   - Standard suffix: "@company.com"
   - Alternative suffixes: "@subsidiary.com", "@division.company.com"
   - Common internal patterns if inferable: "firstname.lastname@company.com"
   - Service account patterns: "noreply@company.com", "admin@company.com"
   - Note: include the @ symbol — this distinguishes email from domain hits

3. COMPANY NAME VARIANTS
   Extract every way the company name could realistically appear in text.
   - Full legal name: "Acme Corporation"
   - Short name: "Acme"
   - Common abbreviation: "ACME"
   - Lowercase variant: "acme" (for case-insensitive matching)
   - Name with industry suffix removed: if "Acme Financial Services", add "Acme Financial"
   - Name as it might appear in file paths: "AcmeCorp", "acme_corp", "acme-corp"
   - Name as it might appear in database table names: "acme_users", "acmedb"
   - Camel case variants: "AcmeCorporation", "AcmeCorp"

4. BRAND AND PRODUCT NAMES
   Every sub-brand, product line, or service name associated with the organization.
   - Each brand name in full
   - Each brand name abbreviated
   - Product-specific domains if they exist: "acmepay.com"
   - App or platform names: "AcmePortal", "AcmePay", "AcmeDrive"
   - Internal codenames if publicly known or inferable

5. INTERNAL SYSTEM & INFRASTRUCTURE IDENTIFIERS
   Strings that would only appear in genuinely internal data.
   These are high-confidence indicators of a real breach if found.
   - Internal hostnames patterns: "acme-dc01", "acme-mail01", "corp.acme.local"
   - Internal domain suffix: "acme.local", "acme.internal", "corp.acme.com"
   - VPN or remote access identifiers: "vpn.acme.com", "remote.acme.com"
   - Common internal system names by industry:
     * Finance: "acme-erp", "acme-sap", "acme-oracle"
     * Tech: "acme-jira", "acme-confluence", "acme-gitlab"
     * Healthcare: "acme-emr", "acme-epic", "acme-hl7"
   - AWS/cloud resource naming conventions: "acme-prod", "acme-staging", "acme-s3"
   - Internal project codenames if publicly known

6. CREDENTIAL & ACCESS PATTERN IDENTIFIERS
   Strings that would appear in credential dumps specific to this organization.
   - Username format patterns: "a.lastname", "firstname.l", "flastname"
     (infer from email format if known)
   - Employee ID prefix patterns if publicly known: "EMP", "ACM"
   - Internal system login URLs: "sso.acme.com", "login.acme.com", \
     "acme.okta.com", "acme.onelogin.com"
   - API endpoint identifiers: "api.acme.com", "acme-api"

7. LEGAL & CORPORATE IDENTIFIERS
   Formal identifiers that appear in official documents and financial leaks.
   - Full legal entity name: "Acme Corporation Inc."
   - Registered business variants: "Acme Corp.", "Acme Co."
   - Parent company name if applicable
   - Subsidiary names if applicable
   - Stock ticker if publicly listed: "ACME"
   - VAT or registration number format prefix if known by industry

8. INDUSTRY-SPECIFIC CONTEXTUAL STRINGS
   Strings that combine the company name with industry-specific terms \
   that would appear in relevant leaked documents.
   - "{{company}} customer data"
   - "{{company}} patient records" (healthcare)
   - "{{company}} transaction data" (finance)
   - "{{company}} source code" (tech)
   - "{{company}} employee records"
   - "{{company}} payroll"
   These are lower priority but useful for semantic matching.

9. THREAT-ACTOR REFERENCE VARIANTS
   How threat actors typically reference organizations in posts and advertisements.
   - "{{company}} DB" — database abbreviation
   - "{{company}} fullz" — complete identity records
   - "{{company}} combo" — credential combination list
   - "{{company}} logs" — stealer log reference
   - "{{company}} access" — initial access sale language
   These help catch forum posts that don't contain domains or formal names.

10. KNOWN PUBLIC FIGURES (if applicable and publicly known)
    Names of C-suite executives or board members that would appear in \
    targeted leaks, dox posts, or executive credential dumps.
    Only include if verifiably public information — do not infer or fabricate.
    - "Firstname Lastname" (CEO name if public)
    - "F. Lastname" variant
    - Executive email if publicly listed on company website

---

STRING QUALITY RULES:
- Every string must be specific enough that a match is meaningful — \
  single common words like "corp" or "data" alone are NOT valid strings
- Every string must be realistic — only include what would genuinely \
  appear in leaked content, not theoretical variants
- Strings should be ready for direct substring matching — no regex patterns,\
  no wildcards, no special characters unless they are part of the actual string\
  (e.g., "@company.com" is valid, "company*" is not)
- Strings must be lowercase unless casing is semantically significant \
  (e.g., stock tickers are uppercase by convention)
- Aim for {min_count}–{max_count} total strings — enough for broad coverage \
  without introducing noise from overly generic terms
- Prioritize strings that would ONLY appear in content related to this \
  specific organization — high specificity is more valuable than high quantity

---

DEDUPLICATION RULE:
Before outputting, remove any string that is a pure substring of another \
string already in the list where the longer string is already included \
AND the shorter string is too generic to be useful alone.
Example: if "acme.com" is in the list, "@acme.com" should also be included \
(it is more specific, not redundant) but plain "acme" alone may be dropped \
if the company name is common.

---

OUTPUT FORMAT:
Return ONLY a valid JSON array of strings, ordered from highest to lowest \
specificity (most unique identifiers first, contextual strings last). \
No preamble, no explanation, no category labels, no markdown, no code fences.

Correct format:
["acme.com", "@acme.com", "mail.acme.com", "AcmeCorp", "acme_users", ...]

Any response that is not a raw JSON array will be rejected and retried.\
"""


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
        "max_tokens": 4096,
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
        primary_domain=state.primary_domain or "N/A",
        alt_domains=state.alt_domains or "N/A",
        email_suffix=state.email_suffix or "N/A",
        brands=state.brands or "N/A",
        industry=state.industry or "N/A",
        aliases=state.aliases or "N/A",
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
        primary_domain=state.primary_domain or "N/A",
        email_suffix=state.email_suffix or "N/A",
        brands=state.brands or "N/A",
        industry=state.industry or "N/A",
        aliases=state.aliases or "N/A",
        used_queries=used_list,
        count=settings.initial_query_count,
        multilingual_count=settings.multilingual_query_count,
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
        primary_domain=state.primary_domain or "N/A",
        alt_domains=state.alt_domains or "N/A",
        email_suffix=state.email_suffix or "N/A",
        brands=state.brands or "N/A",
        industry=state.industry or "N/A",
        country=state.country or "N/A",
        min_count=settings.search_strings_min_count,
        max_count=settings.search_strings_max_count,
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

    # Use primary_domain if set
    if state.primary_domain:
        strings.append(state.primary_domain)
        strings.append(f"@{state.primary_domain}")
    elif "." in name:
        strings.append(f"@{name}")
    else:
        # Try common domain
        lower = name.lower().replace(" ", "")
        strings.append(f"{lower}.com")
        strings.append(f"@{lower}.com")

    # Add email suffix if explicitly set
    if state.email_suffix and state.email_suffix not in strings:
        strings.append(state.email_suffix)

    # Add brand names
    if state.brands:
        for brand in state.brands.split(","):
            brand = brand.strip()
            if brand and brand not in strings:
                strings.append(brand)

    # Add aliases
    if state.aliases:
        for alias in state.aliases.split(","):
            alias = alias.strip()
            if alias and alias not in strings:
                strings.append(alias)

    return strings


def _generate_fallback_queries() -> None:
    """Create basic queries without LLM access."""
    name = state.company_name
    domain = state.primary_domain or name.lower().replace(" ", "") + ".com"

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
        f"{domain} data breach",
        f"@{domain} leaked credentials",
    ]

    # Add domain-based queries from alt_domains
    if state.alt_domains:
        for d in state.alt_domains.split(",")[:3]:
            d = d.strip()
            if d:
                patterns.append(f"{d} data breach")
                patterns.append(f"@{d} leaked credentials")

    # Add brand-based queries
    if state.brands:
        for brand in state.brands.split(",")[:3]:
            brand = brand.strip()
            if brand:
                patterns.append(f"{brand} data leak")

    state.add_queries(patterns)
    state.generation_round = 1
    _log.info("Generated %d fallback queries (no LLM)", len(patterns))
