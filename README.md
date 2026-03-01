# AIDarkLeak

Early-detection system for data leaks on the dark web. Monitors configurable company identifiers across dark web sources and uses AI to assess whether scraped content is relevant to the monitored organization.

> **University research project** — THWS / RVCE joint programme.

---

## How It Works

```
start.py → Query Generator → Scraper → AI Analysis → results.txt
```

1. **You provide** a company name and description
2. **Query Generator** uses an LLM (Dolphin-Mistral via OpenRouter) to produce diverse dark-web search queries and detailed search strings
3. **Scraper** polls for queries, searches 17 dark-web search engines via Tor, scrapes `.onion` pages, and sends raw HTML to the analysis service in batches of 5
4. **AI Analysis** preprocesses HTML, runs rule-based pre-filtering, zero-shot classification (DeBERTa), semantic similarity (BGE-M3), and writes relevant results to `output/results.txt`
5. The system **stops automatically** when the LLM can no longer generate novel queries (quality gate)

---

## Architecture

```
aidarkleak/
├── start.py                   ← One-command launcher
├── docker-compose.yml         ← Orchestrates all 3 services
│
├── query-generator/           ← LLM-based query + search-string generation
│   ├── app/
│   │   ├── main.py            ← POST /configure, GET /queries, GET /search-strings
│   │   ├── config.py          ← OpenRouter API settings
│   │   ├── state.py           ← In-memory state (served queries, dedup)
│   │   └── generator.py       ← LLM prompts, dedup, quality gate, fallback
│   ├── Dockerfile
│   ├── requirements.txt
│   └── .env.example
│
├── scraper-service/           ← Dark-web scraping via Tor
│   ├── app/
│   │   ├── main.py            ← GET /health, POST /trigger, background polling loop
│   │   ├── config.py          ← Tor, concurrency, inter-service URLs
│   │   ├── search.py          ← 17 dark-web search engines, circuit isolation
│   │   ├── scrape.py          ← HEAD pre-check → GET scrape, raw HTML output
│   │   └── dispatcher.py      ← Batches pages (5/req) → POST /analyze
│   ├── Dockerfile             ← python:3.11-slim + Tor
│   ├── entrypoint.sh          ← Starts Tor → uvicorn
│   ├── requirements.txt
│   └── .env.example
│
├── ai-analysis-service/       ← ML-based leak detection
│   ├── app/
│   │   ├── main.py            ← POST /analyze, GET /health, writes results
│   │   ├── config.py          ← Model paths, thresholds, query service URL
│   │   ├── models.py          ← Pydantic v2 request/response schemas
│   │   ├── logger.py          ← JSON-lines structured logging
│   │   └── pipeline/
│   │       ├── preprocessor.py  ← Stage 0: Strip HTML, scripts, forms, nav
│   │       ├── prefilter.py     ← Stage 1: Unicode-normalised substring match
│   │       ├── language.py      ← Stage 2: Language detection
│   │       ├── classifier.py    ← Stage 3: Multi-chunk zero-shot DeBERTa
│   │       ├── similarity.py    ← Stage 4: BGE-M3 cosine similarity
│   │       ├── relevance.py     ← Stage 5: Threshold-based decision
│   │       └── orchestrator.py  ← Sequences stages 0–5
│   ├── tests/
│   │   └── test_analyze.py    ← Integration tests (mocked ML, raw HTML input)
│   ├── Dockerfile
│   ├── requirements.txt
│   └── .env.example
│
├── output/                    ← results.txt (analysis output)
├── logs/                      ← analysis.log (JSON-lines)
└── models/                    ← Local model weights (mounted into Docker)
```

---

## Quick Start

### Prerequisites

