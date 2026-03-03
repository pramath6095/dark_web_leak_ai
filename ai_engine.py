import os
import json
import time
import requests
from dotenv import load_dotenv
load_dotenv()

import warnings
warnings.filterwarnings("ignore")


# per-stage gemini api keys with fallback
STAGE_KEY_MAP = {
    "refine":        os.getenv("GEMINI_KEY_REFINE"),
    "filter":        os.getenv("GEMINI_KEY_FILTER"),
    "classify":      os.getenv("GEMINI_KEY_CLASSIFY"),
    "summary":       os.getenv("GEMINI_KEY_SUMMARY"),
    "file_analysis": os.getenv("GEMINI_KEY_FILE_ANALYSIS"),
}
GEMINI_FALLBACK_KEY = os.getenv("GEMINI_API_KEY")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_MAX_RETRIES = 3
GEMINI_RETRY_DELAYS = [2, 5, 10]

# per-stage output token caps — generous but not wasteful
STAGE_MAX_TOKENS = {
    "refine":        512,
    "filter":        512,
    "classify":      3072,
    "summary":       4096,
    "file_analysis": 3072,
}

# stages that output JSON — use response_mime_type for reliable parsing
STAGE_JSON_MODE = {"classify", "file_analysis"}

# per-key rate limit tracking: key -> {last_429: float, cooldown_until: float, fails: int}
_key_state = {}


def _is_key_available(key: str) -> bool:
    """check if a key is not in cooldown"""
    state = _key_state.get(key)
    if not state:
        return True
    return time.time() >= state.get("cooldown_until", 0)


def _record_rate_limit(key: str):
    """record a 429 and set exponential cooldown"""
    state = _key_state.setdefault(key, {"fails": 0, "cooldown_until": 0})
    state["fails"] = state.get("fails", 0) + 1
    state["last_429"] = time.time()
    # exponential cooldown: 30s, 60s, 120s
    cooldown = min(30 * (2 ** (state["fails"] - 1)), 120)
    state["cooldown_until"] = time.time() + cooldown
    print(f"  [!] Key ...{key[-4:]} rate limited, cooldown {cooldown}s")


def _record_success(key: str):
    """reset fail count on success"""
    if key in _key_state:
        _key_state[key]["fails"] = 0


def _get_gemini_key(stage: str) -> str:
    """get the best available api key, skipping keys in cooldown. rotates across all keys."""
    # try stage-specific key first
    candidates = []
    stage_key = STAGE_KEY_MAP.get(stage)
    if stage_key and stage_key.strip():
        candidates.append(stage_key.strip())
    # try fallback key
    if GEMINI_FALLBACK_KEY and GEMINI_FALLBACK_KEY.strip():
        fb = GEMINI_FALLBACK_KEY.strip()
        if fb not in candidates:
            candidates.append(fb)
    # try keys from other stages
    for other_stage, other_key in STAGE_KEY_MAP.items():
        if other_key and other_key.strip():
            k = other_key.strip()
            if k not in candidates:
                candidates.append(k)
    # return first available (not in cooldown)
    for key in candidates:
        if _is_key_available(key):
            return key
    # all in cooldown — return first anyway (will retry)
    return candidates[0] if candidates else None


def _ollama_available() -> bool:
    """check if ollama is running locally"""
    try:
        r = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=3)
        return r.status_code == 200 and len(r.json().get("models", [])) > 0
    except:
        return False


def _get_ollama_model() -> str:
    """get first available ollama model"""
    try:
        r = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=3)
        models = r.json().get("models", [])
        if models:
            return models[0].get("name", "llama3.2")
    except:
        pass
    return None


