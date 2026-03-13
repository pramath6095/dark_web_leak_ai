import os
import json
import time
import threading
import requests
from dotenv import load_dotenv
load_dotenv()

import warnings
warnings.filterwarnings("ignore")


# ============================================================
# PROVIDER CONFIGURATION
# ============================================================

PROVIDERS = ["gemini", "anthropic", "deepseek", "groq", "mistral", "ollama"]
STAGES = ["refine", "filter", "classify", "summary", "file_analysis"]

# active provider — set from env or overridden by dashboard
_active_provider = os.getenv("AI_PROVIDER", "gemini").strip().lower()

# provider key env var prefixes
_PROVIDER_PREFIX = {
    "gemini":    "GEMINI",
    "anthropic": "ANTHROPIC",
    "deepseek":  "DEEPSEEK",
    "groq":      "GROQ",
    "mistral":   "MISTRAL",
}

# provider model defaults
PROVIDER_MODELS = {
    "gemini":    os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
    "anthropic": os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514"),
    "deepseek":  os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
    "groq":      os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
    "mistral":   os.getenv("MISTRAL_MODEL", "mistral-large-latest"),
}

# provider API base URLs
PROVIDER_URLS = {
    "anthropic": "https://api.anthropic.com/v1/messages",
    "deepseek":  "https://api.deepseek.com/v1/chat/completions",
    "groq":      "https://api.groq.com/openai/v1/chat/completions",
    "mistral":   "https://api.mistral.ai/v1/chat/completions",
}

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

# user-selected ollama model (None = auto-pick first available)
_active_ollama_model = os.getenv("OLLAMA_MODEL", "").strip() or None

# load all provider keys: {provider: {stage: key_value}}
_PROVIDER_KEYS = {}
for _prov, _prefix in _PROVIDER_PREFIX.items():
    _PROVIDER_KEYS[_prov] = {}
    for _stage in STAGES:
        _env_name = f"{_prefix}_KEY_{_stage.upper()}"
        _val = os.getenv(_env_name, "").strip()
        if _val:
            _PROVIDER_KEYS[_prov][_stage] = _val

# legacy fallback: GEMINI_API_KEY -> gemini refine key
_gemini_legacy = os.getenv("GEMINI_API_KEY", "").strip()
if _gemini_legacy and "refine" not in _PROVIDER_KEYS.get("gemini", {}):
    _PROVIDER_KEYS.setdefault("gemini", {})["refine"] = _gemini_legacy


GEMINI_MAX_RETRIES = 3
GEMINI_RETRY_DELAYS = [2, 5, 10]

# per-stage output token caps
STAGE_MAX_TOKENS = {
    "refine":        512,
    "filter":        1024,
    "classify":      3072,
    "summary":       4096,
    "file_analysis": 3072,
    "company_check": 3072,
}

# stages that output JSON
STAGE_JSON_MODE = {"classify", "file_analysis", "company_check"}

# per-key rate limit tracking
_key_state = {}


# ============================================================
# PROVIDER MANAGEMENT
# ============================================================

def set_provider(name: str):
    """set the active AI provider (called by dashboard per-job)"""
    global _active_provider
    name = name.strip().lower()
    if name not in PROVIDERS:
        print(f"  [!] Unknown provider '{name}', falling back to gemini")
        name = "gemini"
    _active_provider = name
    print(f"  [*] AI provider set to: {name}")


def get_provider() -> str:
    """get the currently active provider"""
    return _active_provider


def set_ollama_model(model_name: str):
    """set the ollama model to use (called by dashboard per-job)"""
    global _active_ollama_model
    model_name = model_name.strip() if model_name else None
    _active_ollama_model = model_name or None
    if _active_ollama_model:
        print(f"  [*] Ollama model set to: {_active_ollama_model}")


def get_ollama_model_name() -> str:
    """get the currently selected ollama model name"""
    return _active_ollama_model


def list_ollama_models() -> list:
    """list all models available in the local ollama instance"""
    try:
        r = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5)
        if r.status_code == 200:
            models = r.json().get("models", [])
            return [m.get("name", "") for m in models if m.get("name")]
    except Exception:
        pass
    return []


