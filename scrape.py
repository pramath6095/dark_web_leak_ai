"""
Dark Web Scraper Module
Reads URLs from results.txt and saves scraped content to scraped_data.txt
Uses async I/O with HEAD pre-checks and circuit isolation
"""
import asyncio
import random
from bs4 import BeautifulSoup
from aiohttp import ClientSession, ClientTimeout
from aiohttp_socks import ProxyConnector

import warnings
warnings.filterwarnings("ignore")

# Browser profiles for realistic fingerprinting
# Each profile includes matching User-Agent and headers
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


def get_browser_headers() -> dict:
    """Get a random browser profile with matching headers."""
    return random.choice(BROWSER_PROFILES).copy()


# Sanitized error messages to prevent information leakage
ERROR_MESSAGES = {
    "timeout": "[ERROR: Connection timeout]",
    "connection": "[ERROR: Connection failed]",
    "dead_link": "[ERROR: Dead link]",
    "http": "[ERROR: HTTP error]",
    "parse": "[ERROR: Parse error]",
    "unknown": "[ERROR: Request failed]",
}


def sanitize_error(exception: Exception) -> str:
    """Convert exception to sanitized error message without leaking internal details."""
    error_str = str(exception).lower()
    
    if "timeout" in error_str:
        return ERROR_MESSAGES["timeout"]
    elif "connect" in error_str or "refused" in error_str or "unreachable" in error_str:
        return ERROR_MESSAGES["connection"]
    elif "http" in error_str or "status" in error_str:
        return ERROR_MESSAGES["http"]
    elif "parse" in error_str or "decode" in error_str:
        return ERROR_MESSAGES["parse"]
    else:
        return ERROR_MESSAGES["unknown"]


def get_proxy_connector(stream_id: int) -> ProxyConnector:
    """Create a SOCKS5 proxy connector with circuit isolation.
    
    Args:
        stream_id: Unique identifier for circuit isolation. Different IDs = different circuits.
    """
    return ProxyConnector.from_url(
        f"socks5://stream{stream_id}:x@127.0.0.1:9050",
        rdns=True  # Resolve DNS through Tor
    )


async def check_url_alive(url: str, stream_id: int) -> bool:
    """Check if URL is reachable using HEAD request.
    
    This is faster than a full GET and helps skip dead links.
    
    Args:
        url: URL to check
        stream_id: Unique ID for circuit isolation
    """
    connector = get_proxy_connector(stream_id)
    timeout = ClientTimeout(total=10)  # Short timeout for HEAD
    headers = get_browser_headers()
    
    try:
        async with ClientSession(connector=connector, timeout=timeout) as session:
            async with session.head(url, headers=headers, allow_redirects=True) as response:
                return response.status < 400
    except:
        # If HEAD fails, try GET anyway (some servers don't support HEAD)
        return True


async def scrape_url(url: str, stream_id: int) -> tuple:
    """Scrape content from a single URL asynchronously.
    
    Performs HEAD check first, then GET if alive.
    
    Args:
        url: The URL to scrape
        stream_id: Unique identifier for circuit isolation
    """
    # HEAD pre-check
    print(f"  [*] Checking: {url[:45]}... (circuit {stream_id})")
    is_alive = await check_url_alive(url, stream_id)
    
    if not is_alive:
        print(f"  [!] Dead link: {url[:45]}...")
        return url, ERROR_MESSAGES["dead_link"]
    
    # Full GET request
    connector = get_proxy_connector(stream_id)
    timeout = ClientTimeout(total=45)
    headers = get_browser_headers()
    
    try:
        print(f"  [*] Scraping: {url[:45]}...")
        
        async with ClientSession(connector=connector, timeout=timeout) as session:
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    html = await response.text()
                    soup = BeautifulSoup(html, "html.parser")
                    
                    # Remove scripts and styles
                    for element in soup(["script", "style", "nav", "footer", "header"]):
                        element.extract()
                    
                    # Get text content
                    text = soup.get_text(separator=' ')
                    # Normalize whitespace
                    text = ' '.join(text.split())
                    
                    # Truncate to 3000 chars
                    if len(text) > 3000:
                        text = text[:3000] + "... [TRUNCATED]"
                    
                    print(f"  [+] Success: {url[:45]}... ({len(text)} chars)")
                    return url, text
                else:
                    return url, f"[ERROR: HTTP {response.status}]"
                    
    except asyncio.TimeoutError:
        return url, ERROR_MESSAGES["timeout"]
    except Exception as e:
        return url, sanitize_error(e)


def load_urls(filename: str = "results.txt") -> list:
    """Load URLs from results file."""
    try:
        with open(filename, "r", encoding="utf-8") as f:
            urls = [line.strip() for line in f if line.strip()]
        return urls
    except FileNotFoundError:
        print(f"[-] File not found: {filename}")
        return []


async def scrape_all_async(urls: list, max_workers: int = 3) -> dict:
    """Scrape multiple URLs concurrently with HEAD pre-checks.
    
    Args:
        urls: List of URLs to scrape
        max_workers: Number of concurrent tasks (each uses a different Tor circuit)
    """
    print(f"\n[+] Scraping {len(urls)} URLs with {max_workers} concurrent tasks...")
    print(f"[+] Circuit isolation: ENABLED | HEAD pre-checks: ENABLED\n")
    
    # Use semaphore to limit concurrency
    semaphore = asyncio.Semaphore(max_workers)
    
    async def limited_scrape(url, stream_id):
        async with semaphore:
            return await scrape_url(url, stream_id)
    
    # Create tasks with unique stream IDs
    tasks = [
        limited_scrape(url, i)
        for i, url in enumerate(urls)
    ]
    
    results_list = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Convert to dictionary
    results = {}
    for i, result in enumerate(results_list):
        if isinstance(result, tuple):
            url, content = result
            results[url] = content
        elif isinstance(result, Exception):
            results[urls[i]] = f"[ERROR: {str(result)[:100]}]"
    
    return results


def scrape_all(urls: list, max_workers: int = 3) -> dict:
    """Synchronous wrapper for async scrape function."""
    return asyncio.run(scrape_all_async(urls, max_workers))


def save_scraped_data(results: dict, filename: str = "scraped_data.txt"):
    """Save scraped data organized by URL."""
    with open(filename, "w", encoding="utf-8") as f:
        f.write("=" * 80 + "\n")
        f.write("DARK WEB SCRAPED DATA\n")
        f.write("=" * 80 + "\n\n")
        
        for i, (url, content) in enumerate(results.items(), 1):
            f.write(f"\n{'='*80}\n")
            f.write(f"[{i}] URL: {url}\n")
            f.write(f"{'='*80}\n\n")
            f.write(content + "\n")
    
    print(f"\n[+] Saved scraped data to {filename}")


if __name__ == "__main__":
    urls = load_urls()
    if urls:
        print(f"[+] Loaded {len(urls)} URLs from results.txt")
        results = scrape_all(urls)
        save_scraped_data(results)
        
        # Count successful scrapes
        success = sum(1 for v in results.values() if not v.startswith("[ERROR"))
        print(f"[+] Successfully scraped {success}/{len(urls)} pages")
    else:
        print("[-] No URLs to scrape. Run search.py first.")