def _call_gemini(prompt: str, api_key: str, stage: str = "summary", temperature: float = 0.3) -> str:
    """call gemini api with retry logic for rate limits and optional JSON mode"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={api_key}"
    
    max_tokens = STAGE_MAX_TOKENS.get(stage, 4096)
    gen_config = {
        "temperature": temperature,
        "maxOutputTokens": max_tokens,
    }
    # JSON mode for structured output stages
    if stage in STAGE_JSON_MODE:
        gen_config["responseMimeType"] = "application/json"
    
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": gen_config
    }
    
    for attempt in range(GEMINI_MAX_RETRIES):
        try:
            response = requests.post(url, json=payload, timeout=60)
            
            # handle rate limit with retry + tracking
            if response.status_code == 429:
                _record_rate_limit(api_key)
                delay = GEMINI_RETRY_DELAYS[attempt] if attempt < len(GEMINI_RETRY_DELAYS) else 10
                print(f"  [!] Rate limited (429). Retrying in {delay}s... (attempt {attempt + 1}/{GEMINI_MAX_RETRIES})")
                time.sleep(delay)
                continue
            
            response.raise_for_status()
            _record_success(api_key)
            data = response.json()
            
            candidates = data.get("candidates", [])
            if candidates:
                parts = candidates[0].get("content", {}).get("parts", [])
                if parts:
                    return parts[0].get("text", "")
            return ""
        except requests.exceptions.HTTPError as e:
            if e.response.status_code != 429:
                print(f"  [!] Gemini API error: {e.response.status_code}")
                raise
        except Exception as e:
            print(f"  [!] Gemini request failed: {str(e)[:80]}")
            raise
    
    raise Exception("Gemini rate limit exceeded after all retries")


def _call_ollama(prompt: str, model: str) -> str:
    """call ollama api for local model inference"""
    url = f"{OLLAMA_BASE_URL}/api/generate"
    
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.3,
        }
    }
    
    try:
        response = requests.post(url, json=payload, timeout=120)
        response.raise_for_status()
        return response.json().get("response", "")
    except Exception as e:
        print(f"  [!] Ollama request failed: {str(e)[:80]}")
        raise


def call_llm(prompt: str, stage: str, temperature: float = 0.3) -> str:
    """
    call the best available llm for a given stage.
    fallback chain: stage-specific gemini key -> other keys -> ollama -> error
    """
    # try gemini first
    gemini_key = _get_gemini_key(stage)
    if gemini_key:
        try:
            return _call_gemini(prompt, gemini_key, stage=stage, temperature=temperature)
        except Exception:
            print(f"  [!] Gemini failed for stage '{stage}', trying fallback...")
    
    # try ollama
    if _ollama_available():
        model = _get_ollama_model()
        if model:
            print(f"  [*] Using Ollama ({model}) for stage '{stage}'")
            try:
                return _call_ollama(prompt, model)
            except Exception:
                print(f"  [!] Ollama also failed for stage '{stage}'")
    
    print(f"  [-] No LLM available for stage '{stage}'. Skipping AI step.")
    return None


def _call_llm_json_retry(prompt: str, stage: str) -> list:
    """
    call LLM for JSON output with automatic retry on parse failure.
    on failure, retries with temperature=0.1 and stricter instructions.
    """
    result = call_llm(prompt, stage)
    if not result:
        return None
    
    # first parse attempt
    try:
        return _parse_classification_json(result)
    except (json.JSONDecodeError, ValueError) as e:
        print(f"  [!] JSON parse failed: {str(e)[:50]}. Retrying with temp=0.1...")
    
    # retry with lower temperature and stricter prompt
    retry_prompt = "Output ONLY raw JSON array. No markdown fences, no explanation, no text before or after.\n\n" + prompt
    result = call_llm(retry_prompt, stage, temperature=0.1)
    if not result:
        return None
    
    try:
        return _parse_classification_json(result)
    except (json.JSONDecodeError, ValueError) as e:
        print(f"  [!] JSON retry also failed: {str(e)[:50]}")
        return None


# ============================================================
# STAGE 1: QUERY REFINEMENT
# ============================================================

def refine_query(query: str) -> list:
    """
    stage 1: generate threat-intelligence-optimized search strings for dark web.
    returns list of keyword strings targeting real threat data.
    """
    prompt = f"""Dark web threat intelligence analyst. Generate exactly 5 search strings to find REAL threats related to the user's input on dark web search engines (.onion).