def _get_provider_key(provider: str, stage: str) -> str:
    """
    get the best available API key for a provider+stage.
    fallback chain: stage key -> refine key -> any other key for that provider.
    """
    keys = _PROVIDER_KEYS.get(provider, {})
    if not keys:
        return None

    # try stage-specific key first
    candidates = []
    stage_key = keys.get(stage)
    if stage_key:
        candidates.append(stage_key)

    # try refine key as fallback
    refine_key = keys.get("refine")
    if refine_key and refine_key not in candidates:
        candidates.append(refine_key)

    # try any other key
    for other_stage, other_key in keys.items():
        if other_key and other_key not in candidates:
            candidates.append(other_key)

    # return first available (not in cooldown)
    for key in candidates:
        if _is_key_available(key):
            return key

    # all in cooldown — return first anyway
    return candidates[0] if candidates else None


# ============================================================
# RATE LIMIT TRACKING
# ============================================================

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
    cooldown = min(30 * (2 ** (state["fails"] - 1)), 120)
    state["cooldown_until"] = time.time() + cooldown
    print(f"  [!] Key ...{key[-4:]} rate limited, cooldown {cooldown}s")


def _record_success(key: str):
    """reset fail count on success"""
    if key in _key_state:
        _key_state[key]["fails"] = 0


# ============================================================
# PROVIDER API CALLS
# ============================================================

def _call_gemini(prompt: str, api_key: str, stage: str = "summary", temperature: float = 0.1) -> str:
    """call gemini api with retry logic for rate limits and optional JSON mode"""
    model = PROVIDER_MODELS["gemini"]
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"

    max_tokens = STAGE_MAX_TOKENS.get(stage, 4096)
    gen_config = {
        "temperature": temperature,
        "maxOutputTokens": max_tokens,
    }
    if stage in STAGE_JSON_MODE:
        gen_config["responseMimeType"] = "application/json"

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": gen_config
    }

    for attempt in range(GEMINI_MAX_RETRIES):
        try:
            response = requests.post(url, json=payload, timeout=60)

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


def _call_anthropic(prompt: str, api_key: str, stage: str = "summary", temperature: float = 0.1) -> str:
    """call anthropic messages API"""
    url = PROVIDER_URLS["anthropic"]
    model = PROVIDER_MODELS["anthropic"]
    max_tokens = STAGE_MAX_TOKENS.get(stage, 4096)

    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": [{"role": "user", "content": prompt}],
    }

    for attempt in range(GEMINI_MAX_RETRIES):
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=90)

            if response.status_code == 429:
                _record_rate_limit(api_key)
                delay = GEMINI_RETRY_DELAYS[attempt] if attempt < len(GEMINI_RETRY_DELAYS) else 10
                print(f"  [!] Anthropic rate limited. Retrying in {delay}s... (attempt {attempt + 1}/{GEMINI_MAX_RETRIES})")
                time.sleep(delay)
                continue

            response.raise_for_status()
            _record_success(api_key)
            data = response.json()

            content = data.get("content", [])
            if content and isinstance(content, list):
                for block in content:
                    if block.get("type") == "text":
                        return block.get("text", "")
            return ""
        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code != 429:
                print(f"  [!] Anthropic API error: {e.response.status_code}")
                raise
        except Exception as e:
            print(f"  [!] Anthropic request failed: {str(e)[:80]}")
            raise

    raise Exception("Anthropic rate limit exceeded after all retries")


def _call_openai_compatible(prompt: str, api_key: str, provider: str, stage: str = "summary", temperature: float = 0.1) -> str:
    """call OpenAI-compatible API (used by DeepSeek, Groq, Mistral)"""
    url = PROVIDER_URLS[provider]
    model = PROVIDER_MODELS[provider]
    max_tokens = STAGE_MAX_TOKENS.get(stage, 4096)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    # add JSON mode for structured output stages
    if stage in STAGE_JSON_MODE:
        payload["response_format"] = {"type": "json_object"}

    for attempt in range(GEMINI_MAX_RETRIES):
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=90)

            if response.status_code == 429:
                _record_rate_limit(api_key)
                delay = GEMINI_RETRY_DELAYS[attempt] if attempt < len(GEMINI_RETRY_DELAYS) else 10
                print(f"  [!] {provider.title()} rate limited. Retrying in {delay}s... (attempt {attempt + 1}/{GEMINI_MAX_RETRIES})")
                time.sleep(delay)
                continue

            response.raise_for_status()
            _record_success(api_key)
            data = response.json()

            choices = data.get("choices", [])
            if choices:
                message = choices[0].get("message", {})
                return message.get("content", "")
            return ""
        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code != 429:
                print(f"  [!] {provider.title()} API error: {e.response.status_code}")
                raise
        except Exception as e:
            print(f"  [!] {provider.title()} request failed: {str(e)[:80]}")
            raise

    raise Exception(f"{provider.title()} rate limit exceeded after all retries")


