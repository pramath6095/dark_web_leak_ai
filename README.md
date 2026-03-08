# aidarkleak

AI-powered dark web leak monitoring tool. Searches `.onion` search engines, scrapes content, extracts IOCs, classifies threats, analyzes downloadable files, and generates intelligence summaries — all through Tor.

## Features

- **Multi-engine search** — queries 17 dark web search engines simultaneously
- **AI query refinement** — Gemini generates optimized OSINT keywords from your search term
- **Smart filtering** — AI ranks and filters results by relevance
- **Content scraping** — async scraping with per-request Tor circuit isolation
- **IOC extraction** — regex-based extraction of emails, IPs, domains, hashes, crypto wallets
- **Threat classification** — AI categorizes pages (data breach, credentials, malware, etc.) with severity levels
- **File analysis** — detects downloadable files, samples 4KB headers via HTTP Range requests, parses torrent metadata, and identifies file types from magic bytes
- **AI file verification** — Gemini analyzes file headers to determine if threats are real, fake, or inconclusive
- **Intelligence reports** — generates incident response briefs with all findings

## Quick Start (Docker Compose)

```bash
# 1. clone and configure
git clone https://github.com/yourusername/dark_web_leak_ai.git
cd dark_web_leak_ai
cp .env.example .env
# edit .env and add your Gemini API key

# 2. run
docker compose run --rm aidarkleak "data breach"
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
# edit .env — add your GEMINI_API_KEY and set TOR_PROXY_PORT
```

### Run
```bash
# interactive mode (prompts for query)
python main.py

# direct query
python main.py "leaked credentials"

# with options
python main.py -t 5 -l 20 -d 2 "company name"
```

## CLI Options

| Flag | Description | Default |
|------|-------------|---------|
| `-t` | Concurrent tasks | 3 |
| `-e` | Number of search engines to use | all |
| `-l` | Max URLs to scrape | 10 |
| `-d` | Scrape depth (1=landing page, 2=follow sublinks) | 1 |
| `--no-ai` | Skip all AI stages (search + scrape only) | off |
| `--no-download` | Skip file header analysis | off |

## Pipeline

```
Step 1: AI Query Refinement     → generates OSINT keywords
Step 2: Dark Web Search         → searches .onion engines
Step 3: AI Result Filtering     → ranks results by relevance
Step 4: Content Scraping        → scrapes pages through Tor
  4.5:  IOC Auto-Extraction     → regex-based IOC extraction
Step 5: AI Threat Classification → categorizes threats + severity
  5.5:  File Header Analysis    → samples 4KB headers, parses torrents
  5.7:  AI File Verification    → Gemini verifies threat authenticity
Step 6: AI Intelligence Summary → incident response brief
```

## Output Files

| File | Contents |
|------|----------|
| `output/results.txt` | Found `.onion` URLs |
| `output/scraped_data.txt` | Scraped text content per URL |
| `output/iocs.txt` | Extracted IOCs (emails, IPs, hashes, etc.) |
| `output/file_analysis.txt` | File type detection + AI threat verdicts |
| `output/summary.txt` | AI-generated intelligence summary |

## Project Structure

```
main.py            — entry point, CLI, pipeline orchestration
search.py          — async multi-engine dark web search
scrape.py          — content scraping with Tor circuit isolation
ai_engine.py       — Gemini/Ollama AI stages (refine, filter, classify, verify, summarize)
ioc_extractor.py   — regex IOC extraction (emails, IPs, hashes, wallets)
file_analyzer.py   — file link extraction, header sampling, torrent parsing
Dockerfile         — container with Tor daemon
docker-compose.yml — one-command startup with volume mounts
entrypoint.sh      — waits for Tor, then runs the script
.env.example       — config template
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GEMINI_API_KEY` | Yes | Primary Gemini API key (fallback for all stages) |
| `TOR_PROXY_HOST` | No | Tor SOCKS proxy host (default: `127.0.0.1`) |
| `TOR_PROXY_PORT` | No | Tor SOCKS proxy port (default: `9150`, Docker: `9050`) |
| `GEMINI_KEY_REFINE` | No | Separate key for query refinement stage |
| `GEMINI_KEY_FILTER` | No | Separate key for result filtering stage |
| `GEMINI_KEY_CLASSIFY` | No | Separate key for threat classification stage |
| `GEMINI_KEY_SUMMARY` | No | Separate key for summary generation stage |
| `GEMINI_KEY_FILE_ANALYSIS` | No | Separate key for file verification stage |
| `OLLAMA_BASE_URL` | No | Ollama URL for local model fallback |

> Using separate API keys per stage distributes rate limits across accounts.

## Dependencies

- `aiohttp` + `aiohttp-socks` — async HTTP through Tor
- `beautifulsoup4` — HTML parsing
- `python-dotenv` — environment config
- `bencodepy` — torrent file metadata parsing
- `requests` — HTTP utilities

## Security Notes

- All traffic routed through Tor with per-request circuit isolation
- HEAD pre-checks detect dead links before full scrapes
- File analysis downloads only 4KB headers — never full files
- Error messages sanitized to prevent leaking internals
- Rate limiting between searches and API calls
- `.env` with API keys is gitignored

## License

For educational and authorized security research purposes only.
