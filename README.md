# aidarkleak

Dark web leak monitoring tool. Searches multiple .onion search engines and scrapes content from the results. Uses async I/O and routes everything through Tor.

> **Note:** This project is still under development. Some features are incomplete or may change.

## What it does

- Searches 17 dark web search engines for a given query
- Extracts .onion URLs from search results
- Scrapes text content from those URLs
- Saves everything to text files for analysis

Each request goes through a separate Tor circuit for better anonymity.

## Setup

### Requirements
- Python 3.8+
- Tor Browser running (uses SOCKS proxy on port 9150) or Tor daemon (port 9050)

### Install
```bash
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` if your Tor proxy is on a different port.

### Run
```bash
# interactive mode
python main.py

# with a query
python main.py "data breach"

# more options
python main.py -t 5 -l 20 "leaked credentials"
```

Options:
- `-t` — number of concurrent tasks (default 3)
- `-e` — how many search engines to use
- `-l` — max URLs to scrape (default 10)

### Docker

If you don't want to set up Tor yourself, use Docker. It comes with Tor built in.

```bash
docker build -t aidarkleak .
docker run --rm -it aidarkleak "data breach"
```

To get the output files out:
```bash
docker run --name dwl aidarkleak "query"
docker cp dwl:/app/output/ ./output
docker rm dwl
```

## Project structure

```
main.py          - entry point, CLI
search.py        - async search across dark web engines
scrape.py        - scrapes content from found URLs
Dockerfile       - container setup with Tor included
entrypoint.sh    - starts Tor then runs the script
requirements.txt - dependencies
.env.example     - config template
output/          - results go here (gitignored)
```

## Output

- `output/results.txt` — list of .onion URLs found
- `output/scraped_data.txt` — scraped text content organized by URL

## Dependencies

- aiohttp + aiohttp-socks (async HTTP through Tor)
- beautifulsoup4 (HTML parsing)
- python-dotenv (config)