Rules:
1. Output ONLY 5 search strings, one per line. No numbering, no explanation, no quotes.
2. Each 2-5 words. KEEP the target name in every query.
3. Each query MUST target a DIFFERENT threat surface:
   - Data breach / leak exposure (breach, leak, exposed, compromised, hacked)
   - Ransomware / extortion (ransomware, ransom, lockbit, alphv, leak blog)
   - Credential exposure (credentials, login, combolist, stealer logs, infostealer)
   - Forum/marketplace chatter (selling, for sale, access, exploit, vulnerability)
   - Paste / dump sites (paste, dump, database, records, dox)
4. Think like a threat actor — use terms they actually use on forums and paste sites.

Example - Input: "Accenture" - Output:
Accenture data breach leaked
Accenture ransomware leak blog
Accenture credentials stealer logs
Accenture access selling forum
Accenture database dump paste

User input: {query}"""

    result = call_llm(prompt, "refine")
    if result:
        import re
        lines = [line.strip().strip('"').strip("'").strip('-').strip()
                 for line in result.strip().split("\n") if line.strip()]
        keywords = []
        for line in lines:
            cleaned = re.sub(r'^\d+[\.\)\-]\s*', '', line).strip()
            if cleaned and len(cleaned) > 2:
                keywords.append(cleaned)

        if keywords:
            return keywords[:5]


    return [query]


# ============================================================
# STAGE 2: RESULT FILTERING
# ============================================================

def filter_results(query: str, results: list) -> list:
    """
    stage 2: use llm to pick the top 20 most relevant search results.
    results format: list of dicts with {url, title}
    """
    if not results:
        return []
    
    if len(results) <= 20:
        return results
    
    # build numbered list for llm
    results_text = []
    for i, item in enumerate(results, 1):
        if isinstance(item, dict):
            title = item.get("title", "Untitled")[:60]
            url_short = item.get("url", "")[:50]
        else:
            title = str(item)[:60]
            url_short = str(item)[:50]
        results_text.append(f"{i}. [{title}] — {url_short}")
    
    results_block = "\n".join(results_text)
    
    prompt = f"""OSINT relevance analyst. From {len(results)} dark web search results, select the top 20 most likely to contain actual leaked data, credentials, or threat intelligence.

Query: {query}

Results:
{results_block}

Prioritize actual data leaks, credential dumps, paste sites, forum breach posts. Deprioritize search/error pages and generic marketplaces.
Output ONLY comma-separated indices of the top 20, most relevant first. Nothing else.