def _call_deepseek(prompt: str, api_key: str, stage: str = "summary", temperature: float = 0.1) -> str:
    """call DeepSeek API (OpenAI-compatible)"""
    return _call_openai_compatible(prompt, api_key, "deepseek", stage, temperature)


def _call_groq(prompt: str, api_key: str, stage: str = "summary", temperature: float = 0.1) -> str:
    """call Groq API (OpenAI-compatible)"""
    return _call_openai_compatible(prompt, api_key, "groq", stage, temperature)


def _call_mistral(prompt: str, api_key: str, stage: str = "summary", temperature: float = 0.1) -> str:
    """call Mistral API (OpenAI-compatible)"""
    return _call_openai_compatible(prompt, api_key, "mistral", stage, temperature)


# provider -> call function mapping
_PROVIDER_CALL_FN = {
    "gemini":    _call_gemini,
    "anthropic": _call_anthropic,
    "deepseek":  _call_deepseek,
    "groq":      _call_groq,
    "mistral":   _call_mistral,
}


# ============================================================
# OLLAMA (LOCAL MODEL)
# ============================================================

def _ollama_available() -> bool:
    """check if ollama is running locally"""
    try:
        r = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=3)
        return r.status_code == 200 and len(r.json().get("models", [])) > 0
    except:
        return False


def _get_ollama_model() -> str:
    """get user-selected ollama model, or first available if none set"""
    if _active_ollama_model:
        return _active_ollama_model
    try:
        r = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=3)
        models = r.json().get("models", [])
        if models:
            return models[0].get("name", "llama3.2")
    except:
        pass
    return None


# lock to serialise Ollama requests (local models handle one request at a time)
_ollama_lock = threading.Lock()


def _call_ollama(prompt: str, model: str) -> str:
    """call ollama api for local model inference (serialised via lock)"""
    url = f"{OLLAMA_BASE_URL}/api/generate"

    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.1,
        }
    }

    with _ollama_lock:
        try:
            response = requests.post(url, json=payload, timeout=600)
            response.raise_for_status()
            return response.json().get("response", "")
        except Exception as e:
            print(f"  [!] Ollama request failed: {str(e)[:80]}")
            raise


# ============================================================
# UNIFIED LLM DISPATCHER
# ============================================================

def call_llm(prompt: str, stage: str, temperature: float = 0.1) -> str:
    """
    call the best available llm for a given stage.
    uses active provider, then falls back to ollama on failure.
    """
    provider = _active_provider

    # ollama path — direct
    if provider == "ollama":
        if _ollama_available():
            model = _get_ollama_model()
            if model:
                print(f"  [*] Using Ollama ({model}) for stage '{stage}'")
                try:
                    return _call_ollama(prompt, model)
                except Exception:
                    print(f"  [!] Ollama failed for stage '{stage}'")
        print(f"  [-] Ollama not available for stage '{stage}'. Skipping AI step.")
        return None

    # cloud provider path
    api_key = _get_provider_key(provider, stage)
    call_fn = _PROVIDER_CALL_FN.get(provider)

    if api_key and call_fn:
        try:
            return call_fn(prompt, api_key, stage=stage, temperature=temperature)
        except Exception:
            print(f"  [!] {provider.title()} failed for stage '{stage}', trying fallback...")

    # fallback: try ollama
    if _ollama_available():
        model = _get_ollama_model()
        if model:
            print(f"  [*] Falling back to Ollama ({model}) for stage '{stage}'")
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
    prompt = f"""You are a Dark Web Threat Intelligence Analyst. Generate search queries for dark web search engines related to the provided input.
Logic:
- If the input is a target (company/person/domain), include the target in every query.
- If the input is a threat keyword (ransomware, malware, stealer, botnet), expand it with realistic dark web context instead of forcing unrelated terms.
Rules:
- Generate exactly 5 queries, one per line.
- Each query must be 1–3 words.
- Use realistic dark web terminology (breach, leak, credentials, combolist, stealer logs, access, selling, dump, paste, panel, builder).
- Queries must represent different dark web contexts such as breach/leak, credentials, marketplace activity, malware distribution, or data dumps.
- No logical operators, numbering, quotes, or explanations.
INPUT: {query}"""

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

