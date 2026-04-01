import os
import json
import asyncio
import random
from datetime import datetime
from bs4 import BeautifulSoup
from aiohttp import ClientSession, ClientTimeout
from aiohttp_socks import ProxyConnector

from dotenv import load_dotenv
load_dotenv()

import warnings
warnings.filterwarnings("ignore")

import functools
print = functools.partial(print, flush=True)

# forum authentication
from forum_auth import is_login_wall, get_forum_session, extract_domain

# ── login wall tracking ──
_LOGIN_WALLS_FILE = os.path.join("output", "login_walls.json")

def _load_login_walls() -> list:
    if os.path.isfile(_LOGIN_WALLS_FILE):
        try:
            with open(_LOGIN_WALLS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, ValueError):
            pass
    return []

def _save_login_wall(url: str, status: str):
    """Append a login-wall detection entry. status = 'auth_success' | 'auth_failed'"""
    os.makedirs("output", exist_ok=True)
    walls = _load_login_walls()
    # avoid duplicate URLs — update status if already tracked
    for entry in walls:
        if entry["url"] == url:
            entry["status"] = status
            entry["last_seen"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open(_LOGIN_WALLS_FILE, "w", encoding="utf-8") as f:
                json.dump(walls, f, indent=2)
            return
    walls.append({
        "url": url,
        "domain": extract_domain(url),
        "status": status,
        "first_seen": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "last_seen": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })
    with open(_LOGIN_WALLS_FILE, "w", encoding="utf-8") as f:
        json.dump(walls, f, indent=2)

def get_login_walls() -> list:
    """Public accessor for tracked login walls."""
    return _load_login_walls()

# tor proxy config
TOR_PROXY_HOST = os.getenv("TOR_PROXY_HOST", "127.0.0.1")
TOR_PROXY_PORT = os.getenv("TOR_PROXY_PORT", "9150")

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


ERROR_MESSAGES = {
    "timeout": "[ERROR: Connection timeout]",
    "connection": "[ERROR: Connection failed]",
    "dead_link": "[ERROR: Dead link]",
    "http": "[ERROR: HTTP error]",
    "parse": "[ERROR: Parse error]",
    "unknown": "[ERROR: Request failed]",
    "auth_required": "[AUTH_REQUIRED: Login wall detected, authentication failed]",
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


def get_proxy_connector(stream_id: int) -> ProxyConnector:
    return ProxyConnector.from_url(
        f"socks5://stream{stream_id}:x@{TOR_PROXY_HOST}:{TOR_PROXY_PORT}",
        rdns=True
    )


async def check_url_alive(url: str, stream_id: int) -> bool:
    # quick HEAD check before doing full scrape
    connector = get_proxy_connector(stream_id)
    timeout = ClientTimeout(total=10)
    headers = get_browser_headers()
    
    try:
        async with ClientSession(connector=connector, timeout=timeout) as session:
            async with session.head(url, headers=headers, allow_redirects=True) as response:
                return response.status < 400
    except:
        return True  # if HEAD fails just try GET anyway


async def scrape_url(url: str, stream_id: int) -> tuple:
    print(f"  [*] Checking: {url[:45]}... (circuit {stream_id})")
    is_alive = await check_url_alive(url, stream_id)
    
    if not is_alive:
        print(f"  [!] Dead link: {url[:45]}...")
        return url, ERROR_MESSAGES["dead_link"], [], ''
    
    connector = get_proxy_connector(stream_id)
    timeout = ClientTimeout(total=45)
    headers = get_browser_headers()
    
    try:
        print(f"  [*] Scraping: {url[:45]}...")
        
        async with ClientSession(connector=connector, timeout=timeout) as session:
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    html = await response.text()
                    
                    # --- LOGIN WALL DETECTION ---
                    if is_login_wall(html):
                        print(f"  [AUTH] Login wall detected on {url[:45]}...")
                        auth_html = await _try_authenticated_scrape(url, stream_id, html)
                        if auth_html:
                            html = auth_html
                            print(f"  [AUTH] ✓ Got authenticated content for {url[:45]}...")
                            _save_login_wall(url, "auth_success")
                        else:
                            print(f"  [AUTH] ✗ Could not authenticate for {url[:45]}...")
                            _save_login_wall(url, "auth_failed")
                            return url, ERROR_MESSAGES["auth_required"], [], html
                    
                    soup = BeautifulSoup(html, "html.parser")
                    
                    # extract sublinks before stripping elements (for depth scraping)
                    sublinks = _extract_sublinks(url, soup)
                    
                    # strip out scripts, styles, nav etc
                    for element in soup(["script", "style", "nav", "footer", "header"]):
                        element.extract()
                    
                    text = soup.get_text(separator=' ')
                    text = ' '.join(text.split())
                    
                    print(f"  [+] Success: {url[:45]}... ({len(text)} chars, {len(sublinks)} sublinks)")
                    return url, text, sublinks, html
                else:
                    return url, f"[ERROR: HTTP {response.status}]", [], ''
                    
    except asyncio.TimeoutError:
        return url, ERROR_MESSAGES["timeout"], [], ''
    except Exception as e:
        return url, sanitize_error(e), [], ''


async def _try_authenticated_scrape(url: str, stream_id: int, original_html: str) -> str:
    """
    attempt to authenticate and re-fetch a login-walled page.
    returns the authenticated HTML on success, None on failure.
    """
    forum_session = get_forum_session()
    
    try:
        auth_session, success = await forum_session.get_authenticated_session(url, stream_id + 1000)
        
        if success:
            # re-fetch the page with authenticated session
            headers = get_browser_headers()
            try:
                async with auth_session.get(url, headers=headers) as resp:
                    if resp.status == 200:
                        html = await resp.text()
                        # verify we're past the login wall
                        if not is_login_wall(html):
                            return html
                        else:
                            print(f"  [AUTH] Still behind login wall after authentication")
                            return None
            except Exception as e:
                print(f"  [AUTH] Re-fetch failed: {str(e)[:60]}")
                return None
        
        return None
    except Exception as e:
        print(f"  [AUTH] Authentication flow error: {str(e)[:60]}")
        return None


async def scrape_url_paginated(url: str, stream_id: int, max_pages: int = 1) -> tuple:
    """scrape a URL and follow pagination links up to max_pages."""
    all_text = ""
    all_sublinks = []
    raw_html = ""
    current_url = url
    visited_pages = set()
    
    for page_num in range(max_pages):
        if current_url in visited_pages:
            break
        visited_pages.add(current_url)
        
        result_url, text, sublinks, html = await scrape_url(current_url, stream_id + page_num)
        
        if text.startswith("[ERROR"):
            if page_num == 0:
                return url, text, sublinks, html
            break
        
        all_text += ("\n\n" if all_text else "") + text
        all_sublinks.extend(sublinks)
        if page_num == 0:
            raw_html = html  # only cache first page HTML
        
        # detect next page
        if max_pages > 1 and html:
            soup = BeautifulSoup(html, "html.parser")
            next_url = _detect_next_page(soup, current_url)
            if next_url and next_url not in visited_pages:
                print(f"    [→] Following page {page_num + 2}: {next_url[:45]}...")
                current_url = next_url
            else:
                break
        else:
            break
    
    return url, all_text, all_sublinks, raw_html


def _extract_sublinks(parent_url: str, soup) -> list:
    """extract same-domain sublinks from a page, capped at 5 per page to prevent bloat"""
    import re as _re
    
    # get base domain of parent
    domain_match = _re.search(r'https?://([a-z0-9\.]+\.onion)', parent_url)
    if not domain_match:
        return []
    parent_domain = domain_match.group(1)
    
    sublinks = []
    seen = set()
    
    for a in soup.find_all('a', href=True):
        href = a['href']
        
        # resolve relative urls
        if href.startswith('/'):
            href = f"http://{parent_domain}{href}"
        
        # only follow same-domain .onion links
        if parent_domain not in href:
            continue
        
        # skip search, login, nav, and generic forum pages with no intel value
        skip_patterns = [
            # auth/session
            'login', 'register', 'signup', 'logout', 'sign-in', 'sign-up',
            'forgot-password', 'reset-password', 'account/create',
            # navigation / meta
            'javascript:', 'mailto:', '#',
            '?page=', '?sort=', '?order=', '?direction=',
            # forum generic pages
            '/whats-new', '/what-s-new', '/members', '/notable',
            '/rules', '/help', '/faq', '/contact', '/about',
            '/terms', '/privacy', '/tos', '/guidelines',
            '/staff', '/moderators', '/admin',
            '/install', '/upgrade',
            '/latest', '/categories', '/tags',
            '/search', '/find-threads',
            # social / share
            '/share', '/tweet', '/like',
            # static assets
            '.css', '.js', '.png', '.jpg', '.gif', '.svg', '.ico',
        ]
        if any(p in href.lower() for p in skip_patterns):
            continue
        
        clean = href.rstrip('/')
        if clean not in seen and clean != parent_url.rstrip('/'):
            seen.add(clean)
            sublinks.append(clean)
        
        if len(sublinks) >= 5:  # cap at 5 sublinks per page
            break
    
    return sublinks


def _detect_next_page(soup, current_url: str) -> str:
    """detect pagination 'next page' link. returns URL or None."""
    import re as _re
    from urllib.parse import urljoin
    
    # method 1: rel="next" link
    link = soup.find('a', rel='next')
    if link and link.get('href'):
        return urljoin(current_url, link['href'])
    
    # method 2: link text patterns
    next_patterns = ['next', 'next page', '»', '›', '→', '>>']
    for a in soup.find_all('a', href=True):
        text = a.get_text(strip=True).lower()
        if text in next_patterns:
            href = urljoin(current_url, a['href'])
            if href != current_url:
                return href
    
    # method 3: page number sequence (find current page, get next)
    pagination = soup.find(['nav', 'div', 'ul'], class_=_re.compile(r'pag', _re.IGNORECASE))
    if pagination:
        links = pagination.find_all('a', href=True)
        active = pagination.find(['span', 'strong', 'li'], class_=_re.compile(r'active|current', _re.IGNORECASE))
        if active:
            active_text = active.get_text(strip=True)
            if active_text.isdigit():
                next_num = str(int(active_text) + 1)
                for a in links:
                    if a.get_text(strip=True) == next_num:
                        return urljoin(current_url, a['href'])
    
    return None


def load_urls(filename: str = "output/results.txt") -> list:
    try:
        with open(filename, "r", encoding="utf-8") as f:
            urls = []
            for line in f:
                line = line.strip()
                if line:
                    # handle new format: "url | title"
                    url = line.split(" | ")[0].strip()
                    urls.append(url)
        return urls
    except FileNotFoundError:
        print(f"[-] File not found: {filename}")
        return []


async def scrape_all_async(urls: list, max_workers: int = 3, depth: int = 1, max_pages: int = 1, check_abort: callable = None) -> tuple:
    """
    scrape urls with optional depth control and pagination.
    depth=1: landing page only (default, backward compatible)
    depth=2: follow up to 5 sublinks per page (1 level deep)
    max_pages: follow pagination up to N pages per URL (default: 1 = no pagination)
    
    loop protection:
    - visited set prevents re-scraping same url
    - same-domain only (no cross-site following)
    - max 5 sublinks per page
    - strict depth cap
    
    returns (scraped_data, html_cache) tuple
    """
    print(f"\n[+] Scraping {len(urls)} URLs with {max_workers} concurrent tasks...")
    print(f"[+] Circuit isolation: ENABLED | HEAD pre-checks: ENABLED")
    print(f"[+] Depth: {depth} {'(sublinks enabled)' if depth > 1 else '(landing page only)'}")
    if max_pages > 1:
        print(f"[+] Pagination: up to {max_pages} pages per URL")
    print()
    
    semaphore = asyncio.Semaphore(max_workers)
    visited = set()
    results = {}
    html_cache = {}
    
    async def limited_scrape(url, stream_id):
        if check_abort and check_abort():
            raise InterruptedError("Aborted by user")
        async with semaphore:
            if check_abort and check_abort():
                raise InterruptedError("Aborted by user")
            # pass check_abort down if possible, but scrape_url_paginated isn't wired for it so we just check at task level
            return await scrape_url_paginated(url, stream_id, max_pages=max_pages)
    
    # depth 1: scrape initial urls
    tasks = []
    for i, url in enumerate(urls):
        clean = url.rstrip('/')
        if clean not in visited:
            visited.add(clean)
            tasks.append(limited_scrape(url, i))
    
    results_list = await asyncio.gather(*tasks, return_exceptions=True)
    
    all_sublinks = []
    for i, result in enumerate(results_list):
        if isinstance(result, tuple):
            url, content, sublinks, raw_html = result
            results[url] = content
            if raw_html:
                html_cache[url] = raw_html
            if depth > 1 and sublinks:
                all_sublinks.extend(sublinks)
        elif isinstance(result, InterruptedError):
            print("\n  [!] Scraping aborted early. Saving partial results...")
            break
        elif isinstance(result, Exception):
            results[urls[i]] = f"[ERROR: {str(result)[:100]}]"
    
    if check_abort and check_abort():
        return results, html_cache
    
    # depth 2: follow sublinks (if depth > 1)
    if depth > 1 and all_sublinks:
        # filter out already visited
        new_sublinks = [u for u in all_sublinks if u.rstrip('/') not in visited]
        
        if new_sublinks:
            print(f"\n[+] Depth 2: following {len(new_sublinks)} sublinks...")
            
            sub_tasks = []
            for i, url in enumerate(new_sublinks):
                clean = url.rstrip('/')
                if clean not in visited:
                    visited.add(clean)
                    sub_tasks.append(limited_scrape(url, i + len(urls)))
            
            sub_results = await asyncio.gather(*sub_tasks, return_exceptions=True)
            
            for i, result in enumerate(sub_results):
                if isinstance(result, tuple):
                    url, content, _, raw_html = result  # ignore sublinks at depth 2
                    results[url] = content
                    if raw_html:
                        html_cache[url] = raw_html
                elif isinstance(result, Exception):
                    results[new_sublinks[i]] = f"[ERROR: {str(result)[:100]}]"
            
            print(f"[+] Depth 2 complete: scraped {len(sub_results)} additional pages")
    
    # cleanup forum sessions
    try:
        forum_session = get_forum_session()
        await forum_session.close_all()
    except Exception:
        pass
    
    return results, html_cache


def scrape_all(urls: list, max_workers: int = 3, depth: int = 1, max_pages: int = 1, check_abort: callable = None) -> tuple:
    """returns (scraped_data, html_cache) tuple"""
    return asyncio.run(scrape_all_async(urls, max_workers, depth, max_pages=max_pages, check_abort=check_abort))


def save_scraped_data(results: dict, filename: str = "output/scraped_data.txt"):
    os.makedirs("output", exist_ok=True)
    
    with open(filename, "w", encoding="utf-8") as f:
        f.write("## 🕸 Dark Web Scraped Data\n\n")
        f.write(f"**{len(results)} pages scraped**\n\n")
        f.write("---\n\n")
        
        for i, (url, content) in enumerate(results.items(), 1):
            f.write(f"### [{i}] {url}\n\n")
            # Truncate extremely long content for readability
            display = content if len(content) <= 15000 else content[:15000] + "\n\n*... content truncated (full data preserved in raw scrape) ...*"
            f.write(display + "\n\n")
            f.write("---\n\n")
    
    print(f"\n[+] Saved scraped data to {filename}")


if __name__ == "__main__":
    urls = load_urls()
    if urls:
        print(f"[+] Loaded {len(urls)} URLs from output/results.txt")
        results = scrape_all(urls)
        save_scraped_data(results)
        
        success = sum(1 for v in results.values() if not v.startswith("[ERROR"))
        dead_links = sum(1 for v in results.values() if "Dead link" in v)
        print(f"[+] Successfully scraped {success}/{len(urls)} pages")
        print(f"[+] Dead links skipped: {dead_links}")
    else:
        print("[-] No URLs to scrape. Run search.py first.")