Output:"""

    result = call_llm(prompt, "filter")
    if result:
        # parse indices from response
        import re
        parsed = []
        for match in re.findall(r"\d+", result):
            try:
                idx = int(match)
                if 1 <= idx <= len(results):
                    parsed.append(idx)
            except ValueError:
                continue
        
        # deduplicate while preserving order
        seen = set()
        unique_indices = []
        for idx in parsed:
            if idx not in seen:
                seen.add(idx)
                unique_indices.append(idx)
        
        if unique_indices:
            filtered = [results[i - 1] for i in unique_indices[:20]]
            return filtered
    
    # fallback: return first 20
    print("  [!] Could not parse filter response. Using first 20 results.")
    return results[:20]


# ============================================================
# STAGE 3: THREAT CLASSIFICATION (NEW - not in Robin)
# ============================================================

def _parse_classification_json(result: str) -> list:
    """parse classification JSON from LLM response, handling markdown fences"""
    cleaned = result.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned
        cleaned = cleaned.rsplit("```", 1)[0]
    cleaned = cleaned.strip()
    return json.loads(cleaned)


def classify_threats(query: str, scraped_data: dict) -> dict:
    """
    stage 3: classify each scraped page into threat categories with severity.
    processes in batches of 6 to prevent JSON truncation.
    uses cleaned content for better signal.
    returns dict of url -> {category, severity, reason, evidence}
    """
    if not scraped_data:
        return {}
    
    # clean content before classification
    try:
        from content_cleaner import clean_content, extract_meaningful_section
        use_cleaner = True
    except ImportError:
        use_cleaner = False
    
    # build entries with cleaned content
    entries = []
    for url, content in scraped_data.items():
        if content.startswith("[ERROR"):
            continue
        if use_cleaner:
            content = extract_meaningful_section(clean_content(content), max_chars=800)
        else:
            content = content[:800]
        entries.append((url, content))
    
    if not entries:
        return {}
    
    # batch processing — 6 pages per LLM call to prevent JSON truncation
    BATCH_SIZE = 6
    all_classified = {}
    
    for batch_start in range(0, len(entries), BATCH_SIZE):
        batch = entries[batch_start:batch_start + BATCH_SIZE]
        batch_num = (batch_start // BATCH_SIZE) + 1
        total_batches = (len(entries) + BATCH_SIZE - 1) // BATCH_SIZE
        
        if total_batches > 1:
            print(f"  [*] Classifying batch {batch_num}/{total_batches} ({len(batch)} pages)...")
        
        content_block = "\n\n".join(
            f"[{i+1}] URL: {url}\nContent: {content}" 
            for i, (url, content) in enumerate(batch)
        )
        
        prompt = f"""Threat classification engine. Classify each page and extract the KEY PHRASE (max 50 chars) that is the actual threat indicator.

Context: {query}

Pages:
{content_block}

Categories: data_breach (leaked DBs, credential dumps, exposed records) | credentials (combo lists, email:pass) | malware (samples, ransomware, stealers, RATs, exploits) | market_listing (cards, accounts, services for sale) | forum_post (discussions, tutorials) | paste (raw data dumps) | other
Severity: critical (active large-scale breach, fresh creds, zero-day) | high (confirmed leaked data, working exploits) | medium (older data, partial leaks) | low (generic, tangential)

Output ONLY valid JSON array, no markdown, no explanation:
[{{"url": "...", "category": "...", "severity": "...", "reason": "short reason max 30 chars", "evidence": "key threat phrase from page max 50 chars"}}]

