# Dark Web Leak Monitor

AI-based monitoring for data leaks on the dark web.

## Features

- 🚀 **Async I/O** - High-performance crawling with `aiohttp` (5-10x faster than sync)
- 🔀 **Circuit Isolation** - Each request uses a different Tor circuit via SOCKS5 auth
- ⚡ **HEAD Pre-checks** - Skip dead links quickly before full scrape
- 🎭 **Browser Fingerprinting** - Realistic request headers matching real browsers
- 🔒 **Error Sanitization** - No internal details leaked in error messages
- 🔍 **16 Search Engines** - Queries multiple dark web search engines simultaneously
- 🛡️ **VPN Support** - Optional ProtonVPN integration for extra security

## Changelog

**v2.0** - Async rewrite with `aiohttp`, circuit isolation, HEAD pre-checks, browser fingerprinting, error sanitization, advanced CLI.

**v1.0** - Initial release with threaded search/scrape via Tor proxy.

---

## Quick Start

### Prerequisites

1. **Install Tor Browser** from https://www.torproject.org/
2. **Start Tor Browser** (runs SOCKS5 proxy on port 9150)
3. **Install Python dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

### Run

```bash
python main.py "search query"
```

Or run interactively:
```bash
python main.py
```

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

## How It Works

### Tor Connection
The application connects to the dark web through **Tor** (The Onion Router):
- Tor runs as a SOCKS5 proxy on `127.0.0.1:9150`
- All HTTP requests are routed through this proxy
- **Circuit isolation** via SOCKS5 authentication ensures each request uses a different Tor circuit

```python
# Circuit isolation via unique credentials per request
connector = ProxyConnector.from_url(
    f"socks5://stream{stream_id}:x@127.0.0.1:9150",
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
| HEAD Pre-checks | Skip dead links before wasting bandwidth |

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
│   ┌────────────────────────────────────┐            │
│   │   Tor Proxy (port 9150)            │            │
│   │  ┌────────┐ ┌────────┐             │            │
│   │  │Circuit1│ │Circuit2│ ...         │            │
│   │  └────────┘ └────────┘             │            │
│   └────────────┬───────────────────────┘            │
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

---

## Project Structure

```
aidarkleak/
├── main.py           # Entry point with CLI (argparse)
├── search.py         # Async search module (aiohttp + circuit isolation)
├── scrape.py         # Async scrape module (HEAD checks + fingerprinting)
├── requirements.txt  # Python dependencies
├── .env              # Environment variables (Tor/VPN config)
├── .env.example      # Example environment file
├── Dockerfile        # Docker configuration
├── entrypoint.sh     # Docker entrypoint script
└── output/           # Output folder
    ├── results.txt       # Discovered .onion URLs
    └── scraped_data.txt  # Scraped content from URLs
```

---

## Output Files

All output files are saved to the `output/` folder:

| File | Description |
|------|-------------|
| `output/results.txt` | One .onion URL per line |
| `output/scraped_data.txt` | Scraped text content organized by URL |

---

## Configuration

Create a `.env` file (or copy from `.env.example`):

```env
# Tor SOCKS5 Proxy
TOR_PROXY_HOST=127.0.0.1
TOR_PROXY_PORT=9150

# ProtonVPN (optional)
PROTONVPN_USER=your_username
PROTONVPN_PASS=your_password
```

**Tor Ports:**
- `9150` - Tor Browser (default)
- `9050` - Tor service/daemon

---

## Running Options

### Option 1: Local (Windows/Mac/Linux)

1. Start Tor Browser
2. Run:
   ```bash
   python main.py "data breach"
   python main.py -t 5 -l 15 "credentials"
   ```

### Option 2: Docker

```bash
# Build
docker build -t aidarkleak .

# Run with query
docker run --rm -it aidarkleak "leaked passwords"
docker run --rm -it aidarkleak -t 5 "data breach"

# Copy output files
docker run --name dwl aidarkleak "data breach"
docker cp dwl:/app/output/ ./output
docker rm dwl
```

---

## Individual Modules

Run modules separately:

```bash
# Search only (saves to output/results.txt)
python search.py

# Scrape only (reads output/results.txt, saves to output/scraped_data.txt)
python scrape.py
```

---

## Useful Commands

**Check if Tor is running:**
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

---

## Requirements

- Python 3.8+
- Tor Browser or Tor service
- Internet connection

**Python packages:**
- aiohttp
- aiohttp-socks
- beautifulsoup4
- PySocks
- python-dotenv
- requests
- urllib3

---

## Security Notes

⚠️ **For maximum anonymity:**
1. Connect to ProtonVPN (or any VPN) first
2. Then start Tor Browser
3. Run this script

This creates: **You → VPN → Tor → Dark Web** (double anonymity layer)

---

## Dependencies

```
requests
pysocks
beautifulsoup4
urllib3
python-dotenv
aiohttp
aiohttp-socks
```
