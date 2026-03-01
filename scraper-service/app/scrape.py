"""Tor-based web scraper for .onion pages.

Performs HEAD pre-checks and then full GET requests through Tor SOCKS5
proxies with circuit isolation and randomised browser fingerprints.

Returns **raw HTML** — all preprocessing is handled downstream by the
ai-analysis service.

Refactored from the original ``scrape.py`` — file I/O and CLI removed.
"""

from __future__ import annotations

import asyncio
import random

from aiohttp import ClientSession, ClientTimeout
from aiohttp_socks import ProxyConnector

from app.config import settings

import warnings
warnings.filterwarnings("ignore")

# ── Browser fingerprinting ─────────────────────────────────────────────────

BROWSER_PROFILES = [
    {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate",
        "Sec-Ch-Ua": '"Chromium";v="135", "Google Chrome";v="135", "Not-A.Brand";v="99"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Upgrade-Insecure-Requests": "1",
    },
    {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate",
        "Sec-Ch-Ua": '"Chromium";v="135", "Google Chrome";v="135", "Not-A.Brand";v="99"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"macOS"',
        "Upgrade-Insecure-Requests": "1",
    },
    {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:137.0) Gecko/20100101 Firefox/137.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate",
        "Upgrade-Insecure-Requests": "1",
    },
    {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:137.0) Gecko/20100101 Firefox/137.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate",
        "Upgrade-Insecure-Requests": "1",
    },
]


def _get_browser_headers() -> dict:
    return random.choice(BROWSER_PROFILES).copy()


# ── Helpers ────────────────────────────────────────────────────────────────

ERROR_MESSAGES = {
    "timeout": "[ERROR: Connection timeout]",
    "connection": "[ERROR: Connection failed]",
    "dead_link": "[ERROR: Dead link]",
    "http": "[ERROR: HTTP error]",
    "parse": "[ERROR: Parse error]",
    "unknown": "[ERROR: Request failed]",
}


def _sanitize_error(exception: Exception) -> str:
    error_str = str(exception).lower()
    if "timeout" in error_str:
        return ERROR_MESSAGES["timeout"]
    elif "connect" in error_str or "refused" in error_str or "unreachable" in error_str:
        return ERROR_MESSAGES["connection"]
    elif "http" in error_str or "status" in error_str:
        return ERROR_MESSAGES["http"]
    elif "parse" in error_str or "decode" in error_str:
        return ERROR_MESSAGES["parse"]
    return ERROR_MESSAGES["unknown"]


def _get_proxy_connector(stream_id: int) -> ProxyConnector:
    return ProxyConnector.from_url(
        f"socks5://stream{stream_id}:x@{settings.tor_proxy_host}:{settings.tor_proxy_port}",
        rdns=True,
    )


# ── URL liveness check ───────────────────────────────────────────────────

async def _check_url_alive(url: str, stream_id: int) -> bool:
    """Quick HEAD check before doing a full scrape."""
    connector = _get_proxy_connector(stream_id)
    timeout = ClientTimeout(total=10)
    headers = _get_browser_headers()

    try:
        async with ClientSession(connector=connector, timeout=timeout) as session:
            async with session.head(url, headers=headers, allow_redirects=True) as resp:
                return resp.status < 400
    except Exception:
        return True  # if HEAD fails, try GET anyway


# ── Single-page scrape ────────────────────────────────────────────────────

async def _scrape_url(url: str, stream_id: int) -> tuple[str, str]:
    """Scrape a single URL.  Returns ``(url, raw_html_or_error)``."""
    print(f"  [*] Checking: {url[:45]}... (circuit {stream_id})")
    is_alive = await _check_url_alive(url, stream_id)

    if not is_alive:
        print(f"  [!] Dead link: {url[:45]}...")
        return url, ERROR_MESSAGES["dead_link"]

    connector = _get_proxy_connector(stream_id)
    timeout = ClientTimeout(total=45)
    headers = _get_browser_headers()

    try:
        print(f"  [*] Scraping: {url[:45]}...")

        async with ClientSession(connector=connector, timeout=timeout) as session:
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    raw_html = await response.text()
                    print(f"  [+] Success: {url[:45]}... ({len(raw_html)} chars)")
                    return url, raw_html
                else:
                    return url, f"[ERROR: HTTP {response.status}]"

    except asyncio.TimeoutError:
        return url, ERROR_MESSAGES["timeout"]
    except Exception as e:
        return url, _sanitize_error(e)


# ── Public API ────────────────────────────────────────────────────────────

async def scrape_all(urls: list[str]) -> dict[str, str]:
    """Scrape all URLs concurrently and return ``{url: raw_html_or_error}``.

    Respects ``settings.max_workers`` for concurrency and
    ``settings.scrape_limit`` for the maximum number of URLs to scrape.
    """
    urls_to_scrape = urls[: settings.scrape_limit]

    print(f"\n[+] Scraping {len(urls_to_scrape)} URLs with "
          f"{settings.max_workers} concurrent tasks...")
    print(f"[+] Circuit isolation: ENABLED | HEAD pre-checks: ENABLED\n")

    semaphore = asyncio.Semaphore(settings.max_workers)

    async def limited_scrape(url: str, stream_id: int) -> tuple[str, str]:
        async with semaphore:
            return await _scrape_url(url, stream_id)

    tasks = [limited_scrape(url, i) for i, url in enumerate(urls_to_scrape)]
    results_list = await asyncio.gather(*tasks, return_exceptions=True)

    results: dict[str, str] = {}
    for i, result in enumerate(results_list):
        if isinstance(result, tuple):
            url, content = result
            results[url] = content
        elif isinstance(result, Exception):
            results[urls_to_scrape[i]] = f"[ERROR: {str(result)[:100]}]"

    success = sum(1 for v in results.values() if not v.startswith("[ERROR"))
    dead = sum(1 for v in results.values() if "Dead link" in v)
    print(f"\n[+] Scraped {success}/{len(urls_to_scrape)} pages "
          f"(dead links: {dead})")

    return results
