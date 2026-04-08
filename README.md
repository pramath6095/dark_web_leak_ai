# AI Dark Leak

AI-powered dark web leak monitoring tool. Searches `.onion` search engines, scrapes content, extracts IOCs, classifies threats, analyzes downloadable files, and generates intelligence summaries — all routed through Tor.

---

## Table of Contents

- [Features](#features)
- [Architecture](#architecture)
- [Prerequisites](#prerequisites)
- [Step-by-Step Setup](#step-by-step-setup)
  - [Option A: Local Setup (Windows / macOS / Linux)](#option-a-local-setup)
  - [Option B: Docker Setup](#option-b-docker-setup)
- [Running the Tool](#running-the-tool)
  - [CLI Mode](#cli-mode)
  - [Web Dashboard](#web-dashboard)
- [Configuration](#configuration)
  - [AI Provider Setup](#ai-provider-setup)
  - [Tor Configuration](#tor-configuration)
  - [Forum Authentication](#forum-authentication)
  - [Environment Variables Reference](#environment-variables-reference)
- [Pipeline Stages](#pipeline-stages)
- [Output Files](#output-files)
- [CLI Options](#cli-options)
- [Dashboard Features](#dashboard-features)
- [Project Structure](#project-structure)
- [Troubleshooting](#troubleshooting)
- [Security Notes](#security-notes)
- [License](#license)

---

## Features

### Search & Discovery
- **Multi-engine search** — queries 18 dark web search engines simultaneously
- **AI query refinement** — generates optimized OSINT keywords from your search term
- **Smart filtering** — AI ranks and filters results by relevance
- **Browser fingerprinting** — rotates user agents to avoid detection

### Content Extraction
- **Async scraping** — concurrent content retrieval through Tor
- **Tor circuit isolation** — per-request circuit rotation for anonymity
- **HEAD pre-checks** — detects dead links before full scrapes
- **Pagination support** — follows multiple pages per URL
- **Login wall detection** — automatically detects pages requiring authentication

### AI Analysis
- **Company categorization** — identifies company-specific vs general threats
- **Threat classification** — categorizes pages (data breach, credentials, malware, etc.) with severity levels
- **Intelligence summary** — generates incident response briefs with all findings
- **Multi-provider support** — Gemini, Anthropic, DeepSeek, Groq, Mistral, and Ollama (local)

### File Analysis
- **Downloadable file detection** — scans threat pages for downloadable files
- **Header sampling** — extracts 4KB headers via HTTP Range requests (never downloads full files)
- **Torrent parsing** — extracts metadata from .torrent files
- **AI verification** — determines if files are real threats, fakes, or inconclusive

### IOC Extraction
- **Regex extraction** — extracts emails, IPs, domains, hashes, crypto wallets
- **Threat actor contacts** — extracts contact info (Telegram, ICQ, email, etc.) from scraped pages

### Forum Authentication
- **Credential storage** — stores and manages forum credentials locally
- **Auto-login** — automatically authenticates when encountering login walls
- **Auto-registration** — creates new accounts when credentials aren't stored
- **Captcha solving** — integrates with 2captcha/anti-captcha services
- **Forum detection** — identifies XenForo, MyBB, phpBB, SMF, Discourse

### Web Dashboard
- **Visual interface** — Flask-based web UI for running scans
- **Automation** — scheduled scans with configurable intervals
- **Webhook alerts** — Discord/Slack notifications for new threats
- **Alerts history** — tracks company-specific findings across scans
- **Real-time status** — live pipeline progress with stage timeline and log streaming

---

## Architecture

```
┌─────────────┐    ┌──────────────┐    ┌──────────────┐
│   User CLI  │    │  Dashboard   │    │  Automation  │
│  (main.py)  │    │ (dashboard.py│    │  Scheduler   │
└──────┬──────┘    └──────┬───────┘    └──────┬───────┘
       │                  │                   │
       └──────────┬───────┴───────────────────┘
                  │
       ┌──────────▼──────────┐
       │   Pipeline Engine   │
       ├─────────────────────┤
       │ 1. Query Refinement │◄── ai_engine.py
       │ 2. Dark Web Search  │◄── search.py (18 engines)
       │ 3. Result Filtering │◄── ai_engine.py
       │ 4. Content Scraping │◄── scrape.py + forum_auth.py
       │ 5. IOC Extraction   │◄── ioc_extractor.py
       │ 6. Classification   │◄── ai_engine.py
       │ 7. File Analysis    │◄── file_analyzer.py
       │ 8. Summary          │◄── ai_engine.py
       └──────────┬──────────┘
                  │
          ┌───────▼───────┐
          │   Tor Proxy   │
          │  (SOCKS5)     │
          │ Port 9150/9050│
          └───────────────┘
```

---

## Prerequisites

| Requirement | Purpose | Notes |
|---|---|---|
| **Python 3.8+** | Runtime | 3.11+ recommended |
| **Tor** | Anonymized traffic | Tor Browser (port 9150) or Tor daemon (port 9050) |
| **AI Provider** | Intelligence analysis | Ollama (free, local) or cloud API keys |
| **Git** | Clone repository | Optional, can download ZIP |

---

## Step-by-Step Setup

### Option A: Local Setup

#### Step 1 — Clone the Repository

```bash
git clone https://github.com/pramath6095/dark_web_leak_ai.git
cd dark_web_leak_ai
```

Or download and extract the ZIP archive manually.

#### Step 2 — Create a Python Virtual Environment (Recommended)

**Windows (PowerShell):**
```powershell
python -m venv venv
.\venv\Scripts\Activate
```

**macOS / Linux:**
```bash
python3 -m venv venv
source venv/bin/activate
```

#### Step 3 — Install Python Dependencies

```bash
pip install -r requirements.txt
```

This installs:
- `requests`, `pysocks` — HTTP requests through Tor SOCKS proxy
- `aiohttp`, `aiohttp-socks` — async HTTP for concurrent scraping
- `beautifulsoup4` — HTML content parsing
- `python-dotenv` — environment variable management
- `bencodepy` — torrent file metadata parsing
- `flask` — web dashboard server
- `2captcha-python` — captcha solving integration

#### Step 4 — Install and Start Tor

**Option 1: Tor Browser (easiest)**
1. Download Tor Browser from https://www.torproject.org
2. Install and launch Tor Browser
3. Keep Tor Browser running while you use this tool
4. Tor Browser exposes SOCKS5 proxy on port **9150**

**Option 2: Tor Daemon (headless)**

*Windows:*
```powershell
# Install via Chocolatey
choco install tor
# Start the service
tor --service install
net start tor
```

*macOS:*
```bash
brew install tor
brew services start tor
```

*Linux (Debian/Ubuntu):*
```bash
sudo apt install tor
sudo systemctl start tor
sudo systemctl enable tor
```

The Tor daemon exposes SOCKS5 proxy on port **9050**.

#### Step 5 — Configure Environment Variables

```bash
cp .env.example .env
```

Edit `.env` with your preferred text editor:

```ini
# Set Tor proxy port (9150 for Tor Browser, 9050 for Tor daemon)
TOR_PROXY_HOST=127.0.0.1
TOR_PROXY_PORT=9150

# Choose your AI provider
AI_PROVIDER=ollama    # Options: ollama, gemini, anthropic, deepseek, groq, mistral
```

See [AI Provider Setup](#ai-provider-setup) for detailed provider configuration.

#### Step 6 — Set Up an AI Provider

**Option A: Ollama (Free, Local — Recommended for Getting Started)**
1. Install Ollama from https://ollama.ai
2. Pull a model (we recommend `deepseek-v3.1:671b-cloud` as it works best):
   ```bash
   ollama pull deepseek-v3.1:671b-cloud
   ```
3. Ollama runs automatically on `http://localhost:11434`
4. Set in `.env`:
   ```ini
   AI_PROVIDER=ollama
   OLLAMA_MODEL=deepseek-v3.1:671b-cloud
   ```

**Option B: Cloud Provider (Gemini, Anthropic, etc.)**
1. Get an API key from your provider
2. Add it to `.env`:
   ```ini
   AI_PROVIDER=gemini
   GEMINI_KEY_REFINE=your-api-key-here
   ```
   The `REFINE` key is used as a fallback for all stages. For distributed rate limiting, you can add separate keys per stage (see [Environment Variables Reference](#environment-variables-reference)).

#### Step 7 — Verify Setup

```bash
# Check Tor connectivity
python main.py --check-engines

# Test the AI engine
python ai_engine.py
```

If `--check-engines` shows some engines as alive, Tor is working. If the AI engine test shows a response, your AI provider is configured correctly.

#### Step 8 — Run Your First Scan

```bash
python dashboard.py
```

Then open **http://localhost:5000** in your browser to use the dashboard.

---

### Option B: Docker Setup

Docker includes Tor pre-configured (no separate Tor installation needed).

#### Step 1 — Clone and Configure

```bash
git clone https://github.com/pramath6095/dark_web_leak_ai.git
cd dark_web_leak_ai
cp .env.example .env
# Edit .env and add your AI provider API keys
```

#### Step 2 — Build and Run

```bash
# Run the web dashboard
docker compose run --rm -p 5000:5000 aidarkleak python dashboard.py
```

Then open **http://localhost:5000** in your browser to use the dashboard.

Output files are automatically saved to `./output/` on your host via Docker volume mount.

> **Note:** The Docker image uses Tor daemon (port 9050) automatically. You do not need to change `TOR_PROXY_PORT`.

---

## Running the Tool

The easiest and recommended way to run AI Dark Leak is through the web dashboard.

```bash
python dashboard.py
```

Then open **http://localhost:5000** in your browser.

The dashboard provides:
- **Run Query** — configure and launch scans via the web UI
- **Automation Settings** — schedule recurring scans with configurable intervals
- **Recent Alerts** — view company-specific threat alerts across scans
- **Forum Accounts** — manage stored forum authentication credentials
- **Login Walls** — track detected login walls and authentication status
- **Job Status** — live pipeline progress with stage timeline and log streaming
- **Output Reports** — view and download generated reports (Summary, IOCs, File Analysis, etc.)

---

## Configuration

### AI Provider Setup

| Provider | Key format | Free tier | Notes |
|---|---|---|---|
| **Ollama** | No key needed | ✅ Unlimited | Local model, install from ollama.ai |
| **Gemini** | `GEMINI_KEY_*` | ✅ Yes | Google AI Studio, fast & capable |
| **Anthropic** | `ANTHROPIC_KEY_*` | ❌ Paid | claude-sonnet-4-20250514 |
| **DeepSeek** | `DEEPSEEK_KEY_*` | ✅ Low-cost | deepseek-chat |
| **Groq** | `GROQ_KEY_*` | ✅ Yes | llama-3.3-70b-versatile, very fast |
| **Mistral** | `MISTRAL_KEY_*` | ✅ Yes | mistral-large-latest |

**Per-stage keys:** Each provider supports separate API keys per pipeline stage (`REFINE`, `FILTER`, `CLASSIFY`, `SUMMARY`, `FILE_ANALYSIS`). This distributes rate limits across accounts. If only one key is provided (e.g., `GEMINI_KEY_REFINE`), it is used as the fallback for all stages.

### Tor Configuration

| Setting | Tor Browser | Tor Daemon | Docker |
|---|---|---|---|
| `TOR_PROXY_HOST` | `127.0.0.1` | `127.0.0.1` | `127.0.0.1` |
| `TOR_PROXY_PORT` | `9150` | `9050` | `9050` (auto-set) |

### Forum Authentication

The scraper automatically detects login walls on dark web forums. You can configure authentication in two ways:

1. **Manual credentials** — Add via the dashboard (Forum Accounts section) or in `output/forum_accounts.json`
2. **Auto-registration** — Set `FORUM_AUTO_REGISTER=true` in `.env` to automatically create accounts

For CAPTCHA-protected forums, configure a solving service:
```ini
CAPTCHA_API_KEY=your-2captcha-key
CAPTCHA_SERVICE=2captcha    # or anticaptcha
```

### Environment Variables Reference

#### AI Provider Selection

| Variable | Required | Default | Description |
|---|---|---|---|
| `AI_PROVIDER` | No | `ollama` | Active provider: `gemini`, `anthropic`, `deepseek`, `groq`, `mistral`, `ollama` |
| `OLLAMA_BASE_URL` | No | `http://localhost:11434` | Ollama server URL |
| `OLLAMA_MODEL` | No | Auto-detect | Specific Ollama model to use |

#### API Keys (per-provider, per-stage)

| Variable pattern | Provider | Stages |
|---|---|---|
| `GEMINI_KEY_{STAGE}` | Gemini | `REFINE`, `FILTER`, `CLASSIFY`, `SUMMARY`, `FILE_ANALYSIS` |
| `ANTHROPIC_KEY_{STAGE}` | Anthropic | Same stages |
| `DEEPSEEK_KEY_{STAGE}` | DeepSeek | Same stages |
| `GROQ_KEY_{STAGE}` | Groq | Same stages |
| `MISTRAL_KEY_{STAGE}` | Mistral | Same stages |

#### Tor Configuration

| Variable | Default | Description |
|---|---|---|
| `TOR_PROXY_HOST` | `127.0.0.1` | Tor SOCKS proxy host |
| `TOR_PROXY_PORT` | `9150` | Tor SOCKS proxy port |

#### Forum Authentication

| Variable | Default | Description |
|---|---|---|
| `FORUM_ACCOUNTS_FILE` | `output/forum_accounts.json` | Path to stored credentials |
| `FORUM_AUTO_REGISTER` | `true` | Auto-register on new forums |
| `CAPTCHA_API_KEY` | — | 2captcha or anti-captcha API key |
| `CAPTCHA_SERVICE` | `2captcha` | Captcha service: `2captcha` or `anticaptcha` |

#### Model Overrides

| Variable | Default |
|---|---|
| `GEMINI_MODEL` | `gemini-2.5-flash` |
| `ANTHROPIC_MODEL` | `claude-sonnet-4-20250514` |
| `DEEPSEEK_MODEL` | `deepseek-chat` |
| `GROQ_MODEL` | `llama-3.3-70b-versatile` |
| `MISTRAL_MODEL` | `mistral-large-latest` |

---

## Pipeline Stages

```
Step 1: AI Query Refinement      → Generates 5 OSINT-optimized search keywords
Step 2: Dark Web Search          → Searches up to 18 .onion engines simultaneously
Step 3: AI Result Filtering      → Ranks and selects the most relevant results
Step 4: Content Scraping         → Scrapes pages through Tor with circuit isolation
  4.5:  IOC Auto-Extraction      → Regex-based IOC extraction (emails, IPs, hashes, wallets)
  4.7:  Contact Extraction       → Extracts threat actor contact info (Telegram, ICQ, etc.)
Step 5: Company Categorization   → Classifies pages as company-specific vs general
Step 6: AI Threat Classification → Categorizes threats + assigns severity levels
  6.5:  File Header Analysis     → Samples 4KB headers from downloadable files, parses torrents
  6.7:  AI File Verification     → Determines if files are real threats, fakes, or inconclusive
Step 7: AI Intelligence Summary  → Generates a comprehensive incident response brief
```

---

## Output Files

All output files are saved to the `output/` directory:

| File | Contents |
|---|---|
| `output/results.txt` | Found `.onion` URLs from all search engines |
| `output/scraped_data.txt` | Scraped text content per URL |
| `output/iocs.txt` | Extracted IOCs + threat actor contacts |
| `output/file_analysis.txt` | File type detection + AI threat verdicts |
| `output/summary.txt` | AI-generated intelligence summary |
| `output/alerts.json` | Alert history from dashboard scans |
| `output/automation_settings.json` | Persisted automation configuration |
| `output/forum_accounts.json` | Stored forum credentials |

---

## CLI Options

| Flag | Description | Default |
|---|---|---|
| `-t N` | Concurrent tasks / threads | `3` |
| `-e N` | Number of search engines to use | All available |
| `-l N` | Max URLs to scrape | `10` (CLI prompts, dashboard configurable) |
| `-d {1,2}` | Scrape depth: `1` = landing page only, `2` = follow sublinks | `2` |
| `-p N` | Max pages to follow per URL via pagination | `1` |
| `--no-ai` | Skip all AI stages (search + scrape only) | Off |
| `--no-download` | Skip file header analysis | Off |
| `--dashboard` | Launch web dashboard instead of CLI | Off |
| `--check-engines` | Test which search engines are alive and exit | Off |

---

## Dashboard Features

### Run Query
Configure and launch scans with parameters: engines, scrape limit, threads, depth, AI provider, and Ollama model. Supports real-time abort of running pipelines.

### Automation
Schedule recurring scans at configurable intervals (e.g., every 6 hours). Uses the last manual query. Supports Discord/Slack webhook alerts.

### Recent Alerts
Displays company-specific threat alerts generated from scan results. Alerts are deduplicated across scans and displayed with severity badges, evidence, and category tags.

### Forum Accounts & Login Walls
- **Left panel:** Manage stored credentials for dark web forums
- **Right panel:** View detected login walls with authentication status

### Job Status
Live pipeline progress with:
- Stage timeline showing elapsed time per stage
- Live log panel streaming CLI output in real-time
- Pipeline duration timer and Tor error counter with breakdown

### Output Reports
Browse, view, and download all generated report files. Summary and file analysis reports render with full markdown formatting.

---

## Project Structure

```
main.py              — Entry point, CLI argument parsing, pipeline orchestration
search.py            — Async multi-engine dark web search (18 engines)
scrape.py            — Content scraping with Tor circuit isolation + login wall detection
ai_engine.py         — All AI stages: refine, filter, classify, verify, summarize
ioc_extractor.py     — Regex IOC extraction (emails, IPs, hashes, wallets, contacts)
file_analyzer.py     — File link extraction, header sampling, torrent parsing
forum_auth.py        — Forum authentication, login, registration, captcha solving
content_cleaner.py   — Cleans scraped HTML for better AI analysis
dashboard.py         — Flask web dashboard with automation and alerts
Dockerfile           — Container image with Tor daemon pre-configured
docker-compose.yml   — One-command startup with volume mounts
entrypoint.sh        — Waits for Tor readiness before running the script
.env.example         — Configuration template with all environment variables
requirements.txt     — Python package dependencies
```

---

## Troubleshooting

### Tor Connection Issues

| Symptom | Cause | Fix |
|---|---|---|
| `No results found` | Tor not running | Start Tor Browser or Tor daemon |
| `Connection refused` | Wrong proxy port | Check `TOR_PROXY_PORT` in `.env` (9150 for Tor Browser, 9050 for daemon) |
| Many `[ERROR: connection timeout]` | Tor circuit congestion | Normal for .onion sites; increase threads (`-t 5`) for parallel retries |
| All engines dead | Tor is connected but engines are down | Run `--check-engines` to identify available engines |

### AI Provider Issues

| Symptom | Cause | Fix |
|---|---|---|
| `No LLM available` | Provider not configured | Add API key to `.env` or install Ollama |
| `Rate limited (429)` | Too many API calls | Add separate keys per stage to distribute rate limits |
| `Ollama not available` | Ollama server not running | Start with `ollama serve` or check `OLLAMA_BASE_URL` |
| JSON parse failures | Model output inconsistency | Automatic retry with lower temperature; try a different model |

### Common Issues

| Symptom | Fix |
|---|---|
| `ModuleNotFoundError` | Run `pip install -r requirements.txt` |
| Empty `output/` folder | Ensure Tor is running and search engines are reachable |
| Dashboard won't start | Check port 5000 is not in use; try `python dashboard.py` directly |
| Forum login fails | Add credentials manually via dashboard; check CAPTCHA service configuration |

---

## Security Notes

- All traffic routed through Tor with per-request circuit isolation
- HEAD pre-checks detect dead links before full scrapes
- File analysis downloads only 4KB headers — never full files
- Error messages sanitized to prevent leaking internals
- Rate limiting between searches and API calls
- `.env` with API keys is gitignored
- Forum credentials stored locally in `output/forum_accounts.json` (gitignored)

---

## Dependencies

| Package | Purpose |
|---|---|
| `requests` + `pysocks` | HTTP requests through Tor SOCKS proxy |
| `aiohttp` + `aiohttp-socks` | Async HTTP for concurrent scraping |
| `beautifulsoup4` | HTML content parsing |
| `python-dotenv` | Environment variable management |
| `bencodepy` | Torrent file metadata parsing |
| `flask` | Web dashboard server |
| `2captcha-python` | Captcha solving integration |

---

## License

For educational and authorized security research purposes only.
