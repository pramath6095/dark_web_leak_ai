"""
forum_auth.py — forum authentication module for dark web scraping.
handles account management, login, registration, captcha solving,
and session persistence through tor.
"""

import os
import re
import json
import time
import random
import string
import asyncio
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from aiohttp import ClientSession, ClientTimeout, CookieJar
from aiohttp_socks import ProxyConnector

from dotenv import load_dotenv
load_dotenv()

import functools
print = functools.partial(print, flush=True)

import warnings
warnings.filterwarnings("ignore")

# tor proxy config
TOR_PROXY_HOST = os.getenv("TOR_PROXY_HOST", "127.0.0.1")
TOR_PROXY_PORT = os.getenv("TOR_PROXY_PORT", "9150")

# forum auth config
FORUM_ACCOUNTS_FILE = os.getenv("FORUM_ACCOUNTS_FILE", os.path.join("output", "forum_accounts.json"))
FORUM_AUTO_REGISTER = os.getenv("FORUM_AUTO_REGISTER", "true").lower() == "true"

# captcha config
CAPTCHA_API_KEY = os.getenv("CAPTCHA_API_KEY", "").strip()
CAPTCHA_SERVICE = os.getenv("CAPTCHA_SERVICE", "2captcha").strip().lower()

# browser headers (reuse from scrape.py pattern)
BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:137.0) Gecko/20100101 Firefox/137.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate",
    "Upgrade-Insecure-Requests": "1",
}

# common login-wall indicators
LOGIN_WALL_PATTERNS = [
    re.compile(r'you must (?:be )?(?:logged in|register|sign up|create an account)', re.IGNORECASE),
    re.compile(r'please (?:login|log in|sign in|register)', re.IGNORECASE),
    re.compile(r'(?:login|sign[- ]?in) (?:required|to (?:view|continue|access|see|read))', re.IGNORECASE),
    re.compile(r'you (?:need|have) to (?:login|log in|register|sign up)', re.IGNORECASE),
    re.compile(r'(?:create|register) (?:an? )?account (?:to|for)', re.IGNORECASE),
    re.compile(r'members only', re.IGNORECASE),
    re.compile(r'(?:access|content) (?:is )?(?:restricted|denied|forbidden)', re.IGNORECASE),
    re.compile(r'you do not have permission to view', re.IGNORECASE),
    re.compile(r'this (?:page|content|forum|thread|topic) is (?:only )?(?:available|visible) (?:to|for) (?:registered|logged[- ]?in)', re.IGNORECASE),
]

# forum software detection signatures
FORUM_SIGNATURES = {
    "xenforo": [
        re.compile(r'xenforo', re.IGNORECASE),
        re.compile(r'data-xf-', re.IGNORECASE),
        re.compile(r'XF\.', re.IGNORECASE),
        re.compile(r'js/xf/', re.IGNORECASE),
    ],
    "mybb": [
        re.compile(r'mybb', re.IGNORECASE),
        re.compile(r'member\.php\?action=login', re.IGNORECASE),
        re.compile(r'my_post_key', re.IGNORECASE),
    ],
    "phpbb": [
        re.compile(r'phpbb', re.IGNORECASE),
        re.compile(r'phpBB', re.IGNORECASE),
        re.compile(r'ucp\.php\?mode=login', re.IGNORECASE),
    ],
    "smf": [
        re.compile(r'simple machines', re.IGNORECASE),
        re.compile(r'smf_', re.IGNORECASE),
        re.compile(r'action=login', re.IGNORECASE),
    ],
    "discourse": [
        re.compile(r'discourse', re.IGNORECASE),
        re.compile(r'ember-application', re.IGNORECASE),
        re.compile(r'data-discourse-', re.IGNORECASE),
    ],
}


# ============================================================
# FORUM ACCOUNT MANAGER
# ============================================================