JSON:"""
        
        parsed = _call_llm_json_retry(prompt, "classify")
        if parsed:
            try:
                for item in parsed:
                    all_classified[item["url"]] = {
                        "category": item.get("category", "other"),
                        "severity": item.get("severity", "low"),
                        "reason": item.get("reason", "")[:60],
                        "evidence": item.get("evidence", "")[:80],
                    }
            except (KeyError, TypeError) as e:
                print(f"  [!] Failed to process batch {batch_num}: {str(e)[:60]}")
                for url, _ in batch:
                    if url not in all_classified:
                        all_classified[url] = {"category": "other", "severity": "medium", "reason": "parse failed", "evidence": ""}
        else:
            # LLM unavailable — fallback for this batch
            for url, _ in batch:
                all_classified[url] = {"category": "other", "severity": "medium", "reason": "LLM unavailable", "evidence": ""}
    
    return all_classified


# ============================================================
# STAGE 4: INTELLIGENCE SUMMARY
# ============================================================

def generate_summary(query: str, scraped_data: dict, classifications: dict, regex_iocs: dict = None, actor_contacts: dict = None) -> str:
    """
    stage 4: generate structured threat intelligence report with evidence.
    includes threat actor contacts and pre-extracted IOCs.
    """
    if not scraped_data:
        return "No data available for summary generation."
    
    # clean content for summary
    try:
        from content_cleaner import clean_content, extract_meaningful_section
        use_cleaner = True
    except ImportError:
        use_cleaner = False
    
    # build compact entries with cleaned content and classification data
    # de-duplicate mirror pages (same page title from different .onion mirrors)
    seen_titles = set()
    entries = []
    for i, (url, content) in enumerate(scraped_data.items(), 1):
        if content.startswith("[ERROR"):
            continue
        
        # skip navigation/meta pages that snuck through
        skip_suffixes = ['/whats-new', '/whats-new/posts', '/members', '/rules']
        if any(url.rstrip('/').endswith(s) for s in skip_suffixes):
            continue
        
        cls = classifications.get(url, {})
        cat = cls.get("category", "unknown")
        sev = cls.get("severity", "unknown")
        evidence = cls.get("evidence", "N/A")
        
        if use_cleaner:
            display_content = extract_meaningful_section(clean_content(content), max_chars=400)
        else:
            display_content = content[:400]
        
        # de-dup by first 80 chars of cleaned content (catches mirror sites)
        content_sig = display_content[:80].strip().lower()
        if content_sig in seen_titles:
            continue
        seen_titles.add(content_sig)
        
        entries.append(f"[{i}] URL: {url}\nClassification: {cat} | Severity: {sev}\nEvidence: {evidence}\nContent Preview: {display_content}")
    
    if not entries:
        return "No valid content to summarize."
    
    content_block = "\n\n---\n\n".join(entries)
    
    # classification stats
    cat_counts = {}
    sev_counts = {}
    for cls in classifications.values():
        cat = cls.get("category", "other")
        sev = cls.get("severity", "low")
        cat_counts[cat] = cat_counts.get(cat, 0) + 1
        sev_counts[sev] = sev_counts.get(sev, 0) + 1
    
    threat_matrix = "Threat Distribution: " + ", ".join(f"{k}: {v}" for k, v in cat_counts.items())
    severity_matrix = "Severity Distribution: " + ", ".join(f"{k}: {v}" for k, v in sev_counts.items())
    
    # format threat actor contacts — enriched format with context
    contacts_block = ""
    if actor_contacts:
        contact_lines = ["Threat Actor Contacts (regex-extracted from pages):"]
        for url, contacts in actor_contacts.items():
            for contact_type, items in contacts.items():
                for item in (items[:3] if isinstance(items, list) else [items]):
                    if isinstance(item, dict):
                        val = item.get("value", str(item))
                        ctx = item.get("context", "")
                        ctx_short = ctx[:80] if ctx else ""
                        contact_lines.append(f"  {contact_type}: {val}")
                        if ctx_short:
                            contact_lines.append(f"    Context: {ctx_short}")
                    else:
                        contact_lines.append(f"  {contact_type}: {item}")
        contacts_block = "\n".join(contact_lines[:25])
    
    # format regex IOCs — filter out catalog noise (types with >30 items from single page)
    ioc_block = ""
    if regex_iocs:
        ioc_lines = ["Pre-extracted IOCs (regex-verified):"]
        for url, iocs in regex_iocs.items():
            for ioc_type, values in iocs.items():
                # skip noisy types (likely catalog listings)
                if len(values) > 30:
                    ioc_lines.append(f"  {ioc_type}: [{len(values)} items from catalog — omitted]")
                    continue
                for val in values[:5]:
                    ioc_lines.append(f"  {ioc_type}: {val} [from: {url[:40]}]")
        ioc_block = "\n".join(ioc_lines[:25])
    
    prompt = f"""Cyber Threat Intelligence Analyst. Produce a dark web OSINT report. ANALYZE the data — extract meaning, identify patterns, assess threats.

Investigation Query: "{query}"
{threat_matrix}
{severity_matrix}
Total Unique Sources: {len(entries)}

{contacts_block}

{ioc_block}

=== SCRAPED INTELLIGENCE DATA ===
{content_block}
=== END DATA ===

OUTPUT FORMAT — follow this EXACTLY:

## DARK WEB INTELLIGENCE BRIEF

### Query
"{query}" — state scope in 1 line.

### Executive Summary
2-3 sentences. What's the overall threat landscape for this query? Mention specific numbers (how many compromised accounts, prices, etc). State the threat level (LOW/MEDIUM/HIGH/CRITICAL).

