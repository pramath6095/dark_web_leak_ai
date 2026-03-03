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


def _get_gemini_key(stage: str) -> str:
    """get the api key for a specific stage, falling back to the general key"""
    key = STAGE_KEY_MAP.get(stage)
    if key and key.strip():
        return key.strip()
    if GEMINI_FALLBACK_KEY and GEMINI_FALLBACK_KEY.strip():
        return GEMINI_FALLBACK_KEY.strip()
    return None


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


def _call_gemini(prompt: str, api_key: str) -> str:
    """call gemini api with retry logic for rate limits"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={api_key}"
    
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.3,
            "maxOutputTokens": 4096,
        }
    }
    
    for attempt in range(GEMINI_MAX_RETRIES):
        try:
            response = requests.post(url, json=payload, timeout=60)
            
            # handle rate limit with retry
            if response.status_code == 429:
                delay = GEMINI_RETRY_DELAYS[attempt] if attempt < len(GEMINI_RETRY_DELAYS) else 10
                print(f"  [!] Rate limited (429). Retrying in {delay}s... (attempt {attempt + 1}/{GEMINI_MAX_RETRIES})")
                time.sleep(delay)
                continue
            
            response.raise_for_status()
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


def call_llm(prompt: str, stage: str) -> str:
    """
    call the best available llm for a given stage.
    fallback chain: stage-specific gemini key -> GEMINI_API_KEY -> ollama -> error
    """
    # try gemini first
    gemini_key = _get_gemini_key(stage)
    if gemini_key:
        try:
            return _call_gemini(prompt, gemini_key)
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


# ============================================================
# STAGE 1: QUERY REFINEMENT
# ============================================================

def refine_query(query: str) -> list:
    """
    stage 1: generate 3 generic dark web search keywords from user input.
    strips company names and specifics — those are searched separately via original query.
    returns list of 3 keyword strings.
    """
    prompt = f"""You are a Dark Web Query Specialist focused on data leak investigations.

Your task: generate exactly 3 different generic dark web search keywords from the user's input.

Rules:
1. Output ONLY 3 keywords, one per line, nothing else — no numbering, no explanation, no quotes
2. Each keyword should be 2-4 words maximum
3. Use dark web leak terminology: breach, dump, leak, cred, paste, combo, database, exposed, stolen, hack, fullz, stealer
4. REMOVE all company names, person names, and specific identifiers — keep only generic threat terms
5. Each keyword should target a different angle of the same threat
6. Focus on what would appear in dark web forum titles and paste sites

Examples:
Input: "Company ABC email data leak"
Output:
email leak dump
data breach database
credentials combo list

Input: "stolen credit cards from Bank XYZ"
Output:
credit card fullz
banking credentials dump
financial data breach

Input: "John Smith account hacked"
Output:
account credentials leak
hacked login dump
stolen account combo

User input: {query}"""

    result = call_llm(prompt, "refine")
    if result:
        # parse 3 keywords from response
        lines = [line.strip().strip('"').strip("'").strip('-').strip() 
                 for line in result.strip().split("\n") if line.strip()]
        # filter out empty and numbering artifacts
        keywords = []
        for line in lines:
            # remove leading numbers like "1." or "1)"
            import re
            cleaned = re.sub(r'^\d+[\.\)]\s*', '', line).strip()
            if cleaned and len(cleaned) > 2:
                keywords.append(cleaned)
        
        if keywords:
            return keywords[:3]  # cap at 3
    
    return [query]  # fallback to original query as single keyword


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
    
    prompt = f"""You are an OSINT Relevance Analyst specializing in dark web leak investigations.

You are given a search query and {len(results)} search results from dark web engines. Select the top 20 results most likely to contain actual leaked data, credentials, or threat intelligence relevant to the query.

Search Query: {query}

Search Results:
{results_block}

