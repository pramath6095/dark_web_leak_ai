# Dark Web Leak Monitor

A high-performance dark web crawler for monitoring data leaks on .onion sites. Built with Python async I/O for speed and Tor for anonymity.

## Features

| Feature | Description |
|---------|-------------|
| 🚀 **Async I/O** | `aiohttp` for 5-10x faster crawling than synchronous requests |
| 🔀 **Circuit Isolation** | Each request uses different Tor circuit via SOCKS5 auth |
| ⚡ **HEAD Pre-checks** | Skip dead links quickly before full scrape |
| 🎭 **Browser Fingerprinting** | 4 realistic browser profiles with full headers |
| 🔒 **Error Sanitization** | Generic messages prevent internal details leakage |
| 🔍 **17 Search Engines** | Ahmia, Torch, Tor66, OnionLand, and more |
| 🐳 **Docker Ready** | Self-contained with built-in Tor service |

---

## Quick Start

### Prerequisites
- Python 3.8+
- Tor Browser (runs proxy on port 9150) OR Tor service (port 9050)

### Install & Run
```bash
# Install dependencies
pip install -r requirements.txt

# Start Tor Browser, then run:
python main.py "data breach"
```

---

## Usage

### Command Line Options
```
python main.py [-h] [-t N] [-l N] [query]

Arguments:
  query              Search query (prompts if not provided)
  -t, --threads N    Concurrent tasks (default: 3)
  -l, --limit N      Max URLs to scrape (default: 10)
  -h, --help         Show help
```

### Examples
```bash
python main.py "leaked passwords"         # Default settings
python main.py "credentials" -t 5         # 5 concurrent tasks
python main.py -t 10 -l 20 "data breach"  # 10 tasks, scrape 20 URLs
```

### Run Modules Separately
```bash
python search.py   # Search only → output/results.txt
python scrape.py   # Scrape only → output/scraped_data.txt
```

---

## Docker

Self-contained with built-in Tor service—no external setup needed.

```bash
# Build
docker build -t aidarkleak .

# Run
docker run --rm -it aidarkleak "data breach"
docker run --rm -it aidarkleak -t 5 -l 15 "credentials"

# Copy results
docker run --name dwl aidarkleak "query"
docker cp dwl:/app/output/ ./output
docker rm dwl
```

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                    YOUR MACHINE                      │
│                                                      │
│  ┌──────────┐     ┌──────────┐     ┌──────────┐    │
│  │  main.py │────▶│search.py │────▶│scrape.py │    │
│  │(argparse)│     │ (async)  │     │ (async)  │    │
│  └──────────┘     └────┬─────┘     └────┬─────┘    │
│                        │                 │          │
│            ┌───────────┴─────────────────┘          │
│            │  Concurrent async tasks with           │
│            │  per-request circuit isolation         │
│            ▼                                        │
│   ┌────────────────────────────────────┐            │
│   │   Tor SOCKS5 Proxy (9150/9050)     │            │
│   │   Circuit1 │ Circuit2 │ Circuit3   │            │
│   └────────────────────┬───────────────┘            │
└────────────────────────┼────────────────────────────┘
                         ▼
                 ┌───────────────┐
                 │  TOR NETWORK  │ → Entry → Middle → Exit
                 └───────┬───────┘
                         ▼
                 ┌───────────────┐
                 │   DARK WEB    │ (.onion sites)
                 └───────────────┘
```

### How It Works

1. **main.py** - Entry point with CLI, orchestrates search + scrape
2. **search.py** - Queries 17 dark web search engines asynchronously
   - Extracts .onion URLs from results
   - Deduplicates URLs
   - Saves to `output/results.txt`
3. **scrape.py** - Scrapes content from discovered URLs
   - HEAD pre-check skips dead links
   - Extracts text, removes scripts/styles
   - Saves to `output/scraped_data.txt`

### Circuit Isolation
Each request gets a unique Tor circuit via SOCKS5 credentials:
```python
socks5://stream{id}:x@127.0.0.1:9150
```

---

## Configuration

Create `.env` file (copy from `.env.example`):
```env
TOR_PROXY_HOST=127.0.0.1
TOR_PROXY_PORT=9150
```

| Port | Source |
|------|--------|
| 9150 | Tor Browser (default) |
| 9050 | Tor service/daemon |

---

## Project Structure

```
aidarkleak/
├── main.py           # CLI entry point (argparse)
├── search.py         # Async search (17 engines, circuit isolation)
├── scrape.py         # Async scrape (HEAD checks, content extraction)
├── requirements.txt  # Python dependencies
├── Dockerfile        # Docker config (includes Tor)
├── entrypoint.sh     # Docker entrypoint (starts Tor)
├── .env.example      # Config template
└── output/           # Results (gitignored)
    ├── results.txt
    └── scraped_data.txt
```

---

## Output

| File | Content |
|------|---------|
| `output/results.txt` | One .onion URL per line |
| `output/scraped_data.txt` | Scraped text organized by URL |

---

## Security Features

| Feature | Implementation |
|---------|----------------|
| Circuit Isolation | Different exit IP per request |
| Browser Profiles | Full headers (User-Agent, Accept, Sec-Ch-Ua) |
| Error Sanitization | No internal paths/details exposed |
| DNS over Tor | `rdns=True` prevents DNS leaks |
| HEAD Pre-checks | Skip dead links, reduce exposure |

### Maximum Anonymity
```
You → VPN (optional) → Tor → Dark Web
```

1. Connect to VPN first (ProtonVPN, etc.)
2. Start Tor Browser
3. Run this script

---

## Dependencies

```
aiohttp
aiohttp-socks
beautifulsoup4
pysocks
python-dotenv
requests
urllib3
```

---

## Troubleshooting

**Check Tor is running:**
```bash
# Windows
netstat -ano | findstr "9150"

# Linux/Mac
lsof -i :9150
```

**Test Tor connection:**
```bash
curl --socks5 127.0.0.1:9150 https://check.torproject.org/
```

**Common Issues:**
- `No results found` → Tor not running or wrong port
- `Connection timeout` → Slow Tor circuit, increase `-t` threads
- `Dead link` → Normal, .onion sites go offline frequently