def filter_results(query: str, results: list, limit: int = 20) -> list:
    """
    stage 2: use llm to pick the top `limit` most relevant search results.
    results format: list of dicts with {url, title}
    """
    if not results:
        return []

    if len(results) <= limit:
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

    prompt = f"""
ROLE=You are a cyber threat intelligence ranking engine.
TASK=From the search results below, select up to {limit} results most likely to contain real breach data or leaked credentials related to the query.
QUERY={query}
RESULTS={results_block}

SCORING RULES
Step 1 — COMPANY MATCH
If the query contains a company name, assign highest priority to results
whose title or URL contains that company name.

Step 2 — BREACH KEYWORDS
Prioritize results containing breach-related terms such as:
leak, breach, database, dump, credentials, combolist,
stealer logs, hacked, exposed, data leak.

Step 3 — DARKWEB LEAK SOURCES
Prefer results likely to be leak platforms such as:
leak sites, ransomware blogs, paste sites, hacking forums.

Step 4 — IGNORE IRRELEVANT RESULTS
Never select results that appear to be:
search engines, link directories, hosting services,
login portals, generic marketplaces, porn sites,
advertisement pages, or wiki link lists.

Step 5 — RANKING
Select up to {limit} results that most strongly indicate
leaked data or breach information. If fewer than {limit}
relevant results exist, return only those relevant results.

OUTPUT RULES
Return ONLY the result numbers (from the # column).
Return them as a comma-separated list.

Example:
46,30

Do NOT include explanations or text.
OUTPUT:
"""

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
            filtered = [results[i - 1] for i in unique_indices[:limit]]
            return filtered

    # fallback: return first limit results
    print("  [!] Could not parse filter response. Using first results.")
    return results[:limit]


# ============================================================
# STAGE 2.5: COMPANY CATEGORIZATION
# ============================================================

def categorize_company_relevance(query: str, scraped_data: dict) -> dict:
    """
    stage 2.5: check scraped data for company/target name mentions.
    1. uses a single LLM call to extract the company/target name and variants from the query.
    2. does simple case-insensitive string matching against scraped content.
    categorizes each URL as 'company_specific' or 'general'.
    returns dict: {url: 'company_specific' | 'general'}
    """
    if not scraped_data:
        return {}

    # --- step 1: extract company name(s) from the query via LLM ---
    prompt = f"""Extract the company name, brand name, or specific target from this search query.
Return ONLY the names as a comma-separated list. Include common variations, abbreviations, and domain names.

Examples:
- Query: "Microsoft data breach" → Microsoft, microsoft.com, MSFT
- Query: "leaked credentials Tesla" → Tesla, tesla.com
- Query: "infosys employee data leak" → Infosys, infosys.com
- Query: "ransomware attack" → NONE
- Query: "stolen credit cards" → NONE

If the query is about a GENERAL topic (not targeting a specific company/person/org), return exactly "NONE".

Query: "{query}"
Names:"""

    import re
    result = call_llm(prompt, "company_check")
    
    company_names = []
    if result:
        cleaned = result.strip().strip('"').strip("'")
        if cleaned.upper() != "NONE" and cleaned:
            # split by comma, clean each name
            for name in cleaned.split(","):
                name = name.strip().strip('"').strip("'").strip()
                if name and len(name) > 1:
                    company_names.append(name)

    # also add the raw query words as potential matches (if short enough to be a name)
    query_words = query.strip().split()
    if len(query_words) <= 3:
        # short query is likely itself a company name
        company_names.append(query.strip())

    if not company_names:
        # no company identified — everything is general
        print(f"  [*] No specific company/target identified in query. All results marked as general.")
        return {url: "general" for url, content in scraped_data.items()
                if not content.startswith("[ERROR")}

    # deduplicate and lowercase for matching
    search_terms = list(set(name.lower() for name in company_names if len(name) > 1))
    print(f"  [*] Company/target names to match: {', '.join(company_names)}")

    # --- step 2: string match against scraped content ---
    all_categories = {}
    for url, content in scraped_data.items():
        if content.startswith("[ERROR"):
            continue

        content_lower = content.lower()
        # check if any company name variant appears in the content
        found = any(term in content_lower for term in search_terms)
        all_categories[url] = "company_specific" if found else "general"

    return all_categories