class ForumAccountManager:
    """manages persistent credential store for forum accounts."""

    def __init__(self, filepath: str = None):
        self.filepath = filepath or FORUM_ACCOUNTS_FILE

    def _load(self) -> dict:
        """load accounts from disk."""
        if os.path.isfile(self.filepath):
            try:
                with open(self.filepath, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, ValueError):
                pass
        return {}

    def _save(self, accounts: dict):
        """persist accounts to disk."""
        os.makedirs(os.path.dirname(self.filepath) or ".", exist_ok=True)
        with open(self.filepath, "w", encoding="utf-8") as f:
            json.dump(accounts, f, indent=2)

    def get_account(self, domain: str) -> dict:
        """get stored credentials for a domain. returns {username, password} or None."""
        accounts = self._load()
        domain = domain.lower().strip()
        account = accounts.get(domain)
        if account:
            return {"username": account["username"], "password": account["password"]}
        return None

    def save_account(self, domain: str, username: str, password: str):
        """save credentials for a domain."""
        accounts = self._load()
        domain = domain.lower().strip()
        accounts[domain] = {
            "username": username,
            "password": password,
            "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        self._save(accounts)
        print(f"  [AUTH] Saved account for {domain}: {username}")

    def list_accounts(self) -> list:
        """list all stored accounts (domain + username, no passwords)."""
        accounts = self._load()
        return [
            {"domain": domain, "username": data["username"], "created": data.get("created", "unknown")}
            for domain, data in accounts.items()
        ]

    def delete_account(self, domain: str) -> bool:
        """remove a stored account. returns True if found and removed."""
        accounts = self._load()
        domain = domain.lower().strip()
        if domain in accounts:
            del accounts[domain]
            self._save(accounts)
            return True
        return False


# ============================================================
# CAPTCHA SOLVER
# ============================================================

class CaptchaSolver:
    """integrates with 2captcha/anti-captcha for automated captcha solving."""

    def __init__(self):
        self.api_key = CAPTCHA_API_KEY
        self.service = CAPTCHA_SERVICE
        self._solver = None

    def is_available(self) -> bool:
        """check if a captcha solving service is configured."""
        return bool(self.api_key)

    def _get_solver(self):
        """lazy-init the 2captcha solver instance."""
        if self._solver is None and self.api_key:
            try:
                from twocaptcha import TwoCaptcha
                config = {"apiKey": self.api_key}
                if self.service == "anticaptcha":
                    config["server"] = "https://api.anti-captcha.com"
                self._solver = TwoCaptcha(**config)
            except ImportError:
                print("  [AUTH] 2captcha-python not installed. Run: pip install 2captcha-python")
                return None
        return self._solver

    def detect_captcha(self, html: str) -> dict:
        """
        detect captcha type from html.
        returns {type: 'image'|'recaptcha_v2'|'hcaptcha'|'text'|'none', ...metadata}
        """
        if not html:
            return {"type": "none"}

        # hcaptcha — check BEFORE recaptcha because data-sitekey regex is broad
        if 'hcaptcha' in html.lower() or 'h-captcha' in html.lower():
            hcaptcha_match = re.search(
                r'data-sitekey=["\']([a-f0-9-]{36,})["\']', html
            )
            sitekey = hcaptcha_match.group(1) if hcaptcha_match else None
            if not sitekey:
                alt_match = re.search(r'sitekey["\s:=]+["\']([a-f0-9-]{36,})["\']', html)
                sitekey = alt_match.group(1) if alt_match else None
            if sitekey:
                return {"type": "hcaptcha", "sitekey": sitekey}

        # recaptcha v2
        recaptcha_match = re.search(
            r'data-sitekey=["\']([a-zA-Z0-9_-]+)["\']', html
        )
        if recaptcha_match or 'g-recaptcha' in html or 'recaptcha' in html.lower():
            sitekey = recaptcha_match.group(1) if recaptcha_match else None
            if not sitekey:
                # try alternate patterns
                alt_match = re.search(r'sitekey["\s:=]+["\']([a-zA-Z0-9_-]{20,})["\']', html)
                sitekey = alt_match.group(1) if alt_match else None
            if sitekey:
                return {"type": "recaptcha_v2", "sitekey": sitekey}

        # image captcha (common patterns)
        soup = BeautifulSoup(html, "html.parser")
        captcha_img = None

        # look for captcha images
        for img in soup.find_all("img"):
            src = img.get("src", "")
            alt = img.get("alt", "").lower()
            parent_id = ""
            if img.parent:
                parent_id = (img.parent.get("id", "") + img.parent.get("class", [""])[0] if img.parent.get("class") else img.parent.get("id", "")).lower()

            if any(kw in src.lower() for kw in ["captcha", "securimage", "verify", "code"]):
                captcha_img = src
                break
            if any(kw in alt for kw in ["captcha", "verification", "security code"]):
                captcha_img = src
                break
            if any(kw in parent_id for kw in ["captcha", "verify"]):
                captcha_img = src
                break

        if captcha_img:
            return {"type": "image", "image_url": captcha_img}

        # text captcha (e.g., "what is 2+3?")
        for label in soup.find_all(["label", "span", "div", "p"]):
            text = label.get_text(strip=True).lower()
            if re.search(r'what is \d+\s*[\+\-\*]\s*\d+', text):
                return {"type": "text", "question": label.get_text(strip=True)}
            if any(kw in text for kw in ["captcha", "human verification", "anti-spam", "security question"]):
                # check if sibling/child is a text input
                inp = label.find_next("input", {"type": ["text", "number"]})
                if inp:
                    return {"type": "text", "question": label.get_text(strip=True)}

        return {"type": "none"}

    async def solve(self, captcha_info: dict, page_url: str, session: ClientSession = None) -> str:
        """
        solve a captcha. returns the solution string or None on failure.
        runs the blocking 2captcha call in a thread executor.
        """
        solver = self._get_solver()
        if not solver:
            return None

        captcha_type = captcha_info.get("type", "none")
        if captcha_type == "none":
            return None

        try:
            loop = asyncio.get_event_loop()

            if captcha_type == "recaptcha_v2":
                sitekey = captcha_info.get("sitekey")
                if not sitekey:
                    return None
                print(f"  [CAPTCHA] Solving reCAPTCHA v2 (sitekey: {sitekey[:20]}...)...")
                result = await loop.run_in_executor(
                    None,
                    lambda: solver.recaptcha(sitekey=sitekey, url=page_url)
                )
                solution = result.get("code", "") if isinstance(result, dict) else str(result)
                print(f"  [CAPTCHA] reCAPTCHA solved successfully")
                return solution

            elif captcha_type == "hcaptcha":
                sitekey = captcha_info.get("sitekey")
                if not sitekey:
                    return None
                print(f"  [CAPTCHA] Solving hCaptcha (sitekey: {sitekey[:20]}...)...")
                result = await loop.run_in_executor(
                    None,
                    lambda: solver.hcaptcha(sitekey=sitekey, url=page_url)
                )
                solution = result.get("code", "") if isinstance(result, dict) else str(result)
                print(f"  [CAPTCHA] hCaptcha solved successfully")
                return solution

            elif captcha_type == "image":
                image_url = captcha_info.get("image_url")
                if not image_url or not session:
                    return None
                # download captcha image through tor
                full_url = urljoin(page_url, image_url)
                print(f"  [CAPTCHA] Downloading image captcha...")
                try:
                    async with session.get(full_url, headers=BROWSER_HEADERS) as resp:
                        if resp.status == 200:
                            image_data = await resp.read()
                            # save to temp file for 2captcha
                            import tempfile
                            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                                tmp.write(image_data)
                                tmp_path = tmp.name

                            print(f"  [CAPTCHA] Solving image captcha...")
                            result = await loop.run_in_executor(
                                None,
                                lambda: solver.normal(tmp_path)
                            )
                            # cleanup temp file
                            try:
                                os.unlink(tmp_path)
                            except OSError:
                                pass

                            solution = result.get("code", "") if isinstance(result, dict) else str(result)
                            print(f"  [CAPTCHA] Image captcha solved: {solution}")
                            return solution
                except Exception as e:
                    print(f"  [CAPTCHA] Failed to download captcha image: {str(e)[:80]}")
                    return None

            elif captcha_type == "text":
                question = captcha_info.get("question", "")
                if not question:
                    return None

                # try to solve simple math captchas locally first
                math_match = re.search(r'(\d+)\s*([\+\-\*])\s*(\d+)', question)
                if math_match:
                    a, op, b = int(math_match.group(1)), math_match.group(2), int(math_match.group(3))
                    if op == '+':
                        solution = str(a + b)
                    elif op == '-':
                        solution = str(a - b)
                    elif op == '*':
                        solution = str(a * b)
                    else:
                        solution = str(a + b)
                    print(f"  [CAPTCHA] Math captcha solved locally: {question} = {solution}")
                    return solution

                # send to 2captcha text endpoint
                print(f"  [CAPTCHA] Solving text captcha: {question[:60]}...")
                result = await loop.run_in_executor(
                    None,
                    lambda: solver.text(question)
                )
                solution = result.get("code", "") if isinstance(result, dict) else str(result)
                print(f"  [CAPTCHA] Text captcha solved: {solution}")
                return solution

        except Exception as e:
            print(f"  [CAPTCHA] Solving failed: {str(e)[:100]}")
            return None

        return None


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def generate_credentials() -> dict:
    """generate realistic random username and password."""
    # username patterns: word + numbers
    prefixes = [
        "dark", "shadow", "cyber", "night", "ghost", "void", "null", "byte",
        "zero", "net", "hack", "sys", "data", "code", "root", "nova",
        "storm", "pulse", "vector", "proxy", "echo", "delta", "omega",
        "alpha", "flux", "ion", "arc", "neon", "hex", "bit",
    ]
    suffixes = [
        "walker", "hunter", "runner", "fox", "wolf", "hawk", "crypt",
        "byte", "core", "node", "link", "gate", "lock", "key",
        "mind", "eye", "net", "ops", "sec", "dev",
    ]

    username = random.choice(prefixes) + random.choice(suffixes) + str(random.randint(10, 9999))

    # password: random mix of chars, strong enough for most forums
    chars = string.ascii_letters + string.digits + "!@#$%_-"
    password = ''.join(random.choices(chars, k=random.randint(14, 20)))
    # ensure at least one of each type
    password = (
        random.choice(string.ascii_uppercase) +
        random.choice(string.ascii_lowercase) +
        random.choice(string.digits) +
        random.choice("!@#$%_-") +
        password[4:]
    )

    return {"username": username, "password": password}


def extract_domain(url: str) -> str:
    """extract the .onion domain from a URL."""
    parsed = urlparse(url)
    return parsed.netloc.lower()


def extract_csrf_token(html: str) -> dict:
    """
    extract CSRF/security tokens from forms.
    returns dict of {field_name: value} for all hidden inputs.
    """
    soup = BeautifulSoup(html, "html.parser")
    tokens = {}

    # find hidden inputs in forms (csrf tokens, security tokens, etc.)
    for form in soup.find_all("form"):
        for inp in form.find_all("input", {"type": "hidden"}):
            name = inp.get("name", "")
            value = inp.get("value", "")
            if name:
                tokens[name] = value

    # xenforo specific: _xfToken
    xf_token = soup.find("input", {"name": "_xfToken"})
    if xf_token:
        tokens["_xfToken"] = xf_token.get("value", "")

    # mybb specific: my_post_key
    mybb_key = soup.find("input", {"name": "my_post_key"})
    if mybb_key:
        tokens["my_post_key"] = mybb_key.get("value", "")

    # phpbb specific: sid, creation_time, form_token
    for name in ["sid", "creation_time", "form_token"]:
        elem = soup.find("input", {"name": name})
        if elem:
            tokens[name] = elem.get("value", "")

    return tokens


def resolve_form_action(base_url: str, action: str) -> str:
    """resolve relative form action URL against base URL."""
    if not action:
        return base_url
    return urljoin(base_url, action)


# ============================================================
# FORUM SESSION — LOGIN / REGISTER ENGINE
# ============================================================

class ForumSession:
    """handles login, registration, and session management for dark web forums."""

    def __init__(self, account_manager: ForumAccountManager = None, captcha_solver: CaptchaSolver = None):
        self.account_manager = account_manager or ForumAccountManager()
        self.captcha_solver = captcha_solver or CaptchaSolver()
        # cache: domain -> cookie_jar (in-memory session cache)
        self._session_cache = {}

    def detect_forum_type(self, html: str) -> str:
        """identify forum software from HTML signatures."""
        if not html:
            return "generic"

        for forum_type, patterns in FORUM_SIGNATURES.items():
            for pattern in patterns:
                if pattern.search(html):
                    return forum_type

        return "generic"

    def find_login_form(self, html: str, url: str) -> dict:
        """
        parse login form from HTML.
        returns {action, method, fields: {name: value}, username_field, password_field} or None.
        """
        soup = BeautifulSoup(html, "html.parser")
        forum_type = self.detect_forum_type(html)

        # find forms with password inputs
        for form in soup.find_all("form"):
            password_inputs = form.find_all("input", {"type": "password"})
            if not password_inputs:
                continue

            action = resolve_form_action(url, form.get("action", ""))
            method = (form.get("method", "POST")).upper()

            # collect all hidden fields
            fields = {}
            for inp in form.find_all("input", {"type": "hidden"}):
                name = inp.get("name", "")
                if name:
                    fields[name] = inp.get("value", "")

            # identify username and password field names
            password_field = password_inputs[0].get("name", "password")

            # find text/email input (username field)
            username_field = None
            for inp in form.find_all("input"):
                input_type = inp.get("type", "text").lower()
                input_name = inp.get("name", "").lower()
                if input_type in ("text", "email"):
                    if any(kw in input_name for kw in ["user", "login", "name", "email", "account"]):
                        username_field = inp.get("name")
                        break
            if not username_field:
                # fallback: first text/email input
                for inp in form.find_all("input"):
                    if inp.get("type", "text").lower() in ("text", "email"):
                        if inp.get("name") != password_field:
                            username_field = inp.get("name")
                            break

            if not username_field:
                username_field = "login"  # generic fallback

            # forum-specific field name overrides
            if forum_type == "xenforo" and not any("login" in f.lower() for f in fields):
                username_field = username_field or "login"
                password_field = password_field or "password"
            elif forum_type == "mybb":
                username_field = username_field or "username"
                password_field = password_field or "password"
            elif forum_type == "phpbb":
                username_field = username_field or "username"
                password_field = password_field or "password"

            # check for "remember me" checkbox
            remember_field = None
            for inp in form.find_all("input", {"type": "checkbox"}):
                name = inp.get("name", "").lower()
                if any(kw in name for kw in ["remember", "autologin", "cookie", "persist"]):
                    remember_field = inp.get("name")
                    break

            return {
                "action": action,
                "method": method,
                "fields": fields,
                "username_field": username_field,
                "password_field": password_field,
                "remember_field": remember_field,
                "forum_type": forum_type,
            }

        return None

    def find_register_form(self, html: str, url: str) -> dict:
        """
        parse registration form from HTML.
        returns {action, fields, username_field, password_field, email_field, captcha_info} or None.
        """
        soup = BeautifulSoup(html, "html.parser")

        # find registration links first
        register_url = None
        for a in soup.find_all("a", href=True):
            href = a.get("href", "").lower()
            text = a.get_text(strip=True).lower()
            if any(kw in href for kw in ["register", "signup", "sign-up", "account/create", "create-account"]):
                register_url = urljoin(url, a["href"])
                break
            if any(kw in text for kw in ["register", "sign up", "create account"]):
                register_url = urljoin(url, a["href"])
                break

        if register_url:
            return {"register_url": register_url}

        # look for registration form on current page
        for form in soup.find_all("form"):
            action = form.get("action", "").lower()
            form_id = form.get("id", "").lower()
            form_text = form.get_text().lower()

            is_register = (
                any(kw in action for kw in ["register", "signup", "create"]) or
                any(kw in form_id for kw in ["register", "signup", "create"]) or
                ("register" in form_text[:200] and "password" in form_text)
            )

            if not is_register:
                continue

            # has password fields (for registration)
            password_inputs = form.find_all("input", {"type": "password"})
            if not password_inputs:
                continue

            form_action = resolve_form_action(url, form.get("action", ""))

            # collect fields
            fields = {}
            for inp in form.find_all("input", {"type": "hidden"}):
                name = inp.get("name", "")
                if name:
                    fields[name] = inp.get("value", "")

            # find field names
            username_field = email_field = password_field = password_confirm_field = None

            for inp in form.find_all("input"):
                name = inp.get("name", "").lower()
                input_type = inp.get("type", "text").lower()

                if input_type == "password":
                    if not password_field:
                        password_field = inp.get("name")
                    else:
                        password_confirm_field = inp.get("name")
                elif input_type in ("text", "email"):
                    if "email" in name or "mail" in name:
                        email_field = inp.get("name")
                    elif any(kw in name for kw in ["user", "login", "name", "account"]):
                        username_field = inp.get("name")
                    elif not username_field and input_type == "text":
                        username_field = inp.get("name")

            # detect captcha
            form_html = str(form)
            captcha_info = self.captcha_solver.detect_captcha(form_html)

            return {
                "action": form_action,
                "fields": fields,
                "username_field": username_field or "username",
                "password_field": password_field or "password",
                "password_confirm_field": password_confirm_field,
                "email_field": email_field,
                "captcha_info": captcha_info,
            }

        return None

    def is_logged_in(self, html: str) -> bool:
        """check if a page HTML indicates we're logged in."""
        if not html:
            return False

        soup = BeautifulSoup(html, "html.parser")

        # positive indicators (logged in)
        logged_in_patterns = [
            re.compile(r'log\s*out', re.IGNORECASE),
            re.compile(r'sign\s*out', re.IGNORECASE),
            re.compile(r'my\s*account', re.IGNORECASE),
            re.compile(r'your\s*account', re.IGNORECASE),
            re.compile(r'profile', re.IGNORECASE),
            re.compile(r'inbox|messages|notifications', re.IGNORECASE),
        ]

        # check links and buttons
        for a in soup.find_all(["a", "button"]):
            text = a.get_text(strip=True)
            href = a.get("href", "")
            for pattern in logged_in_patterns:
                if pattern.search(text) or pattern.search(href):
                    return True

        # negative indicators (NOT logged in)
        login_form = self.find_login_form(html, "")
        if login_form:
            # has a login form = probably not logged in
            # but some forums show login form even when logged in, so also check for logout
            for a in soup.find_all("a", href=True):
                if re.search(r'log\s*out|sign\s*out', a.get_text(strip=True), re.IGNORECASE):
                    return True
            return False

        return False

    async def login(self, session: ClientSession, url: str, username: str, password: str, html: str = None) -> bool:
        """
        attempt to log in to a forum.
        returns True on success, False on failure.
        """
        domain = extract_domain(url)

        # get the login page if we don't have HTML
        if not html:
            try:
                async with session.get(url, headers=BROWSER_HEADERS) as resp:
                    if resp.status != 200:
                        return False
                    html = await resp.text()
            except Exception as e:
                print(f"  [AUTH] Failed to fetch login page for {domain}: {str(e)[:60]}")
                return False

        # find login form
        login_form = self.find_login_form(html, url)
        if not login_form:
            print(f"  [AUTH] No login form found on {domain}")
            return False

        print(f"  [AUTH] Found {login_form['forum_type']} login form on {domain}")

        # build POST data
        post_data = dict(login_form["fields"])  # hidden fields (csrf tokens etc.)
        post_data[login_form["username_field"]] = username
        post_data[login_form["password_field"]] = password

        # check "remember me" if available
        if login_form.get("remember_field"):
            post_data[login_form["remember_field"]] = "1"

        # detect and solve captcha if present
        captcha_info = self.captcha_solver.detect_captcha(html)
        if captcha_info["type"] != "none":
            print(f"  [AUTH] Login page has {captcha_info['type']} captcha")
            if self.captcha_solver.is_available():
                solution = await self.captcha_solver.solve(captcha_info, url, session)
                if solution:
                    # inject captcha solution into form data
                    if captcha_info["type"] == "recaptcha_v2":
                        post_data["g-recaptcha-response"] = solution
                    elif captcha_info["type"] == "hcaptcha":
                        post_data["h-captcha-response"] = solution
                        post_data["g-recaptcha-response"] = solution  # some forums use this name for hcaptcha too
                    else:
                        # find the captcha input field name
                        soup = BeautifulSoup(html, "html.parser")
                        captcha_input = soup.find("input", {"name": re.compile(r'captcha|verify|code|answer', re.IGNORECASE)})
                        if captcha_input:
                            post_data[captcha_input["name"]] = solution
                else:
                    print(f"  [AUTH] Captcha solving failed, attempting login anyway")
            else:
                print(f"  [AUTH] No captcha API key configured, attempting login without solving")

        # submit login form
        action_url = login_form["action"]
        print(f"  [AUTH] Submitting login for {username}@{domain}...")

        try:
            # add referrer header for forums that check it
            login_headers = dict(BROWSER_HEADERS)
            login_headers["Referer"] = url
            login_headers["Content-Type"] = "application/x-www-form-urlencoded"

            async with session.post(action_url, data=post_data, headers=login_headers, allow_redirects=True) as resp:
                response_html = await resp.text()

                # check if we're now logged in
                if self.is_logged_in(response_html):
                    print(f"  [AUTH] ✓ Login successful for {username}@{domain}")
                    return True

                # check for error messages
                if any(kw in response_html.lower() for kw in [
                    "invalid", "incorrect", "wrong password", "bad password",
                    "authentication failed", "login failed", "error"
                ]):
                    print(f"  [AUTH] ✗ Login failed for {username}@{domain}: invalid credentials")
                    return False

                # check if redirected to a non-login page (possible success)
                if resp.url and "login" not in str(resp.url).lower():
                    # might have succeeded — check the redirected page
                    if self.is_logged_in(response_html):
                        print(f"  [AUTH] ✓ Login successful (redirect) for {username}@{domain}")
                        return True

                print(f"  [AUTH] ✗ Login result unclear for {username}@{domain}")
                return False

        except Exception as e:
            print(f"  [AUTH] Login request failed for {domain}: {str(e)[:60]}")
            return False

    async def register(self, session: ClientSession, url: str, html: str = None) -> dict:
        """
        attempt to register a new account on a forum.
        returns {username, password} on success, None on failure.
        """
        domain = extract_domain(url)

        if not FORUM_AUTO_REGISTER:
            print(f"  [AUTH] Auto-registration disabled. Skipping for {domain}")
            return None

        # get page HTML if not provided
        if not html:
            try:
                async with session.get(url, headers=BROWSER_HEADERS) as resp:
                    if resp.status != 200:
                        return None
                    html = await resp.text()
            except Exception as e:
                print(f"  [AUTH] Failed to fetch page for {domain}: {str(e)[:60]}")
                return None

        # find registration form or link
        reg_info = self.find_register_form(html, url)
        if not reg_info:
            print(f"  [AUTH] No registration form found on {domain}")
            return None

        # if we only found a registration link, follow it
        if "register_url" in reg_info:
            reg_url = reg_info["register_url"]
            print(f"  [AUTH] Following registration link: {reg_url[:60]}...")
            try:
                async with session.get(reg_url, headers=BROWSER_HEADERS) as resp:
                    if resp.status != 200:
                        print(f"  [AUTH] Registration page returned HTTP {resp.status}")
                        return None
                    reg_html = await resp.text()
                    reg_info = self.find_register_form(reg_html, reg_url)
                    if not reg_info or "register_url" in reg_info:
                        print(f"  [AUTH] No registration form found on registration page")
                        return None
                    url = reg_url
                    html = reg_html
            except Exception as e:
                print(f"  [AUTH] Failed to fetch registration page: {str(e)[:60]}")
                return None

        # generate credentials
        creds = generate_credentials()
        username = creds["username"]
        password = creds["password"]
        email = f"{username}@protonmail.com"

        print(f"  [AUTH] Attempting registration on {domain} as {username}...")

        # build POST data
        post_data = dict(reg_info.get("fields", {}))
        post_data[reg_info["username_field"]] = username
        post_data[reg_info["password_field"]] = password

        if reg_info.get("password_confirm_field"):
            post_data[reg_info["password_confirm_field"]] = password
        if reg_info.get("email_field"):
            post_data[reg_info["email_field"]] = email

        # handle captcha
        captcha_info = reg_info.get("captcha_info", {"type": "none"})
        if captcha_info["type"] != "none":
            print(f"  [AUTH] Registration has {captcha_info['type']} captcha")
            if self.captcha_solver.is_available():
                solution = await self.captcha_solver.solve(captcha_info, url, session)
                if solution:
                    if captcha_info["type"] == "recaptcha_v2":
                        post_data["g-recaptcha-response"] = solution
                    elif captcha_info["type"] == "hcaptcha":
                        post_data["h-captcha-response"] = solution
                        post_data["g-recaptcha-response"] = solution
                    else:
                        # find the captcha input field
                        soup = BeautifulSoup(html, "html.parser")
                        captcha_input = soup.find("input", {"name": re.compile(r'captcha|verify|code|answer', re.IGNORECASE)})
                        if captcha_input:
                            post_data[captcha_input["name"]] = solution
                else:
                    print(f"  [AUTH] Captcha solving failed, registration may fail")
            else:
                print(f"  [AUTH] No captcha API key — cannot auto-register on {domain}")
                return None

        # check for agreement/TOS checkboxes and auto-accept
        soup = BeautifulSoup(html, "html.parser")
        for inp in soup.find_all("input", {"type": "checkbox"}):
            name = inp.get("name", "").lower()
            if any(kw in name for kw in ["agree", "tos", "terms", "rules", "accept", "policy"]):
                post_data[inp.get("name")] = "1"

        # submit registration
        action_url = reg_info.get("action", url)

        try:
            reg_headers = dict(BROWSER_HEADERS)
            reg_headers["Referer"] = url
            reg_headers["Content-Type"] = "application/x-www-form-urlencoded"

            async with session.post(action_url, data=post_data, headers=reg_headers, allow_redirects=True) as resp:
                response_html = await resp.text()

                # check for success indicators
                success_indicators = [
                    "registration complete", "account created", "welcome",
                    "successfully registered", "thank you for registering",
                    "your account has been created", "registration successful",
                ]
                success = any(kw in response_html.lower() for kw in success_indicators)

                # check if we're now logged in (some forums auto-login after registration)
                if not success:
                    success = self.is_logged_in(response_html)

                # check for failure indicators
                failure_indicators = [
                    "already taken", "already exists", "username is not available",
                    "invalid email", "registration failed", "banned",
                    "invite code", "invitation", "closed for registration",
                    "registration is disabled",
                ]
                failed = any(kw in response_html.lower() for kw in failure_indicators)

                if success and not failed:
                    print(f"  [AUTH] ✓ Registration successful on {domain}: {username}")
                    # save account
                    self.account_manager.save_account(domain, username, password)
                    return {"username": username, "password": password}
                else:
                    # check specific error
                    if "already taken" in response_html.lower() or "already exists" in response_html.lower():
                        print(f"  [AUTH] Username taken, retrying with new name...")
                        # try once more with a different username
                        creds2 = generate_credentials()
                        post_data[reg_info["username_field"]] = creds2["username"]
                        post_data[reg_info["password_field"]] = creds2["password"]
                        if reg_info.get("password_confirm_field"):
                            post_data[reg_info["password_confirm_field"]] = creds2["password"]
                        if reg_info.get("email_field"):
                            post_data[reg_info["email_field"]] = f"{creds2['username']}@protonmail.com"

                        async with session.post(action_url, data=post_data, headers=reg_headers, allow_redirects=True) as resp2:
                            resp2_html = await resp2.text()
                            if any(kw in resp2_html.lower() for kw in success_indicators) or self.is_logged_in(resp2_html):
                                print(f"  [AUTH] ✓ Registration successful (2nd try) on {domain}: {creds2['username']}")
                                self.account_manager.save_account(domain, creds2["username"], creds2["password"])
                                return {"username": creds2["username"], "password": creds2["password"]}

                    print(f"  [AUTH] ✗ Registration failed on {domain}")
                    return None

        except Exception as e:
            print(f"  [AUTH] Registration request failed for {domain}: {str(e)[:80]}")
            return None

    async def get_authenticated_session(self, url: str, stream_id: int) -> tuple:
        """
        full authentication flow for a URL:
        1. check stored creds → try login
        2. if no creds → try register → login with new creds
        3. return (aiohttp.ClientSession with cookies, success_bool)

        returns (session, True) on success, (session, False) on failure.
        the session is always returned (may be unauthenticated).
        """
        domain = extract_domain(url)

        # check cache first
        if domain in self._session_cache:
            print(f"  [AUTH] Using cached session for {domain}")
            return self._session_cache[domain], True

        # create a session with a cookie jar that persists cookies
        connector = ProxyConnector.from_url(
            f"socks5://stream{stream_id}:x@{TOR_PROXY_HOST}:{TOR_PROXY_PORT}",
            rdns=True
        )
        cookie_jar = CookieJar(unsafe=True)  # unsafe=True for .onion domains
        timeout = ClientTimeout(total=45)
        session = ClientSession(connector=connector, timeout=timeout, cookie_jar=cookie_jar)

        try:
            # step 1: check stored credentials
            account = self.account_manager.get_account(domain)

            if account:
                print(f"  [AUTH] Found stored credentials for {domain}: {account['username']}")
                success = await self.login(session, url, account["username"], account["password"])
                if success:
                    self._session_cache[domain] = session
                    return session, True
                else:
                    print(f"  [AUTH] Stored credentials invalid for {domain}")
                    # don't delete — might be a temporary issue

            # step 2: try registration
            reg_result = await self.register(session, url)
            if reg_result:
                # try logging in with new credentials
                success = await self.login(session, url, reg_result["username"], reg_result["password"])
                if success:
                    self._session_cache[domain] = session
                    return session, True

            # step 3: auth failed
            print(f"  [AUTH] Could not authenticate to {domain}")
            return session, False

        except Exception as e:
            print(f"  [AUTH] Authentication flow failed for {domain}: {str(e)[:80]}")
            return session, False

    async def close_all(self):
        """close all cached sessions."""
        for domain, session in self._session_cache.items():
            try:
                await session.close()
            except Exception:
                pass
        self._session_cache.clear()


# ============================================================
# LOGIN WALL DETECTION
# ============================================================

def is_login_wall(html: str) -> bool:
    """
    detect if a page is behind a login wall.
    checks for common login-wall patterns and login form presence.
    """
    if not html:
        return False

    text = html

    # check for explicit login-wall messages
    for pattern in LOGIN_WALL_PATTERNS:
        if pattern.search(text):
            return True

    # check if page is mostly a login form with very little content
    soup = BeautifulSoup(html, "html.parser")

    # strip scripts, styles
    for elem in soup(["script", "style", "nav", "footer"]):
        elem.extract()

    visible_text = soup.get_text(separator=' ')
    visible_text = ' '.join(visible_text.split())

    # if very short content + has password field = likely login wall
    password_inputs = soup.find_all("input", {"type": "password"})
    if password_inputs and len(visible_text) < 500:
        return True

    # check for login/register links dominating the page
    login_links = soup.find_all("a", href=re.compile(r'login|register|sign[_-]?(?:in|up)', re.IGNORECASE))
    total_links = soup.find_all("a", href=True)
    if login_links and total_links and len(login_links) / max(len(total_links), 1) > 0.3:
        return True

    return False


# ============================================================
# GLOBAL INSTANCES
# ============================================================

# shared instances used by scrape.py
_account_manager = ForumAccountManager()
_captcha_solver = CaptchaSolver()
_forum_session = ForumSession(_account_manager, _captcha_solver)


def get_forum_session() -> ForumSession:
    """get the global forum session instance."""
    return _forum_session


def get_account_manager() -> ForumAccountManager:
    """get the global account manager instance."""
    return _account_manager
