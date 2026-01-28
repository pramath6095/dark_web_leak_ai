# Dark Web Leak Monitor

Async dark web crawler for monitoring data leaks on .onion sites.

## Features

- **Async I/O**: High-performance crawling with `aiohttp` (5-10x faster than sync)
- **Circuit Isolation**: Each request uses a different Tor circuit via SOCKS5 auth
- **HEAD Pre-checks**: Skip dead links quickly before full scrape
- **Browser Fingerprinting**: Realistic request headers matching real browsers
- **Error Sanitization**: No internal details leaked in error messages
- **Multiple Search Engines**: Queries 5 dark web search engines simultaneously

## Changelog

**v2.0** - Async rewrite with `aiohttp`, circuit isolation, HEAD pre-checks, browser fingerprinting, error sanitization.

**v1.0** - Initial release with threaded search/scrape via Tor proxy.

---

## How It Works

### Tor Connection
The application connects to the dark web through **Tor** (The Onion Router):
- Tor runs as a SOCKS5 proxy on `127.0.0.1:9050`
- All HTTP requests are routed through this proxy
- **Circuit isolation** via SOCKS5 authentication ensures each request uses a different Tor circuit

```python
# Circuit isolation via unique credentials per request
connector = ProxyConnector.from_url(
    f"socks5://stream{stream_id}:x@127.0.0.1:9050",
    rdns=True  # Resolve DNS through Tor
)
```

### Security Features

| Feature | Description |
|---------|-------------|
| Circuit Isolation | Different Tor exit IP per request |
| Browser Profiles | Full headers (Accept, Accept-Language, Sec-Ch-Ua) |
| Error Sanitization | Generic messages, no internal paths exposed |
| DNS over Tor | `rdns=True` prevents DNS leaks |

### Credentials Needed
**NONE!** This project requires:
- ❌ No API keys
- ❌ No login credentials
- ❌ No paid services
- ✅ Only Tor running locally (free and open source)

---

## Command Line Options

```
usage: main.py [-h] [-t N] [-l N] [query]

Dark Web Leak Monitor - Search and scrape .onion sites

positional arguments:
  query              Search query (interactive prompt if not provided)

options:
  -h, --help         show this help message and exit
  -t N, --threads N  Number of concurrent tasks (default: 3)
  -l N, --limit N    Maximum number of URLs to scrape (default: 10)
```

### Examples
```bash
python main.py "data breach"              # Default 3 concurrent tasks
python main.py "leaked passwords" -t 5    # 5 concurrent tasks
python main.py -t 10 -l 20 "credentials"  # 10 tasks, scrape 20 URLs
```

---

## Running the Project

### Option 1: Docker (Recommended)

```bash
# Build
docker build -t dark_web_leak .

# Run
docker run --rm -it dark_web_leak "data breach"
docker run --rm -it dark_web_leak -t 5 "leaked passwords"

# Copy results
docker run --name dwl dark_web_leak "query"
docker cp dwl:/app/results.txt .
docker cp dwl:/app/scraped_data.txt .
docker rm dwl
```

### Option 2: Native (Windows/Linux/Mac)

```bash
# 1. Install Tor
# Windows: winget install TorProject.TorBrowser
# Linux: sudo apt install tor
# Mac: brew install tor

# 2. Start Tor
tor &  # or open Tor Browser

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run
python main.py "data breach"
python main.py -t 5 -l 15 "credentials"
```

---

## Output Files

| File | Content |
|------|---------|
| `results.txt` | One URL per line |
| `scraped_data.txt` | Scraped content organized by URL |

---

## Project Structure

```
aidarkleak/
├── main.py          # Entry point with CLI (argparse)
├── search.py        # Async search module (aiohttp + circuit isolation)
├── scrape.py        # Async scrape module (HEAD checks + fingerprinting)
├── requirements.txt # Python dependencies
├── Dockerfile       # Docker configuration
├── entrypoint.sh    # Docker entrypoint (starts Tor)
└── README.md        # This file
```

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                    YOUR MACHINE                      │
│                                                      │
│  ┌──────────┐     ┌──────────┐     ┌──────────┐    │
│  │  main.py │────▶│search.py │────▶│scrape.py │    │
│  │ (argparse)│    │ (async)  │     │ (async)  │    │
│  └──────────┘     └────┬─────┘     └────┬─────┘    │
│                        │                 │          │
│            ┌───────────┴─────────────────┘          │
│            │  (Concurrent async tasks with          │
│            │   per-request circuit isolation)       │
│            ▼                                        │
│   ┌────────────────────────────────┐                │
│   │   Tor Proxy (port 9050)        │                │
│   │  ┌────────┐ ┌────────┐         │                │
│   │  │Circuit1│ │Circuit2│ ...     │                │
│   │  └────────┘ └────────┘         │                │
│   └────────────┬───────────────────┘                │
│                │                                    │
└────────────────┼────────────────────────────────────┘
                 │
                 ▼
        ┌─────────────────┐
        │   TOR NETWORK   │
        │  (Anonymous)    │
        └────────┬────────┘
                 │
                 ▼
        ┌─────────────────┐
        │   DARK WEB      │
        │ (.onion sites)  │
        └─────────────────┘
```

## Dependencies

```
requests
pysocks
beautifulsoup4
urllib3
aiohttp
aiohttp-socks
```
