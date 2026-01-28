"""
Dark Web Search Module
Searches dark web search engines and saves URLs to results.txt
"""
import requests
import random
import re
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

# Dark web search engines
SEARCH_ENGINES = [
    "http://juhanurmihxlp77nkq76byazcldy2hlmovfu2epvl5ankdibsot4csyd.onion/search/?q={query}",  # Ahmia
    "http://3bbad7fauom4d6sgppalyqddsqbf5u5p56b5k5uk2zxsy3d6ey2jobad.onion/search?q={query}",  # OnionLand
    "http://tor66sewebgixwhcqfnp5inzp5x5uohhdy3kvtnyfxc2e5mxiuh34iid.onion/search?q={query}",  # Tor66
    "http://searchgf7gdtauh7bhnbyed4ivxqmuoat3nm6zfrg3ymkq6mtnpye3ad.onion/search?q={query}",  # Deep Searches
    "http://findtorroveq5wdnipkaojfpqulxnkhblymc7aramjzajcvpptd4rjqd.onion/search?q={query}",  # Find Tor
]


def get_tor_session():
    """Creates a requests Session with Tor SOCKS proxy and retry logic."""
    session = requests.Session()
    retry = Retry(
        total=3,
        read=3,
        connect=3,
        backoff_factor=0.5,
        status_forcelist=[500, 502, 503, 504]
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    # Port 9150 = Tor Browser, Port 9150 = Tor service
    session.proxies = {
        "http": "socks5h://127.0.0.1:9150",
        "https": "socks5h://127.0.0.1:9150"
    }
    return session


def fetch_from_engine(endpoint, query):
    """Fetch search results from a single search engine."""
    url = endpoint.format(query=query)
    headers = {"User-Agent": random.choice(USER_AGENTS)}
    session = get_tor_session()
    
    try:
        print(f"  [*] Searching: {endpoint.split('/')[2][:20]}...")
        response = session.get(url, headers=headers, timeout=40)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, "html.parser")
            links = []
            for a in soup.find_all('a'):
                try:
                    href = a['href']
                    # Extract .onion links
                    onion_links = re.findall(r'https?://[a-z0-9\.]+\.onion[^\s"\'<>]*', href)
                    for link in onion_links:
                        # Filter out search engine self-references
                        if "search" not in link:
                            links.append(link)
                except:
                    continue
            return links
        return []
    except Exception as e:
        print(f"  [!] Error: {str(e)[:50]}")
        return []


def search_dark_web(query, max_workers=3):
    """Search multiple dark web engines and return unique URLs."""
    print(f"\n[+] Searching dark web for: '{query}'")
    print(f"[+] Using {len(SEARCH_ENGINES)} search engines...\n")
    
    all_urls = []
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(fetch_from_engine, engine, query.replace(" ", "+"))
            for engine in SEARCH_ENGINES
        ]
        for future in as_completed(futures):
            urls = future.result()
            all_urls.extend(urls)
    
    # Remove duplicates while preserving order
    seen = set()
    unique_urls = []
    for url in all_urls:
        clean_url = url.rstrip('/')
        if clean_url not in seen:
            seen.add(clean_url)
            unique_urls.append(clean_url)
    
    return unique_urls


def save_results(urls, filename="results.txt"):
    """Save URLs to a text file."""
    with open(filename, "w", encoding="utf-8") as f:
        for url in urls:
            f.write(url + "\n")
    print(f"\n[+] Saved {len(urls)} URLs to {filename}")


if __name__ == "__main__":
    # Example usage
    query = input("Enter search query: ")
    urls = search_dark_web(query)
    if urls:
        save_results(urls)
        print(f"\n[+] Found {len(urls)} unique URLs")
    else:
        print("\n[-] No results found. Check if Tor is running.")