# ============================================================
# STAGE 3: THREAT CLASSIFICATION
# ============================================================

def _parse_classification_json(result: str) -> list:
    """parse classification JSON from LLM response, handling markdown fences"""
    cleaned = result.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned
        cleaned = cleaned.rsplit("```", 1)[0]
    cleaned = cleaned.strip()
    return json.loads(cleaned)


def classify_threats(query: str, scraped_data: dict, company_categories: dict = None) -> dict:
    """
    stage 3: classify scraped pages into threat categories.
    if company_categories is provided, each entry gets a 'company_relevance' field.
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

        prompt = f"""
ROLE=You are a cyber threat intelligence classification engine.
TASK=For each page below:
1. Classify the page into ONE category.
2. Assign a severity level.
3. Extract the most important threat phrase from the content.

CONTEXT=Search query: {query}
PAGES={content_block}

CATEGORY DEFINITIONS

data_breach
Leaked databases, exposed records, breach announcements.

credentials
Email:password combos, credential lists, stealer logs.

malware
Malware samples, ransomware, stealers, RATs, exploits.

market_listing
Listings selling cards, accounts, services, access.

forum_post
Discussion posts, tutorials, conversations.

paste
Raw text dumps or paste pages containing leaked data.

other
Content unrelated to cybercrime or leaks.

SEVERITY RULES

critical
Fresh or large-scale breach data, active credential dumps,
zero-day exploits, or large stealer logs.

high
Confirmed leaked data, working exploits, active malware.

medium
Older leaks, partial data, secondary discussions.

low
Generic discussion or weak relevance.

EVIDENCE EXTRACTION

Extract a SHORT phrase from the page that best proves the threat.
Examples:
"10M customer database leak"
"email:pass combo list 2025"
"ransomware builder v3"
"telegram stealer logs"

Rules:
- max 50 characters
- copy from page text if possible
- do NOT invent phrases

OUTPUT RULES

Return ONLY a valid JSON array.
Do NOT include markdown.
Do NOT include explanations.
Use the URL exactly as provided.

FORMAT

[
{{"url":"...", "category":"...", "severity":"...", "reason":"short reason max 30 chars", "evidence":"key phrase max 50 chars"}}
]