- **Docker** and **Docker Compose**
- **Python 3.10+** (for `start.py` only)
- **OpenRouter API key** (free tier works — [openrouter.ai](https://openrouter.ai))

### 1. Configure

Copy the example `.env` files and add your API key:

```bash
# Query Generator (required — needs OpenRouter API key)
cp query-generator/.env.example query-generator/.env
# Edit query-generator/.env and set OPENROUTER_API_KEY

# AI Analysis
cp ai-analysis-service/.env.example ai-analysis-service/.env

# Scraper
cp scraper-service/.env.example scraper-service/.env
```

### 2. Run

```bash
# Option A: Company name + description as CLI args
python start.py "Acme Corp" "Acme Corp is a technology company. Domain: acme.com. Provides cloud solutions."

# Option B: From a text file (line 1 = name, rest = description)
python start.py --file company_info.txt
```

`start.py` will:
1. Run `docker-compose up -d --build`
2. Wait for the query-generator to become healthy
3. `POST /configure` with the company info
4. Print a confirmation — the system runs autonomously from here

### 3. Results

Results are written to **`output/results.txt`** as relevant pages are detected:

```
======================================================================
[2026-03-01 14:30:15 UTC]
URL:            http://xyz123.onion/dump
Classification: credential_leak
Confidence:     0.87
Similarity:     0.92
Matched:        acme.com, @acme.com
Language:       en
Summary:        Content appears to contain data referencing acme.com, @acme.com. Classified as credential_leak.
======================================================================
```

Structured JSON logs are in **`logs/analysis.log`**.

### 4. Stop

```bash
docker-compose down
```

---

## Services Detail

### Query Generator (`:8001`)

| Endpoint | Method | Description |
|---|---|---|
| `/configure` | POST | Receives `{ company_name, description }`, generates queries + search strings via LLM |
| `/queries` | GET | Returns next batch of unsent queries. Empty list + `exhausted=true` = stop signal |
| `/search-strings` | GET | Returns detailed matching strings for the analysis service |
| `/health` | GET | Status, configured company, total/served queries, exhaustion state |

**Quality gate**: Tracks all served queries. If the LLM generates >50% duplicates in a round, stops producing queries → scraper stops.

**Fallback**: If OpenRouter is unavailable, generates basic pattern queries (`"company data breach"`, `"company leaked database"`, etc.).

### Scraper (`:8002`)

| Endpoint | Method | Description |
|---|---|---|
| `/health` | GET | Status, Tor connectivity, last poll time |
| `/trigger` | POST | Manually trigger one scrape cycle |

**Background polling loop**:
- Fetches queries from query-generator every `POLL_INTERVAL_SECONDS` (default 300)
- For each query: searches 17 dark-web engines → scrapes discovered pages → dispatches raw HTML to analysis in batches of 5
- Stops when query-generator returns `exhausted=true`

**Tor integration**: Each concurrent task uses a separate Tor circuit (`socks5://stream{id}:x@host:port`) for circuit isolation. HEAD pre-checks skip dead links before full scraping.

### AI Analysis (`:8000`)

| Endpoint | Method | Description |
|---|---|---|
| `/analyze` | POST | Batch-analyse pages. `search_strings` optional (fetched from query-generator if omitted) |
| `/health` | GET | Mode (local/API), model load status, uptime |

**Pipeline** (per page):

| Stage | Module | Description |
|---|---|---|
| 0 | `preprocessor.py` | Strip HTML tags, scripts, forms, nav, footer, ads, comments |
| 1 | `prefilter.py` | Case-insensitive, Unicode-normalised substring matching. No match → skip ML |
| 2 | `language.py` | Language detection via `langdetect` |
| 3 | `classifier.py` | Zero-shot classification (DeBERTa). Chunks long text (≤3 × 512 tokens), picks best label |
| 4 | `similarity.py` | Semantic similarity (BGE-M3 embeddings). Max cosine sim across chunks |
| 5 | `relevance.py` | Combines classification + similarity against thresholds → final `is_relevant` |

**Classification labels**: `credential_leak`, `database_dump`, `internal_document`, `general_mention`, `irrelevant`

**Dual mode**: Set `USE_LOCAL_MODELS=true` for local GPU inference, or `false` for HuggingFace Inference API.

---

## Configuration

### Key Environment Variables

#### Query Generator
| Variable | Default | Description |
|---|---|---|
| `OPENROUTER_API_KEY` | — | OpenRouter API key (required) |
| `OPENROUTER_MODEL` | `cognitivecomputations/dolphin-mistral-24b-venice-edition:free` | LLM model |
| `QUERIES_PER_BATCH` | `5` | Queries per GET /queries response |
| `MAX_GENERATION_ROUNDS` | `5` | Max LLM re-generation attempts |
| `DUPLICATE_THRESHOLD` | `0.5` | Stop when this fraction of new queries are dupes |

#### Scraper
| Variable | Default | Description |
|---|---|---|
| `TOR_PROXY_HOST` | `127.0.0.1` | Tor SOCKS5 host |
| `TOR_PROXY_PORT` | `9050` | Tor SOCKS5 port |
| `MAX_WORKERS` | `3` | Concurrent async tasks |
| `BATCH_SIZE` | `5` | Pages per POST to analysis |
| `POLL_INTERVAL_SECONDS` | `300` | Polling interval |
| `SCRAPE_LIMIT` | `20` | Max URLs to scrape per query |

#### AI Analysis
| Variable | Default | Description |
|---|---|---|
| `USE_LOCAL_MODELS` | `true` | `true` = local models, `false` = HuggingFace API |
| `SIMILARITY_THRESHOLD` | `0.75` | Min cosine similarity for relevance |
| `CLASSIFICATION_CONFIDENCE_THRESHOLD` | `0.65` | Min classification confidence |
| `HF_API_KEY` | — | HuggingFace API key (when `USE_LOCAL_MODELS=false`) |

---

## Development

### Running Tests

```bash
cd ai-analysis-service
pip install -r requirements.txt pytest
python -m pytest tests/ -v
```

### Running Services Individually

```bash
# Query Generator
cd query-generator && pip install -r requirements.txt
uvicorn app.main:app --port 8001

# AI Analysis
cd ai-analysis-service && pip install -r requirements.txt
uvicorn app.main:app --port 8000

# Scraper (requires Tor running locally)
cd scraper-service && pip install -r requirements.txt
uvicorn app.main:app --port 8002
```

---

## Dependencies

| Service | Key Dependencies |
|---|---|
| Query Generator | FastAPI, httpx, pydantic-settings |
| Scraper | FastAPI, aiohttp, aiohttp-socks, beautifulsoup4, httpx |
| AI Analysis | FastAPI, transformers, sentence-transformers, beautifulsoup4, langdetect, httpx |

---

## License

See [LICENSE](LICENSE) for details.
