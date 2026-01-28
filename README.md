# Dark Web Leak Monitor

AI-based monitoring for data leaks on the dark web.

## How It Works

### Tor Connection
The application connects to the dark web through **Tor** (The Onion Router):
- Tor runs as a SOCKS5 proxy on `127.0.0.1:9050`
- All HTTP requests are routed through this proxy
- This allows access to `.onion` websites (dark web)

```python
# How the code connects to Tor (in search.py and scrape.py)
session.proxies = {
    "http": "socks5h://127.0.0.1:9050",
    "https": "socks5h://127.0.0.1:9050"
}
```

### Credentials Needed
**NONE!** This project requires:
- ❌ No API keys
- ❌ No login credentials
- ❌ No paid services
- ✅ Only Tor running locally (free and open source)

---

## Running the Project

### Option 1: Docker (Recommended - Works on Windows/Linux/Mac)

**Step 1: Build the Docker image**
```bash
cd c:\Users\prama\OneDrive\Documents\robin\thws\dark_web_leak
docker build -t dark_web_leak .
```

**Step 2: Run with a search query**
```bash
docker run --rm -it dark_web_leak "data breach"
```

**Step 3: Copy output files from container (optional)**
```bash
# Run and keep container to copy files
docker run --name dwl dark_web_leak "leaked passwords"

# Copy results to your machine
docker cp dwl:/app/results.txt .
docker cp dwl:/app/scraped_data.txt .

# Remove container
docker rm dwl
```

---

### Option 2: Windows (Native)

**Step 1: Install Tor**
- Download Tor Browser from https://www.torproject.org/
- OR install Tor service: `winget install TorProject.TorBrowser`

**Step 2: Start Tor**
```bash
# If using Tor Browser - just open it
# If using Tor service:
tor.exe
```

**Step 3: Install dependencies**
```bash
cd c:\Users\prama\OneDrive\Documents\robin\thws\dark_web_leak
pip install -r requirements.txt
```

**Step 4: Run the application**
```bash
python main.py "data breach"
```

---

### Option 3: Linux/Mac (Native)

**Step 1: Install Tor**
```bash
# Ubuntu/Debian
sudo apt install tor

# Mac
brew install tor
```

**Step 2: Start Tor service**
```bash
# Start Tor
sudo systemctl start tor
# OR
tor &
```

**Step 3: Verify Tor is running**
```bash
curl --socks5 127.0.0.1:9050 https://check.torproject.org/
```

**Step 4: Install dependencies and run**
```bash
cd dark_web_leak
pip install -r requirements.txt
python main.py "data breach"
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
dark_web_leak/
├── main.py          # Entry point
├── search.py        # Dark web search module
├── scrape.py        # Content scraping module
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
│  └──────────┘     └────┬─────┘     └────┬─────┘    │
│                        │                 │          │
│                        ▼                 ▼          │
│               ┌────────────────────────────┐        │
│               │   Tor Proxy (port 9050)    │        │
│               └────────────┬───────────────┘        │
│                            │                        │
└────────────────────────────┼────────────────────────┘
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
