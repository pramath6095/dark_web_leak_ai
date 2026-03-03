import os
import asyncio
import random
import re
from bs4 import BeautifulSoup
from aiohttp import ClientSession, ClientTimeout
from aiohttp_socks import ProxyConnector

from dotenv import load_dotenv
load_dotenv()

import warnings
warnings.filterwarnings("ignore")

# tor proxy config
TOR_PROXY_HOST = os.getenv("TOR_PROXY_HOST", "127.0.0.1")
TOR_PROXY_PORT = os.getenv("TOR_PROXY_PORT", "9150")

# browser profiles for fingerprinting
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
    return random.choice(BROWSER_PROFILES).copy()


# sanitized error messages so we dont leak internal info
ERROR_MESSAGES = {
    "timeout": "[ERROR: Connection timeout]",
    "connection": "[ERROR: Connection failed]",
    "http": "[ERROR: HTTP error]",
    "parse": "[ERROR: Parse error]",
    "unknown": "[ERROR: Request failed]",
}


def sanitize_error(exception: Exception) -> str:
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


# dark web search engines
SEARCH_ENGINES = [
    "http://juhanurmihxlp77nkq76byazcldy2hlmovfu2epvl5ankdibsot4csyd.onion/search/?q={query}",
    "http://3bbad7fauom4d6sgppalyqddsqbf5u5p56b5k5uk2zxsy3d6ey2jobad.onion/search?q={query}",
    "http://iy3544gmoeclh5de6gez2256v6pjh4omhpqdh2wpeeppjtvqmjhkfwad.onion/torgle/?query={query}",
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
    "http://leaksndi6i6m2ji6ozulqe4imlrqn6wrgjlhxe25vremvr3aymm4aaid.onion/?q={query}",
    "http://amnesia7u5odx5xbwtpnqk3edybgud5bmiagu75bnqx2crntw5kry7ad.onion/search?query={query}",
]


def get_proxy_connector(stream_id: int) -> ProxyConnector:
    # each stream_id gets a different tor circuit
    return ProxyConnector.from_url(
        f"socks5://stream{stream_id}:x@{TOR_PROXY_HOST}:{TOR_PROXY_PORT}",
        rdns=True
    )


async def fetch_from_engine(endpoint: str, query: str, stream_id: int) -> list:
    url = endpoint.format(query=query)
    headers = get_browser_headers()
    connector = get_proxy_connector(stream_id)
    timeout = ClientTimeout(total=40)
    
    try:
        print(f"  [*] Searching: {endpoint.split('/')[2][:20]}... (circuit {stream_id})")
        
        async with ClientSession(connector=connector, timeout=timeout) as session:
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    html = await response.text()
                    soup = BeautifulSoup(html, "html.parser")
                    links = []
                    
                    for a in soup.find_all('a'):
                        try:
                            href = a.get('href', '')
                            title = a.get_text(strip=True)[:100]
                            onion_links = re.findall(r'https?://[a-z0-9\.]+\.onion[^\s"\'<>]*', href)
                            for link in onion_links:
                                if "search" not in link and len(title) > 2:
                                    links.append({"url": link, "title": title})
                        except:
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
        print(f"  [!] {sanitize_error(e)[:30]}")
        return []


async def search_dark_web_async(query: str, max_workers: int = 3, num_engines: int = None) -> list:
    engines_to_use = SEARCH_ENGINES[:num_engines] if num_engines else SEARCH_ENGINES
    
    print(f"\n[+] Searching dark web for: '{query}'")
    print(f"[+] Using {len(engines_to_use)}/{len(SEARCH_ENGINES)} search engines with {max_workers} concurrent tasks...")
    print(f"[+] Circuit isolation: ENABLED\n")
    
    encoded_query = query.replace(" ", "+")
    semaphore = asyncio.Semaphore(max_workers)
    
    async def limited_fetch(engine, stream_id):
        async with semaphore:
            return await fetch_from_engine(engine, encoded_query, stream_id)
    
    tasks = [
        limited_fetch(engine, i)
        for i, engine in enumerate(engines_to_use)
    ]
    
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # flatten and deduplicate by url
    all_results = []
    for result in results:
        if isinstance(result, list):
            all_results.extend(result)
    
    seen = set()
    unique_results = []
    for item in all_results:
        clean_url = item["url"].rstrip('/')
        if clean_url not in seen:
            seen.add(clean_url)
            unique_results.append({"url": clean_url, "title": item["title"]})
    
    return unique_results