### Threat Breakdown
| Category | Count | Severity | Key Indicator |
|---|---|---|---|
Derive categories from the CONTENT (e.g., data_breach, market_listing, hacking_tutorial, credential_sale, forum_discussion).
Do NOT just use "other" — analyze what each page actually contains.
"Key Indicator" = the single most important phrase proving this categorization (max 30 chars).

### Key Findings
3-5 numbered findings. For each:
1. **[Finding Title]** — What was found specifically (names, numbers, prices).
   - *Evidence*: Direct quote or data point from the scraped content (max 60 chars)
   - *Impact*: Why this matters for the organization (1 line)

### Threat Actors
| Handle/Contact | Platform | Offering/Activity | Context |
|---|---|---|---|
Use the "Threat Actor Contacts" data above. Identify WHO is selling/offering WHAT.
"Context" = what they were advertising near their contact info (max 40 chars).
If no contacts found, write "No threat actor contacts identified in scraped pages."

### Evidence Report
| # | Type | URL (short) | Key Finding |
|---|---|---|---|
Show ONLY the 5-8 most important pages. Skip dead links, error pages, and duplicates.
"Type" = what this page IS (e.g., "Hacking Forum", "Data Shop", "Tutorial Thread")
"Key Finding" = the SPECIFIC threat indicator from this page (max 50 chars). NOT raw HTML or boilerplate.

### IOCs (Indicators of Compromise)
| Type | Value | Source |
|---|---|---|
Use the pre-extracted IOCs. Prioritize: emails, crypto wallets, credential dumps.
SKIP domains from breach catalog listings (hundreds of .com domains = catalog noise, not IOCs).
Max 10 rows. "Source" = domain only (max 25 chars).

### Recommended Actions
3-5 specific, actionable steps based on findings. Be concrete (e.g., "Monitor Telegram handle @xyz for updates" not "Monitor dark web").

CRITICAL RULES:
- NO raw HTML/boilerplate in any output (no "JavaScript is Disabled", no "Menu Log in Register")
- Every table cell MUST be under 50 characters
- Be analytical — identify PATTERNS across sources, don't just list what each page says
- Total output under 3000 characters
- If classification data shows all "other", you MUST re-derive proper categories from the content yourself

OUTPUT:"""

    result = call_llm(prompt, "summary")
    if result:
        return result.strip()
    
    return "Summary generation failed. Raw data saved to output/scraped_data.txt."


# ============================================================
# STAGE 5: FILE THREAT VERIFICATION
# ============================================================

def verify_threat_files(query: str, file_analysis: dict) -> dict:
    """
    stage 5: analyze downloaded file headers and torrent metadata to verify threats.
    returns dict of file_url -> {verdict, confidence, reason}
    """
    if not file_analysis:
        return {}
    
    # build compact entries for each file
    entries = []
    for i, (url, analysis) in enumerate(file_analysis.items(), 1):
        if not isinstance(analysis, dict):
            continue
        
        entry_lines = [f"[{i}] URL: {url[:80]}"]
        
        ftype = analysis.get('file_type', analysis.get('type', 'unknown'))
        entry_lines.append(f"  File Type: {ftype}")
        
        if 'size_bytes' in analysis and analysis['size_bytes']:
            entry_lines.append(f"  Size: {analysis['size_bytes']} bytes")
        
        if 'total_size' in analysis:
            entry_lines.append(f"  Total Size: {analysis['total_size']} bytes")
        
        if 'files' in analysis and analysis['files']:
            file_list = ', '.join(
                f"{f['path']} ({f.get('size', 0)} bytes)" 
                for f in analysis['files'][:8]
            )
            entry_lines.append(f"  Files: {file_list}")
        
        if 'header_preview' in analysis and analysis['header_preview']:
            preview = analysis['header_preview'][:800]
            entry_lines.append(f"  Header Preview:\n{preview}")
        
        if 'name' in analysis:
            entry_lines.append(f"  Name: {analysis['name']}")
        
        if 'info_hash' in analysis and analysis['info_hash']:
            entry_lines.append(f"  Torrent Hash: {analysis['info_hash']}")
        
        entries.append('\n'.join(entry_lines))
    
    if not entries:
        return {}
    
    content_block = '\n\n---\n\n'.join(entries)
    
    prompt = f"""Threat verification analyst. Examine file headers and metadata from dark web sources. You see ONLY the first 4KB header (not full content) plus torrent metadata.