JSON:
"""

        parsed = _call_llm_json_retry(prompt, "classify")
        if parsed:
            try:
                for item in parsed:
                    url = item["url"]
                    entry = {
                        "category": item.get("category", "other"),
                        "severity": item.get("severity", "low"),
                        "reason": item.get("reason", "")[:60],
                        "evidence": item.get("evidence", "")[:80],
                    }
                    if company_categories:
                        entry["company_relevance"] = company_categories.get(url, "general")
                    all_classified[url] = entry
            except (KeyError, TypeError) as e:
                print(f"  [!] Failed to process batch {batch_num}: {str(e)[:60]}")
                for url, _ in batch:
                    if url not in all_classified:
                        entry = {"category": "other", "severity": "medium", "reason": "parse failed", "evidence": ""}
                        if company_categories:
                            entry["company_relevance"] = company_categories.get(url, "general")
                        all_classified[url] = entry
        else:
            # LLM unavailable — fallback for this batch
            for url, _ in batch:
                entry = {"category": "other", "severity": "medium", "reason": "LLM unavailable", "evidence": ""}
                if company_categories:
                    entry["company_relevance"] = company_categories.get(url, "general")
                all_classified[url] = entry

    return all_classified


# ============================================================
# STAGE 4: INTELLIGENCE SUMMARY
# ============================================================

def generate_summary(query: str, scraped_data: dict, classifications: dict, regex_iocs: dict = None, actor_contacts: dict = None, company_categories: dict = None) -> str:
    """
    stage 4: generate structured threat intelligence report with evidence.
    includes threat actor contacts and pre-extracted IOCs.
    if company_categories provided, findings are labeled as company-specific or general.
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

        # add company relevance tag
        relevance_tag = ""
        if company_categories:
            rel = company_categories.get(url, cls.get("company_relevance", "general"))
            relevance_tag = f" | Relevance: {'COMPANY-SPECIFIC' if rel == 'company_specific' else 'GENERAL'}"

        entries.append(f"[{i}] URL: {url}\nClassification: {cat} | Severity: {sev}{relevance_tag}\nEvidence: {evidence}\nContent Preview: {display_content}")

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

    # company categorization stats
    company_stats_block = ""
    if company_categories:
        cs_count = sum(1 for v in company_categories.values() if v == "company_specific")
        gen_count = sum(1 for v in company_categories.values() if v == "general")
        company_stats_block = f"\nCompany Relevance: {cs_count} company-specific, {gen_count} general"

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

    prompt = f"""You are a senior Cyber Threat Intelligence Analyst. Produce a comprehensive dark web OSINT report based on the intelligence data below. ANALYZE the data thoroughly — extract meaning, identify patterns, assess real threats, and provide actionable intelligence.

Investigation Query: "{query}"
{threat_matrix}
{severity_matrix}{company_stats_block}
Total Unique Sources: {len(entries)}

{contacts_block}

{ioc_block}

=== SCRAPED INTELLIGENCE DATA ===
{content_block}
=== END DATA ===

You MUST produce ALL of the following sections. Do NOT skip any section. Fill each with real data from the scraped content above.

OUTPUT FORMAT — follow this EXACTLY:

## DARK WEB INTELLIGENCE BRIEF

### Query
"{query}" — state the investigation scope in 1 line.

### Executive Summary
3-5 sentences. Provide a thorough overview of the threat landscape for this query. Include specific numbers where available (compromised accounts, prices, number of vendors). Mention the most critical threats found. State the overall threat level: LOW / MEDIUM / HIGH / CRITICAL with justification.

### Threat Breakdown
| Category | Count | Severity | Key Indicator |
|---|---|---|---|
Derive categories from the actual CONTENT of each page (e.g., data_breach, market_listing, hacking_service, credential_sale, ransomware, forum_discussion, carding, exploit_sale).
Do NOT just use "other" — analyze what each page actually contains and assign a specific category.
"Key Indicator" = the single most important phrase proving this categorization (max 40 chars).
Include ALL categories found — do not combine or omit.

### Key Findings — Company-Specific
List findings that are SPECIFICALLY about "{query}" (marked as COMPANY-SPECIFIC in the data above).
For each finding:
1. **[Finding Title]** — Describe what was found with specifics: names, numbers, prices, data types, volumes.
   - *Evidence*: Direct quote or data point extracted from the scraped content (max 80 chars)
   - *Source*: Which URL or page type this was found on (1 line)
   - *Impact*: Why this matters for the organization and what risk it poses (1-2 lines)
If no company-specific findings exist, write "No findings directly attributable to the target."

### Key Findings — General Dark Web
List findings from GENERAL (non-target-specific) dark web data.
For each finding:
1. **[Finding Title]** — Describe what was found with specifics.
   - *Evidence*: Direct quote or data point (max 80 chars)
   - *Source*: Which URL or page type (1 line)
   - *Impact*: Broader threat landscape relevance (1-2 lines)

### Threat Actors
| Handle/Contact | Platform | Offering/Activity | Context |
|---|---|---|---|
Use the "Threat Actor Contacts" data above. Identify WHO is selling/offering WHAT.
"Context" = what they were advertising near their contact info (max 50 chars).
Include ALL identified threat actors — do not truncate this table.
If no contacts found, write "No threat actor contacts identified in scraped pages."

### Evidence Report — Company-Specific
| # | Type | URL (short) | Key Finding | Severity |
|---|---|---|---|---|
List pages marked COMPANY-SPECIFIC. Skip dead links, error pages, and duplicates.
"Type" = what this page IS (e.g., "Hacking Forum", "Data Shop", "Leak Blog", "Tutorial Thread", "Breach DB")
"Key Finding" = the SPECIFIC threat indicator from this page (max 60 chars). NOT raw HTML.
"Severity" = critical/high/medium/low
If none, write "No company-specific evidence found."

### Evidence Report — General
| # | Type | URL (short) | Key Finding | Severity |
|---|---|---|---|---|
List pages marked GENERAL. Same column rules as above.

### IOCs (Indicators of Compromise) — Company-Specific
| Type | Value | Source | Context |
|---|---|---|---|
List IOCs extracted from COMPANY-SPECIFIC pages only.
Prioritize: emails, crypto wallets, credential dumps, onion URLs.
SKIP domains from breach catalog listings (hundreds of .com domains = catalog noise, not IOCs).
Max 10 rows. Include context for each IOC explaining its significance.
"Source" = shortened source domain (max 25 chars).
If none, write "No company-specific IOCs found."

### IOCs (Indicators of Compromise) — General
| Type | Value | Source | Context |
|---|---|---|---|
List IOCs from GENERAL (non-target-specific) dark web pages.
Same rules as above. Max 10 rows.

CRITICAL RULES:
- NO raw HTML/boilerplate in any output (no "JavaScript is Disabled", no "Menu Log in Register")
- Every table cell MUST be under 60 characters
- Be analytical — identify PATTERNS across sources, don't just list what each page says
- You MUST complete ALL sections above — do not stop early or skip sections
- Aim for 4000-5000 characters total — be thorough but avoid padding or repetition
- If classification data shows all "other", you MUST re-derive proper categories from the content yourself
- Prefer specific data over generic statements — numbers, names, prices, dates are more valuable than vague descriptions

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


# ============================================================
# PROVIDER INFO
# ============================================================

def get_provider_info() -> dict:
    """check which providers are available and return status info"""
    info = {
        "active_provider": _active_provider,
        "providers": {},
        "ollama_available": _ollama_available(),
        "ollama_model": _get_ollama_model() if _ollama_available() else None,
    }

    for provider in PROVIDERS:
        if provider == "ollama":
            info["providers"]["ollama"] = {
                "available": info["ollama_available"],
                "model": info["ollama_model"],
            }
            continue

        prov_info = {"keys": {}, "model": PROVIDER_MODELS.get(provider, "unknown")}
        keys = _PROVIDER_KEYS.get(provider, {})
        for stage in STAGES:
            key = keys.get(stage)
            if key:
                masked = key[:10] + "..." + key[-4:] if len(key) > 14 else "***"
                prov_info["keys"][stage] = masked
            else:
                prov_info["keys"][stage] = None
        prov_info["has_any_key"] = any(v is not None for v in prov_info["keys"].values())
        info["providers"][provider] = prov_info

    return info


if __name__ == "__main__":
    print("\n[+] AI Engine — Provider Check")
    print("=" * 50)

    info = get_provider_info()
    print(f"\nActive Provider: {info['active_provider']}")

    for provider, prov_data in info["providers"].items():
        print(f"\n--- {provider.upper()} ---")
        if provider == "ollama":
            status = "✓ Running" if prov_data["available"] else "✗ Not available"
            print(f"  Status : {status}")
            if prov_data.get("model"):
                print(f"  Model  : {prov_data['model']}")
        else:
            print(f"  Model  : {prov_data['model']}")
            has_key = prov_data.get("has_any_key", False)
            print(f"  Keys   : {'✓ Configured' if has_key else '✗ No keys set'}")
            for stage, key in prov_data["keys"].items():
                status = f"✓ {key}" if key else "✗ Not set"
                print(f"    {stage:15s} : {status}")

    # quick test call
    print(f"\n[+] Testing LLM call ({info['active_provider']}, refine stage)...")
    result = call_llm("Say 'hello' in one word.", "refine")
    if result:
        print(f"  Response: {result.strip()}")
        print("  ✓ LLM working!")
    else:
        print("  ✗ No LLM available")