Rules:
1. Output ONLY the indices of the top 20 most relevant results as a comma-separated list
2. Prioritize results that suggest actual data leaks, credential dumps, paste sites, or forum posts with breach data
3. Deprioritize results that look like search engine pages, error pages, or generic marketplaces
4. Order from most relevant to least relevant
5. Output nothing except the comma-separated numbers

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
        
        prompt = f"""You are a Threat Classification Engine for dark web intelligence analysis.

Classify each scraped dark web page below. For each, extract the KEY PHRASE (max 50 chars) that is the actual threat indicator — not boilerplate or navigation text.

Search Context: {query}

Scraped Pages:
{content_block}

Categories (pick one per page):
- data_breach: leaked databases, credential dumps, exposed records
- credentials: combo lists, login credentials, passwords, email:pass
- malware: malware samples, ransomware, stealers, RATs, exploits
- market_listing: items for sale (cards, accounts, services, hacking)
- forum_post: discussion threads, tutorials, announcements
- paste: paste sites with raw data dumps
- other: doesn't fit above categories

Severity:
- critical: active large-scale breach, fresh credentials, zero-day
- high: confirmed leaked data, working exploits, significant exposure
- medium: older data, partial leaks, discussion of threats
- low: generic content, tangential relevance, no actionable data

Output ONLY valid JSON array, no markdown, no explanation:
[{{"url": "...", "category": "...", "severity": "...", "reason": "short reason max 30 chars", "evidence": "key threat phrase from page max 50 chars"}}]

JSON:"""
        
        result = call_llm(prompt, "classify")
        if result:
            try:
                classifications = _parse_classification_json(result)
                for item in classifications:
                    all_classified[item["url"]] = {
                        "category": item.get("category", "other"),
                        "severity": item.get("severity", "low"),
                        "reason": item.get("reason", "")[:60],
                        "evidence": item.get("evidence", "")[:80],
                    }
            except (json.JSONDecodeError, KeyError, TypeError) as e:
                print(f"  [!] Failed to parse batch {batch_num} JSON: {str(e)[:60]}")
                # fallback for this batch only
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
        contacts_block = "\n".join(contact_lines[:40])
    
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
        ioc_block = "\n".join(ioc_lines[:40])
    
    prompt = f"""You are a Cyber Threat Intelligence Analyst producing a dark web OSINT report.
Your job is to ANALYZE the data — not just regurgitate it. Extract meaning, identify patterns, and assess threats.

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

OUTPUT:

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
    
    prompt = f"""You are a Threat Verification Analyst examining file headers and metadata from dark web sources.

Investigation Context: {query}

For each file below, determine whether it represents a REAL data leak/threat or is fake/benign.
You are seeing ONLY the first 4KB header of each file (not the full content), plus torrent metadata where available.

Files to Analyze:
{content_block}

For each file, classify:
- verdict: "confirmed_threat" (clearly real leaked data), "likely_fake" (honeypot, fake, or lure), "inconclusive" (can't determine from header alone), "benign" (legitimate/non-threatening content)
- confidence: "high", "medium", or "low"
- reason: brief explanation (max 100 chars)
- data_type: what kind of data this appears to be (e.g., "credential dump", "database export", "financial records", "personal data", "source code", "unknown")

Indicators of REAL threats:
- Structured data patterns (email:password, CSV with PII columns, SQL table structures)
- Database schema references, table names with user/customer/account data
- Large file listings in torrents with data-suggestive names
- File naming conventions common in actual breaches

Indicators of FAKE/honeypot:
- Too-perfect formatting, obviously generated data
- Small files claiming to be massive dumps
- Known honeypot patterns
- Generic/template content

Output ONLY valid JSON array, no markdown, no explanation:
[{{"url": "...", "verdict": "...", "confidence": "...", "reason": "...", "data_type": "..."}}]

JSON:"""

    result = call_llm(prompt, "file_analysis")
    if result:
        try:
            cleaned = result.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned
                cleaned = cleaned.rsplit("```", 1)[0]
            cleaned = cleaned.strip()
            
            verdicts_list = json.loads(cleaned)
            verdicts = {}
            for item in verdicts_list:
                verdicts[item["url"]] = {
                    "verdict": item.get("verdict", "inconclusive"),
                    "confidence": item.get("confidence", "low"),
                    "reason": item.get("reason", ""),
                    "data_type": item.get("data_type", "unknown"),
                }
            return verdicts
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            print(f"  [!] Failed to parse file verification JSON: {str(e)[:60]}")
    
    # fallback
    return {url: {"verdict": "inconclusive", "confidence": "low", "reason": "verification unavailable", "data_type": "unknown"}
            for url in file_analysis}



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
