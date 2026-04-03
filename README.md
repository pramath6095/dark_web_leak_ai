# AI Dark Leak

AI-powered dark web leak monitoring tool. Searches `.onion` search engines, scrapes content, extracts IOCs, classifies threats, analyzes downloadable files, and generates intelligence summaries — all through Tor.

## Features

### Search & Discovery
- **Multi-engine search** — queries 19 dark web search engines simultaneously
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
- **Multi-provider support** — Gemini, Anthropic, DeepSeek, Groq, Mistral, and Ollama

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
- **Alerts history** — tracks findings across scans
- **Real-time status** — live pipeline progress with stage timeline

## Quick Start (Docker Compose)

```bash
# 1. clone and configure
git clone https://github.com/anomalyco/ai-dark-leak.git
cd ai-dark-leak
cp .env.example .env
# edit .env and add your AI provider API keys

# 2. run with Docker
docker compose run --rm ai-dark-leak "data breach"
```

Results are saved to the `./output/` directory.

## Setup (Manual)

### Requirements
- Python 3.8+
- Tor Browser (port 9150) or Tor daemon (port 9050)

### Install
```bash
pip install -r requirements.txt
cp .env.example .env
# edit .env — add your API keys
```

### Run (CLI)
```bash
# interactive mode (prompts for query)
python main.py

# direct query
python main.py "leaked credentials"

# with options
python main.py -t 5 -l 20 -d 2 "company name"
```

### Run (Dashboard)
```bash
python main.py --dashboard
```
Then open http://localhost:5000

## CLI Options

| Flag | Description | Default |
|------|-------------|---------|
| `-t` | Concurrent tasks | 3 |
| `-e` | Number of search engines to use | all |
| `-l` | Max URLs to scrape | 10 |
| `-d` | Scrape depth (1=landing page, 2=follow sublinks) | 2 |
| `-p` | Max pages to follow per URL via pagination | 1 |
| `--no-ai` | Skip all AI stages (search + scrape only) | off |
| `--no-download` | Skip file header analysis | off |
| `--dashboard` | Launch web dashboard instead of CLI | off |
| `--check-engines` | Test which search engines are alive | off |

## Pipeline

```
Step 1: AI Query Refinement     → generates OSINT keywords
Step 2: Dark Web Search         → searches .onion engines
Step 3: AI Result Filtering     → ranks results by relevance
Step 4: Content Scraping        → scrapes pages through Tor
  4.5:  IOC Auto-Extraction    → regex-based IOC extraction
  4.7:  Contact Extraction     → extracts threat actor contacts
Step 5: Company Categorization → filters company-specific vs general
Step 6: AI Threat Classification → categorizes threats + severity
  6.5:  File Header Analysis   → samples 4KB headers, parses torrents
  6.7:  AI File Verification  → verifies threat authenticity
Step 7: AI Intelligence Summary → incident response brief
```

## Output Files

| File | Contents |
|------|----------|
| `output/results.txt` | Found `.onion` URLs |
| `output/scraped_data.txt` | Scraped text content per URL |
| `output/iocs.txt` | Extracted IOCs + threat actor contacts |
| `output/file_analysis.txt` | File type detection + AI threat verdicts |
| `output/summary.txt` | AI-generated intelligence summary |

## Project Structure

```
main.py              — entry point, CLI, pipeline orchestration
search.py           — async multi-engine dark web search
scrape.py           — content scraping with Tor circuit isolation
ai_engine.py        — AI stages (refine, filter, classify, verify, summarize)
ioc_extractor.py    — regex IOC extraction (emails, IPs, hashes, wallets)
file_analyzer.py   — file link extraction, header sampling, torrent parsing
forum_auth.py      — forum authentication, login, registration, captcha solving
content_cleaner.py — cleans scraped HTML for better AI analysis
dashboard.py       — Flask web dashboard with automation
Dockerfile          — container with Tor daemon
docker-compose.yml — one-command startup with volume mounts
entrypoint.sh       — waits for Tor, then runs the script
.env.example       — config template
```

## Environment Variables

### AI Provider Configuration

| Variable | Required | Description |
|----------|----------|-------------|
| `AI_PROVIDER` | No | Active provider: gemini, anthropic, deepseek, groq, mistral, ollama (default: ollama) |
| `OLLAMA_BASE_URL` | No | Ollama URL (default: http://localhost:11434) |
| `OLLAMA_MODEL` | No | Ollama model to use |

### API Keys (per-provider, per-stage for rate limiting)

| Variable | Provider | Description |
|----------|----------|-------------|
| `GEMINI_KEY_*` | Gemini | Keys: refine, filter, classify, summary, file_analysis |
| `ANTHROPIC_KEY_*` | Anthropic | Keys: refine, filter, classify, summary, file_analysis |
| `DEEPSEEK_KEY_*` | DeepSeek | Keys: refine, filter, classify, summary, file_analysis |
| `GROQ_KEY_*` | Groq | Keys: refine, filter, classify, summary, file_analysis |
| `MISTRAL_KEY_*` | Mistral | Keys: refine, filter, classify, summary, file_analysis |

### Tor Configuration

| Variable | Required | Description |
|----------|----------|-------------|
| `TOR_PROXY_HOST` | No | Tor SOCKS proxy host (default: 127.0.0.1) |
| `TOR_PROXY_PORT` | No | Tor SOCKS proxy port (default: 9150, Docker: 9050) |

### Forum Authentication

| Variable | Required | Description |
|----------|----------|-------------|
| `FORUM_ACCOUNTS_FILE` | No | Path to stored credentials (default: output/forum_accounts.json) |
| `FORUM_AUTO_REGISTER` | No | Auto-register new accounts (default: true) |
| `CAPTCHA_API_KEY` | No | 2captcha/anti-captcha API key |
| `CAPTCHA_SERVICE` | No | Captcha service: 2captcha (default) or anticaptcha |

### Model Configuration

| Variable | Description |
|----------|-------------|
| `GEMINI_MODEL` | Gemini model (default: gemini-2.5-flash) |
| `ANTHROPIC_MODEL` | Anthropic model (default: claude-sonnet-4-20250514) |
| `DEEPSEEK_MODEL` | DeepSeek model (default: deepseek-chat) |
| `GROQ_MODEL` | Groq model (default: llama-3.3-70b-versatile) |
| `MISTRAL_MODEL` | Mistral model (default: mistral-large-latest) |

> Using separate API keys per stage distributes rate limits across accounts.

## Dependencies

- `aiohttp` + `aiohttp-socks` — async HTTP through Tor
- `beautifulsoup4` — HTML parsing
- `python-dotenv` — environment config
- `bencodepy` — torrent file metadata parsing
- `requests` — HTTP utilities
- `flask` — web dashboard

## Security Notes

- All traffic routed through Tor with per-request circuit isolation
- HEAD pre-checks detect dead links before full scrapes
- File analysis downloads only 4KB headers — never full files
- Error messages sanitized to prevent leaking internals
- Rate limiting between searches and API calls
- `.env` with API keys is gitignored

## License

For educational and authorized security research purposes only.
