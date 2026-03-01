"""Dark web search engine querying via Tor.

Queries multiple dark web search engines concurrently through Tor SOCKS5
proxies, with circuit isolation per stream.  Extracts .onion links from
search results and deduplicates them.

Refactored from the original ``search.py`` — all file I/O and CLI logic
removed; this module only exports async functions.
"""

from __future__ import annotations

import asyncio
import random
import re

from bs4 import BeautifulSoup
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


# ── Dark web search engines ───────────────────────────────────────────────

SEARCH_ENGINES = [
    "http://juhanurmihxlp77nkq76byazcldy2hlmovfu2epvl5ankdibsot4csyd.onion/search/?q={query}",
    "http://3bbad7fauom4d6sgppalyqddsqbf5u5p56b5k5uk2zxsy3d6ey2jobad.onion/search?q={query}",
    "http://iy3544gmoeclh5de6gez2256v6pjh4omhpqdh2wpeeppjtvqmjhkfwad.onion/torgle/?query={query}",
    "http://amnesia7u5odx5xbwtpnqk3edybgud5bmiagu75bnqx2crntw5kry7ad.onion/search?query={query}",
    "http://kaizerwfvp5gxu6cppibp7jhcqptavq3iqef66wbxenh6a2fklibdvid.onion/search?q={query}",
    "http://anima4ffe27xmakwnseih3ic2y7y3l6e7fucwk4oerdn4odf7k74tbid.onion/search?q={query}",
    "http://2fd6cemt4gmccflhm6imvdfvli3nf7zn6rfrwpsy7uhxrgbypvwf5fad.onion/search?query={query}",
    "http://oniwayzz74cv2puhsgx4dpjwieww4wdphsydqvf5q7eyz4myjvyw26ad.onion/search.php?s={query}",
    "http://tor66sewebgixwhcqfnp5inzp5x5uohhdy3kvtnyfxc2e5mxiuh34iid.onion/search?q={query}",
    "http://3fzh7yuupdfyjhwt3ugzqqof6ulbcl27ecev33knxe3u7goi3vfn2qqd.onion/oss/index.php?search={query}",
    "http://torgolnpeouim56dykfob6jh5r2ps2j73enc42s2um4ufob3ny4fcdyd.onion/?q={query}",
    "http://searchgf7gdtauh7bhnbyed4ivxqmuoat3nm6zfrg3ymkq6mtnpye3ad.onion/search?q={query}",
    "http://tornadoxn3viscgz647shlysdy7ea5zqzwda7hierekeuokh5eh5b3qd.onion/search?q={query}",
    "http://tornetupfu7gcgidt33ftnungxzyfq2pygui5qdoyss34xbgx2qruzid.onion/search?q={query}",
    "http://torlbmqwtudkorme6prgfpmsnile7ug2zm4u3ejpcncxuhpu4k2j4kyd.onion/index.php?a=search&q={query}",
    "http://findtorroveq5wdnipkaojfpqulxnkhblymc7aramjzajcvpptd4rjqd.onion/search?q={query}",
    "http://leaksndi6i6m2ji6ozulqe4imlrqn6wrgjlhxe25vremvr3aymm4aaid.onion/",
]


# ── Helpers ────────────────────────────────────────────────────────────────

ERROR_MESSAGES = {
    "timeout": "[ERROR: Connection timeout]",
    "connection": "[ERROR: Connection failed]",
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
    """Each stream_id gets a different Tor circuit."""
    return ProxyConnector.from_url(
        f"socks5://stream{stream_id}:x@{settings.tor_proxy_host}:{settings.tor_proxy_port}",
        rdns=True,
    )


# ── Engine fetch ──────────────────────────────────────────────────────────

async def _fetch_from_engine(endpoint: str, query: str, stream_id: int) -> list[str]:
    url = endpoint.format(query=query)
    headers = _get_browser_headers()
    connector = _get_proxy_connector(stream_id)
    timeout = ClientTimeout(total=40)

    try:
        print(f"  [*] Searching: {endpoint.split('/')[2][:20]}... (circuit {stream_id})")

        async with ClientSession(connector=connector, timeout=timeout) as session:
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    html = await response.text()
                    soup = BeautifulSoup(html, "html.parser")
                    links: list[str] = []

                    for a in soup.find_all("a"):
                        try:
                            href = a.get("href", "")
                            onion_links = re.findall(
                                r"https?://[a-z0-9\.]+\.onion[^\s\"'<>]*", href
                            )
                            for link in onion_links:
                                if "search" not in link:
                                    links.append(link)
                        except Exception:
                            continue

                    print(f"  [+] Found {len(links)} links from {endpoint.split('/')[2][:20]}")
                    return links
                else:
                    print(f"  [!] HTTP {response.status} from {endpoint.split('/')[2][:20]}")
                    return []
    except asyncio.TimeoutError:
        print(f"  [!] Timeout: {endpoint.split('/')[2][:20]}")
        return []
    except Exception as e:
        print(f"  [!] {_sanitize_error(e)[:30]}")
        return []


# ── Public API ────────────────────────────────────────────────────────────

async def search_dark_web(query: str) -> list[str]:
    """Search dark web engines for *query* and return deduplicated .onion URLs.

    Uses ``settings.max_workers`` concurrent tasks and ``settings.num_engines``
    search engines.
    """
    num_engines = min(settings.num_engines, len(SEARCH_ENGINES))
    engines_to_use = SEARCH_ENGINES[:num_engines]

    print(f"\n[+] Searching dark web for: '{query}'")
    print(f"[+] Using {len(engines_to_use)}/{len(SEARCH_ENGINES)} engines "
          f"with {settings.max_workers} concurrent tasks")
    print(f"[+] Circuit isolation: ENABLED\n")

    encoded_query = query.replace(" ", "+")
    semaphore = asyncio.Semaphore(settings.max_workers)

    async def limited_fetch(engine: str, stream_id: int) -> list[str]:
        async with semaphore:
            return await _fetch_from_engine(engine, encoded_query, stream_id)

    tasks = [limited_fetch(engine, i) for i, engine in enumerate(engines_to_use)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Flatten and deduplicate
    all_urls: list[str] = []
    for result in results:
        if isinstance(result, list):
            all_urls.extend(result)

    seen: set[str] = set()
    unique_urls: list[str] = []
    for url in all_urls:
        clean_url = url.rstrip("/")
        if clean_url not in seen:
            seen.add(clean_url)
            unique_urls.append(clean_url)

    print(f"[+] Found {len(unique_urls)} unique URLs")
    return unique_urls