def search_dark_web(query: str, max_workers: int = 3, num_engines: int = None) -> list:
    return asyncio.run(search_dark_web_async(query, max_workers, num_engines))


def save_results(results: list, filename: str = "output/results.txt"):
    os.makedirs("output", exist_ok=True)
    with open(filename, "w", encoding="utf-8") as f:
        for item in results:
            if isinstance(item, dict):
                f.write(f"{item['url']} | {item.get('title', 'Untitled')}\n")
            else:
                f.write(item + "\n")
    print(f"\n[+] Saved {len(results)} results to {filename}")


def get_urls_from_results(results: list) -> list:
    """extract plain url list from search results for scraper compatibility"""
    if not results:
        return []
    if isinstance(results[0], dict):
        return [item["url"] for item in results]
    return results


async def check_engines_async(max_workers: int = 5) -> dict:
    """health-check all search engines. returns dict of url -> {status, response_time_ms}"""
    import time as _time
    
    print(f"\n[+] Checking {len(SEARCH_ENGINES)} search engines...")
    print(f"[+] Using Tor proxy at {TOR_PROXY_HOST}:{TOR_PROXY_PORT}\n")
    
    semaphore = asyncio.Semaphore(max_workers)
    results = {}
    
    async def check_one(engine, stream_id):
        async with semaphore:
            url = engine.format(query="test")
            domain = engine.split('/')[2][:25]
            connector = get_proxy_connector(stream_id)
            timeout = ClientTimeout(total=20)
            headers = get_browser_headers()
            
            start = _time.time()
            try:
                async with ClientSession(connector=connector, timeout=timeout) as session:
                    async with session.get(url, headers=headers) as response:
                        elapsed = int((_time.time() - start) * 1000)
                        status = "alive" if response.status == 200 else f"http_{response.status}"
                        results[engine] = {"status": status, "ms": elapsed, "domain": domain}
                        icon = "+" if status == "alive" else "!"
                        print(f"  [{icon}] {domain:<25} {status:<10} {elapsed}ms")
            except asyncio.TimeoutError:
                elapsed = int((_time.time() - start) * 1000)
                results[engine] = {"status": "timeout", "ms": elapsed, "domain": domain}
                print(f"  [x] {domain:<25} timeout    {elapsed}ms")
            except Exception:
                elapsed = int((_time.time() - start) * 1000)
                results[engine] = {"status": "dead", "ms": elapsed, "domain": domain}
                print(f"  [x] {domain:<25} dead       {elapsed}ms")
    
    tasks = [check_one(engine, i) for i, engine in enumerate(SEARCH_ENGINES)]
    await asyncio.gather(*tasks)
    
    # summary
    alive = sum(1 for r in results.values() if r["status"] == "alive")
    print(f"\n[+] Results: {alive}/{len(SEARCH_ENGINES)} engines alive")
    return results


def check_engines(max_workers: int = 5) -> dict:
    return asyncio.run(check_engines_async(max_workers))


if __name__ == "__main__":
    query = input("Enter search query: ")
    results = search_dark_web(query)
    if results:
        save_results(results)
        print(f"\n[+] Found {len(results)} unique results")
        for i, item in enumerate(results[:5], 1):
            print(f"  {i}. {item['title'][:50]} — {item['url'][:50]}")
        if len(results) > 5:
            print(f"  ... and {len(results) - 5} more")
    else:
        print("\n[-] No results found. Check if Tor is running.")