Context: {query}

Files:
{content_block}

Classify each file:
- verdict: "confirmed_threat" (clearly real leaked data) | "likely_fake" (honeypot/lure) | "inconclusive" (can't determine from header) | "benign" (non-threatening)
- confidence: "high" | "medium" | "low"
- reason: brief explanation (max 100 chars)
- data_type: e.g. "credential dump", "database export", "financial records", "personal data", "source code", "unknown"

REAL threat indicators: structured data patterns (email:password, CSV with PII, SQL schemas), DB table names with user/customer/account data, large torrent file listings with data-suggestive names, breach-typical naming.
FAKE/honeypot indicators: too-perfect formatting, obviously generated data, small files claiming massive dumps, known honeypot patterns, generic/template content.

Output ONLY valid JSON array, no markdown, no explanation:
[{{"url": "...", "verdict": "...", "confidence": "...", "reason": "...", "data_type": "..."}}]

JSON:"""

    # build reverse lookup: truncated url -> full url (AI may return truncated)
    url_map = {}
    for url_full in file_analysis:
        url_map[url_full] = url_full
        url_map[url_full[:80]] = url_full

    parsed = _call_llm_json_retry(prompt, "file_analysis")
    if parsed:
        try:
            verdicts = {}
            for item in parsed:
                ai_url = item.get("url", "")
                # match truncated or full URL back to original
                full_url = url_map.get(ai_url)
                if not full_url:
                    # fuzzy match: find the original URL that starts with what AI returned
                    for orig in file_analysis:
                        if orig.startswith(ai_url) or ai_url.startswith(orig[:40]):
                            full_url = orig
                            break
                if full_url:
                    verdicts[full_url] = {
                        "verdict": item.get("verdict", "inconclusive"),
                        "confidence": item.get("confidence", "low"),
                        "reason": item.get("reason", ""),
                        "data_type": item.get("data_type", "unknown"),
                    }
            return verdicts
        except (KeyError, TypeError) as e:
            print(f"  [!] Failed to process file verification: {str(e)[:60]}")
    
    # fallback — cover ALL files
    return {u: {"verdict": "inconclusive", "confidence": "low", "reason": "verification unavailable", "data_type": "unknown"}
            for u in file_analysis}


def get_provider_info() -> dict:
    """check which providers are available and return status info"""
    info = {
        "gemini_keys": {},
        "ollama_available": _ollama_available(),
        "ollama_model": _get_ollama_model() if _ollama_available() else None,
    }
    
    for stage in ["refine", "filter", "classify", "summary"]:
        key = _get_gemini_key(stage)
        if key:
            # show first 10 and last 4 chars only
            masked = key[:10] + "..." + key[-4:]
            info["gemini_keys"][stage] = masked
        else:
            info["gemini_keys"][stage] = None
    
    return info


if __name__ == "__main__":
    print("\n[+] AI Engine — Provider Check")
    print("=" * 40)
    
    info = get_provider_info()
    
    print("\nGemini API Keys:")
    for stage, key in info["gemini_keys"].items():
        status = f"✓ {key}" if key else "✗ Not set"
        print(f"  {stage:10s} : {status}")
    
    print(f"\nOllama:")
    if info["ollama_available"]:
        print(f"  Status : ✓ Running")
        print(f"  Model  : {info['ollama_model']}")
    else:
        print(f"  Status : ✗ Not available")
    
    # quick test call
    print("\n[+] Testing LLM call (refine stage)...")
    result = call_llm("Say 'hello' in one word.", "refine")
    if result:
        print(f"  Response: {result.strip()}")
        print("  ✓ LLM working!")
    else:
        print("  ✗ No LLM available")
