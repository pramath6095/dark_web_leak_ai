"""
Dark Web Search Module
Searches dark web search engines and saves URLs to results.txt

RECOMMENDED SETUP FOR MAXIMUM ANONYMITY:
1. Connect to ProtonVPN using the desktop app (normal VPN connection)
2. Start Tor Browser (runs SOCKS5 proxy on port 9150)
3. Run this script

Traffic flow: You → ProtonVPN (system VPN) → Tor SOCKS5 → Dark Web
"""
import os
import requests
import random
import re
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Load environment variables from .env file
from dotenv import load_dotenv
load_dotenv()

import warnings
warnings.filterwarnings("ignore")

# =============================================================================
# CONFIGURATION (loaded from .env file)
# =============================================================================
# ProtonVPN credentials (for reference - connect via desktop app)
PROTONVPN_USER = os.getenv("PROTONVPN_USER", "")
PROTONVPN_PASS = os.getenv("PROTONVPN_PASS", "")

# Tor SOCKS5 Proxy (Tor Browser = 9150, Tor Service = 9050)
TOR_PROXY_HOST = os.getenv("TOR_PROXY_HOST", "127.0.0.1")
TOR_PROXY_PORT = os.getenv("TOR_PROXY_PORT", "9150")
# =============================================================================

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


def check_vpn_status():
    """Check if traffic is going through VPN by checking public IP."""
    try:
        # This request goes through VPN if connected (not through Tor)
        response = requests.get("https://api.ipify.org?format=json", timeout=10)
        if response.status_code == 200:
            ip = response.json().get("ip", "Unknown")
            print(f"[*] Your public IP: {ip}")
            print("[*] If this is NOT your real IP, ProtonVPN is working!")
            return True
    except:
        print("[!] Could not check VPN status")
    return False


def get_tor_session():
    """Creates a requests Session with Tor SOCKS5 proxy."""
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
    
    # Tor SOCKS5 proxy (traffic already goes through ProtonVPN if connected)
    tor_proxy = f"socks5h://{TOR_PROXY_HOST}:{TOR_PROXY_PORT}"
    session.proxies = {
        "http": tor_proxy,
        "https": tor_proxy
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
    print("=" * 60)
    print("DARK WEB SEARCH - ProtonVPN + Tor")
    print("=" * 60)
    print("\nFor maximum anonymity:")
    print("1. Connect to ProtonVPN desktop app")
    print("2. Start Tor Browser")
    print("3. Run this script")
    print(f"\nTraffic: You → ProtonVPN → Tor ({TOR_PROXY_HOST}:{TOR_PROXY_PORT}) → Dark Web")
    
    if PROTONVPN_USER:
        print(f"[✓] ProtonVPN credentials loaded from .env")
    else:
        print("[!] ProtonVPN credentials not set in .env (optional)")
    
    print("=" * 60)
    
    # Check VPN status
    print("\n[*] Checking VPN status...")
    check_vpn_status()
    
    query = input("\nEnter search query: ")
    urls = search_dark_web(query)
    if urls:
        save_results(urls)
        print(f"\n[+] Found {len(urls)} unique URLs")
    else:
        print("\n[-] No results found. Check if Tor is running.")
