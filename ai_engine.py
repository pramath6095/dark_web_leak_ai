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

def classify_threats(query: str, scraped_data: dict) -> dict:
    """
    stage 3: classify each scraped page into threat categories with severity.
    now also extracts evidence text that triggered the classification.
    returns dict of url -> {category, severity, reason, evidence}
    """
    if not scraped_data:
        return {}
    
    # build content block - 1000 chars per page for better evidence extraction
    entries = []
    for i, (url, content) in enumerate(scraped_data.items(), 1):
        if content.startswith("[ERROR"):
            continue
        truncated = content[:1000] if len(content) > 1000 else content
        entries.append(f"[{i}] URL: {url}\nContent: {truncated}")
    
    if not entries:
        return {}
    
    content_block = "\n\n".join(entries)
    
    prompt = f"""You are a Threat Classification Engine for dark web intelligence analysis.

Classify each scraped dark web page below into a threat category with a severity level.
For each page, extract the EXACT text snippet (max 100 chars) that triggered your classification.

Search Context: {query}

Scraped Pages:
{content_block}

Categories (pick one per page):
- data_breach: leaked databases, credential dumps, exposed records
- credentials: combo lists, login credentials, passwords, email:pass
- malware: malware samples, ransomware, stealers, RATs, exploits
- market_listing: items for sale (cards, accounts, services)
- forum_post: discussion threads, tutorials, announcements
- paste: paste sites with raw data dumps
- other: doesn't fit above categories

Severity:
- critical: active large-scale breach, fresh credentials, zero-day
- high: confirmed leaked data, working exploits, significant exposure
- medium: older data, partial leaks, discussion of threats
- low: generic content, tangential relevance, no actionable data

Output ONLY valid JSON array, no markdown, no explanation:
[{{"url": "...", "category": "...", "severity": "...", "reason": "short reason", "evidence": "exact text from page that triggered classification (max 100 chars)"}}]

JSON:"""

    result = call_llm(prompt, "classify")
    if result:
        try:
            cleaned = result.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned
                cleaned = cleaned.rsplit("```", 1)[0]
            cleaned = cleaned.strip()
            
            classifications = json.loads(cleaned)
            classified = {}
            for item in classifications:
                classified[item["url"]] = {
                    "category": item.get("category", "other"),
                    "severity": item.get("severity", "low"),
                    "reason": item.get("reason", ""),
                    "evidence": item.get("evidence", "")[:150],
                }
            return classified
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            print(f"  [!] Failed to parse classification JSON: {str(e)[:60]}")
    
    # fallback
    return {url: {"category": "other", "severity": "medium", "reason": "classification unavailable", "evidence": ""} 
            for url in scraped_data if not scraped_data[url].startswith("[ERROR")}


# ============================================================
# STAGE 4: INTELLIGENCE SUMMARY
# ============================================================

def generate_summary(query: str, scraped_data: dict, classifications: dict, regex_iocs: dict = None) -> str:
    """
    stage 4: generate structured threat intelligence report with evidence.
    now accepts pre-extracted regex IOCs for more accurate output.
    """
    if not scraped_data:
        return "No data available for summary generation."
    
    # build compact entries — less content since classification already captured evidence
    entries = []
    for i, (url, content) in enumerate(scraped_data.items(), 1):
        if content.startswith("[ERROR"):
            continue
        
        cls = classifications.get(url, {})
        cat = cls.get("category", "unknown")
        sev = cls.get("severity", "unknown")
        evidence = cls.get("evidence", "N/A")
        
        truncated = content[:400] if len(content) > 400 else content
        entries.append(f"[{i}] URL: {url}\nClassification: {cat} | Severity: {sev}\nEvidence: {evidence}\nContent: {truncated}")
    
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
    
    # format regex IOCs if provided
    ioc_block = ""
    if regex_iocs:
        ioc_lines = ["Pre-extracted IOCs (regex-verified):"]
        for url, iocs in regex_iocs.items():
            for ioc_type, values in iocs.items():
                for val in values[:5]:  # cap at 5 per type per URL
                    ioc_lines.append(f"  {ioc_type}: {val} [from: {url[:40]}]")
        ioc_block = "\n".join(ioc_lines[:40])  # cap total lines
    
    prompt = f"""You are a Cyber Incident Response Analyst producing an intelligence brief from dark web OSINT data.

Investigation Query: {query}
{threat_matrix}
{severity_matrix}
Total Sources Analyzed: {len(entries)}

{ioc_block}

Scraped Intelligence Data:
{content_block}

Generate a structured INCIDENT RESPONSE BRIEF. KEEP ALL OUTPUT CONCISE — avoid long paragraphs.

## INCIDENT RESPONSE BRIEF

### Investigation Query
State what was investigated (1 line).

### Executive Summary
2-3 sentence overview of key findings and threat level.

### Threat Matrix
| Category | Count | Severity |
Use classification data provided. Keep it compact.

### Evidence Report
For EACH classified page, show one row:
| # | Category | Severity | URL (shortened) | Evidence Text |
The evidence text is the exact snippet that triggered the alert. Use the "Evidence:" field from the data above.

### IOCs (Indicators of Compromise)
| IOC Type | Value | Source |
Use the pre-extracted IOCs above. Keep "Source" to domain only (max 30 chars).
If no IOCs, write "No IOCs identified."
DO NOT put long text in any table cell. Max 60 chars per cell.

### Key Findings
3-5 bullet points. Each: what was found + why it matters (1-2 lines max per finding).

### Recommended Actions
3-5 bullet points of specific next steps.

Rules:
- Be evidence-based — only report what's in the data
- Flag NSFW or illegal content without reproducing it
- DO NOT put long text dumps in table cells — keep every cell under 60 characters
- Keep total output under 3000 characters

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
