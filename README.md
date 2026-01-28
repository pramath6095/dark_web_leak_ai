# Dark Web Leak Monitor

AI-based monitoring for data leaks on the dark web.

## Features

- 🔍 **Search** - Searches multiple dark web search engines (.onion)
- 📄 **Scrape** - Extracts text content from discovered URLs
- 🔒 **Anonymous** - Routes all traffic through Tor network
- 🛡️ **VPN Support** - Optional ProtonVPN integration for extra security

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

## How It Works

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                              YOUR MACHINE                                     │
│                                                                               │
│  ┌─────────────────────────────────────────────────────────────────────────┐ │
│  │                         PYTHON APPLICATION                               │ │
│  │                                                                          │ │
│  │   ┌──────────┐    1.Start    ┌───────────┐   2.Scrape   ┌───────────┐   │ │
│  │   │ main.py  │──────────────▶│ search.py │─────────────▶│ scrape.py │   │ │
│  │   │ (Entry)  │               │ (Search)  │              │ (Scrape)  │   │ │
│  │   └──────────┘               └─────┬─────┘              └─────┬─────┘   │ │
│  │                                    │                          │         │ │
│  │                              3.Query│                   8.Fetch│         │ │
│  │                                    ▼                          ▼         │ │
│  │                         ┌─────────────────────────────────────┐         │ │
│  │                         │      Tor SOCKS5 Proxy               │         │ │
│  │                         │      127.0.0.1:9150                 │         │ │
│  │                         └──────────────┬──────────────────────┘         │ │
│  │                                        │                                │ │
│  └────────────────────────────────────────┼────────────────────────────────┘ │
│                                           │                                  │
│   ┌────────────────┐                      │           ┌──────────────────┐   │
│   │      .env      │                      │           │  output/         │   │
│   │ ─────────────  │                      │           │ ───────────────  │   │
│   │ TOR_PROXY_HOST │                      │           │ results.txt      │   │
│   │ TOR_PROXY_PORT │                      │           │ scraped_data.txt │   │
│   │ PROTONVPN_USER │                      │           └────────▲─────────┘   │
│   │ PROTONVPN_PASS │                      │                    │             │
│   └────────────────┘                      │          7.Save    │  9.Save     │
│                                           │          URLs      │  Data       │
│   ┌────────────────┐                      │                    │             │
│   │  ProtonVPN     │◀ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┤                    │             │
│   │  (Optional)    │        4.VPN         │                    │             │
│   └───────┬────────┘                      │                    │             │
│           │                               │                    │             │
└───────────┼───────────────────────────────┼────────────────────┼─────────────┘
            │                               │                    │
            │ 5.Encrypted                   │                    │
            ▼                               ▼                    │
┌───────────────────────────────────────────────────────────────────────────────┐
│                              TOR NETWORK                                       │
│                                                                                │
│    ┌─────────────┐      ┌─────────────┐      ┌─────────────┐                  │
│    │ Entry Relay │─────▶│Middle Relay │─────▶│ Exit Relay  │                  │
│    │   (Guard)   │      │  (Bridge)   │      │  (Exit)     │                  │
│    └─────────────┘      └─────────────┘      └──────┬──────┘                  │
│                                                      │                         │
└──────────────────────────────────────────────────────┼─────────────────────────┘
                                                       │
                                            6.Anonymous│Request
                                                       ▼
┌───────────────────────────────────────────────────────────────────────────────┐
│                               DARK WEB                                         │
│                                                                                │
│    ┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐       │
│    │  Ahmia Search    │    │  Torch Search    │    │  .onion Sites    │       │
│    │  (Search Engine) │    │  (Search Engine) │    │ (Hidden Services)│       │
│    └──────────────────┘    └──────────────────┘    └──────────────────┘       │
│                                                                                │
└────────────────────────────────────────────────────────────────────────────────┘

DATA FLOW:
═══════════════════════════════════════════════════════════════════════════════
 1. main.py starts search.py with query
 2. search.py triggers scrape.py after finding URLs
 3. search.py sends query through Tor proxy
 4. (Optional) Traffic routes through ProtonVPN first
 5. VPN encrypts and forwards to Tor network
 6. Tor anonymizes request through 3 relays → Dark Web
 7. search.py saves discovered .onion URLs to output/results.txt
 8. scrape.py fetches content from each URL through Tor
 9. scrape.py saves scraped content to output/scraped_data.txt
═══════════════════════════════════════════════════════════════════════════════
```

Traffic flow: **You → ProtonVPN (optional) → Tor → Dark Web**

---

## Project Structure

```
aidarkleak/
├── main.py           # Entry point - runs search + scrape
├── search.py         # Dark web search module
├── scrape.py         # Content scraping module
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
   ```

### Option 2: Docker

```bash
# Build
docker build -t aidarkleak .

# Run with query
docker run --rm -it aidarkleak "leaked passwords"

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
- requests
- beautifulsoup4
- PySocks
- python-dotenv

---

## Security Notes

⚠️ **For maximum anonymity:**
1. Connect to ProtonVPN (or any VPN) first
2. Then start Tor Browser
3. Run this script

This creates: **You → VPN → Tor → Dark Web** (double anonymity layer)
