"""
Dark Web Scraper Module
Reads URLs from results.txt and saves scraped content to scraped_data.txt
"""
import requests
import random
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import warnings
warnings.filterwarnings("ignore")

# User agents for request rotation
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/135.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/135.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/135.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:137.0) Gecko/20100101 Firefox/137.0",
]


def get_tor_session():
    """Creates a requests Session with Tor SOCKS proxy."""
    session = requests.Session()
    retry = Retry(
        total=3,
        read=3,
        connect=3,
        backoff_factor=0.3,
        status_forcelist=[500, 502, 503, 504]
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    # Port 9150 = Tor Browser, Port 9050 = Tor service
    session.proxies = {
        "http": "socks5h://127.0.0.1:9150",
        "https": "socks5h://127.0.0.1:9150"
    }
    return session


def scrape_url(url):
    """Scrape content from a single URL."""
    headers = {"User-Agent": random.choice(USER_AGENTS)}
    
    try:
        print(f"  [*] Scraping: {url[:60]}...")
        session = get_tor_session()
        response = session.get(url, headers=headers, timeout=45)
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, "html.parser")
            
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
            
            return url, text
        else:
            return url, f"[ERROR: HTTP {response.status_code}]"
    except Exception as e:
        return url, f"[ERROR: {str(e)[:100]}]"


def load_urls(filename="results.txt"):
    """Load URLs from results file."""
    try:
        with open(filename, "r", encoding="utf-8") as f:
            urls = [line.strip() for line in f if line.strip()]
        return urls
    except FileNotFoundError:
        print(f"[-] File not found: {filename}")
        return []


def scrape_all(urls, max_workers=3):
    """Scrape multiple URLs concurrently."""
    print(f"\n[+] Scraping {len(urls)} URLs...\n")
    
    results = {}
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(scrape_url, url): url for url in urls}
        for future in as_completed(futures):
            url, content = future.result()
            results[url] = content
    
    return results


def save_scraped_data(results, filename="scraped_data.txt"):
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
