import re
import ipaddress
from urllib.parse import urlparse


# regex patterns for IOC extraction from scraped dark web content
IOC_PATTERNS = {
    "email": re.compile(
        r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}',
        re.IGNORECASE
    ),
    "ipv4": re.compile(
        r'\b(?:(?:25[0-5]|2[0-4]\d|1\d{2}|[1-9]?\d)\.){3}(?:25[0-5]|2[0-4]\d|1\d{2}|[1-9]?\d)\b'
    ),
    "domain": re.compile(
        r'\b(?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)+(?:com|net|org|io|co|info|biz|xyz|ru|cn|tk|cc|pw|top|site|online|live|gov|edu|mil|me|us|uk|de|fr|jp|br|au|ca|in|it|nl|es|se|no|fi|dk|pl|cz|at|ch|be|ie|pt|gr|hu|ro|bg|hr|sk|si|lt|lv|ee|lu|mt|cy)\b',
        re.IGNORECASE
    ),
    "url": re.compile(
        r'https?://[^\s<>"\']{5,}',
        re.IGNORECASE
    ),
    "btc_wallet": re.compile(
        r'\b(?:1|3|bc1)[a-zA-HJ-NP-Z0-9]{25,62}\b'
    ),
    "eth_wallet": re.compile(
        r'\b0x[a-fA-F0-9]{40}\b'
    ),
    "xmr_wallet": re.compile(
        r'\b4[0-9AB][1-9A-HJ-NP-Za-km-z]{93}\b'
    ),
    "ltc_wallet": re.compile(
        r'\b[LM3][a-km-zA-HJ-NP-Z1-9]{26,33}\b'
    ),
    "md5_hash": re.compile(
        r'\b[a-fA-F0-9]{32}\b'
    ),
    "sha256_hash": re.compile(
        r'\b[a-fA-F0-9]{64}\b'
    ),
    "phone": re.compile(
        r'\b(?:\+?\d{1,3}[\s\-]?)?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{4}\b'
    ),
    "credit_card": re.compile(
        r'\b(?:4\d{3}|5[1-5]\d{2}|6011|3[47]\d{2})[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4}\b'
    ),
    "ssn": re.compile(
        r'\b\d{3}[\s\-]\d{2}[\s\-]\d{4}\b'
    ),
    "credential_pair": re.compile(
        r'[a-zA-Z0-9._%+\-]{3,}(?:@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})?[:\|][^\s:]{6,}',
        re.IGNORECASE
    ),
    "telegram_user": re.compile(
        r'(?:'
        r'(?:https?://)?t\.me/([a-zA-Z0-9_]{3,32})'
        r'|(?:https?://)?telegram\.me/([a-zA-Z0-9_]{3,32})'
        r'|telegram\s*[:\s]\s*@([a-zA-Z0-9_]{3,32})'
        r'|tg\s*[:\s]\s*@([a-zA-Z0-9_]{3,32})'
        r'|(?<=\s)@([a-zA-Z0-9_]{3,32})(?=\s|$)'
        r')',
        re.IGNORECASE
    ),
}


# threat actor contact patterns — separate from IOCs
# these identify WHO is behind a listing, not WHAT was leaked
CONTACT_PATTERNS = {
    # messaging apps — strict patterns to avoid matching thread titles
    "telegram": re.compile(
        r'(?:'
        r'(?:https?://)?t\.me/[a-zA-Z0-9_]{3,32}'  # t.me links
        r'|(?:https?://)?telegram\.me/[a-zA-Z0-9_]{3,32}'  # telegram.me links
        r'|tg\s*:\s*@[a-zA-Z0-9_]{3,32}'  # tg:@user (strict colon+@ required)
        r'|tg\s*@[a-zA-Z0-9_]{3,32}'  # tg@user
        r')',
        re.IGNORECASE
    ),
    "wickr": re.compile(
        r'wickr\s*(?:me)?\s*:\s*[a-zA-Z0-9_.\-]{3,30}',
        re.IGNORECASE
    ),
    "signal": re.compile(
        r'signal\s*:\s*(?:\+?\d[\d\s\-]{8,15}|[a-zA-Z0-9_.\-]{3,30})',
        re.IGNORECASE
    ),
    "session": re.compile(
        r'session\s*:\s*(?:05[a-f0-9]{64}|[a-zA-Z0-9_.\-]{3,30})',
        re.IGNORECASE
    ),
    "jabber_xmpp": re.compile(
        r'[a-zA-Z0-9._%+\-]+@(?:'
        r'jabber\.(?:de|org|ru|cz|at|me|calyxinstitute\.org)'
        r'|xmpp\.(?:jp|is|org)'
        r'|(?:exploit|chat|rows|conversations)\.im'
        r'|(?:dukgo|sure|suchat|blah|hot-chilli)\.com'
        r'|(?:draugr|404)\.city'
        r'|(?:creep|xabber|jabb3r)\.im'
        r'|trashserver\.net'
        r')',
        re.IGNORECASE
    ),
    "discord": re.compile(
        r'(?:https?://)?discord\.gg/[a-zA-Z0-9]{2,16}',  # only invite links (strict)
        re.IGNORECASE
    ),
    "matrix": re.compile(
        r'@[a-zA-Z0-9._\-]+:[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}',
        re.IGNORECASE
    ),
    "keybase": re.compile(
        r'(?:'
        r'(?:https?://)?keybase\.io/[a-zA-Z0-9_]{1,16}'
        r'|keybase[\s:]+[a-zA-Z0-9_]{1,16}'
        r')',
        re.IGNORECASE
    ),
    "whatsapp": re.compile(
        r'(?:'
        r'(?:https?://)?wa\.me/\d{7,15}'
        r'|whatsapp[\s:]+\+?\d[\d\s\-]{8,15}'
        r')',
        re.IGNORECASE
    ),
    "element_riot": re.compile(
        r'(?:https?://)?(?:app\.element\.io|riot\.im)/[^\s<>"\']{5,}',
        re.IGNORECASE
    ),
    "threema": re.compile(
        r'threema[\s:]+[A-Z0-9*]{8}',
        re.IGNORECASE
    ),
    "briar": re.compile(
        r'briar[\s:]+briar://[a-zA-Z0-9]{40,}',
        re.IGNORECASE
    ),
    "simplex": re.compile(
        r'(?:https?://)?simplex\.chat/[^\s<>"\']{5,}',
        re.IGNORECASE
    ),

    # crypto-specific identifiers
    "tox_id": re.compile(
        r'\b[A-F0-9]{76}\b'  # TOX IDs are 76 hex chars uppercase
    ),
    "pgp_fingerprint": re.compile(
        r'\b(?:[A-F0-9]{4}\s+){9}[A-F0-9]{4}\b'  # spaced fingerprint
        r'|\b[A-F0-9]{40}\b'  # compact 40-char fingerprint
    ),
    "pgp_keyid": re.compile(
        r'\b0x[A-F0-9]{8,16}\b'  # PGP short/long key IDs
    ),

    # email services popular on dark web (actor contacts, not victim data)
    "protonmail": re.compile(
        r'[a-zA-Z0-9._%+\-]+@(?:protonmail\.com|proton\.me|pm\.me)',
        re.IGNORECASE
    ),
    "tutanota": re.compile(
        r'[a-zA-Z0-9._%+\-]+@(?:tutanota\.com|tutanota\.de|tuta\.io|tutamail\.com|keemail\.me)',
        re.IGNORECASE
    ),
    "onionmail": re.compile(
        r'[a-zA-Z0-9._%+\-]+@(?:onionmail\.org|dnmx\.org|dnmx\.su)',
        re.IGNORECASE
    ),
    "cock_li": re.compile(
        r'[a-zA-Z0-9._%+\-]+@(?:cock\.li|airmail\.cc|8chan\.co|national\.shitposting\.agency|tfwno\.gf)',
        re.IGNORECASE
    ),

    # forum/marketplace handles
    "forum_handle": re.compile(
        r'(?:(?:contact|dm|pm|message|reach|hit)\s*(?:me|us)?[\s:]+@[a-zA-Z0-9_]{3,30})',
        re.IGNORECASE
    ),

    # onion contact pages
    "onion_contact": re.compile(
        r'https?://[a-z2-7]{56}\.onion/(?:contact|support|pgp|about)',
        re.IGNORECASE
    ),

    # ICQ (still used in some eastern european cybercrime)
    "icq": re.compile(
        r'icq[\s:]+\d{5,12}',
        re.IGNORECASE
    ),

    # skype
    "skype": re.compile(
        r'skype[\s:]+[a-zA-Z0-9._\-]{3,32}',
        re.IGNORECASE
    ),
}


# false positive filters
DOMAIN_BLACKLIST = {
    "w3.org", "schema.org", "xmlns.com", "mozilla.org",
    "example.com", "example.org", "example.net",
    "google.com", "googleapis.com", "gstatic.com",
    "facebook.com", "twitter.com", "instagram.com",
    "cloudflare.com", "jquery.com", "bootstrapcdn.com",
    "fontawesome.com", "cdnjs.cloudflare.com",
    "fonts.googleapis.com", "fonts.gstatic.com",
    "ajax.googleapis.com", "maps.googleapis.com",
}

# private/reserved IP ranges to exclude
PRIVATE_IP_NETWORKS = [
    ipaddress.ip_network('10.0.0.0/8'),
    ipaddress.ip_network('127.0.0.0/8'),
    ipaddress.ip_network('172.16.0.0/12'),
    ipaddress.ip_network('192.168.0.0/16'),
    ipaddress.ip_network('169.254.0.0/16'),  # link-local
    ipaddress.ip_network('0.0.0.0/8'),
]

# labels that commonly appear before a colon but are NOT credentials
CREDENTIAL_FALSE_POSITIVE_LABELS = {
    "btc", "eth", "xmr", "ltc", "etc", "bch", "doge", "dash", "zec",
    "http", "https", "ftp", "ssh", "smtp", "imap",
    "title", "subject", "name", "date", "time", "type", "status",
    "description", "category", "version", "size", "format",
    "birth", "death", "marriage", "divorce",
    "country", "city", "state", "address", "phone",
    "color", "width", "height", "content", "charset",
    "utf-8", "iso-8859-1", "windows-1252",
    "chaddadgroup",
}

HASH_COMMON_FP = {
    "0" * 32, "f" * 32, "0" * 64, "f" * 64,
    "d41d8cd98f00b204e9800998ecf8427e",  # md5 of empty string
    "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",  # sha256 of empty
}

# common false positive telegram usernames (navigation elements, not contacts)
TELEGRAM_FP = {
    "bot", "share", "login", "joinchat", "addstickers",
    "setlanguage", "channel", "group", "username",
    "chat", "doxxing", "channels", "token", "grabber",
}

# jabber domains that are just the service itself, not actor contacts
JABBER_DOMAIN_FP = {"jabber.org", "xmpp.org"}


def extract_contacts(text: str) -> dict:
    """
    extract threat actor contact methods from text.
    returns dict of contact_type -> list of unique values
    """
    contacts = {}

    for contact_type, pattern in CONTACT_PATTERNS.items():
        matches = set(pattern.findall(text))

        # filter false positives
        if contact_type == "telegram":
            cleaned = set()
            for m in matches:
                handle = m.strip().lower()
                username = re.sub(r'^.*[/@]', '', handle)
                if username not in TELEGRAM_FP and len(username) >= 3:
                    cleaned.add(m.strip())
            matches = cleaned

        elif contact_type == "matrix":
            matches = {m for m in matches if ":" in m and not m.startswith("@.")}

        elif contact_type == "pgp_fingerprint":
            matches = {m for m in matches if len(m.replace(" ", "")) == 40}

        elif contact_type == "forum_handle":
            cleaned = set()
            for m in matches:
                handle_match = re.search(r'@([a-zA-Z0-9_]{3,30})', m)
                if handle_match:
                    cleaned.add("@" + handle_match.group(1))
            matches = cleaned

        if matches:
            contacts[contact_type] = sorted(matches)

    return contacts


def _get_context(text: str, match: str, window: int = 80) -> str:
    """
    extract surrounding text around a contact match to show what it's associated with.
    returns a cleaned context snippet.
    """
    pos = text.find(match)
    if pos == -1:
        pos = text.lower().find(match.lower())
    if pos == -1:
        return ""

    start = max(0, pos - window)
    end = min(len(text), pos + len(match) + window)
    snippet = text[start:end]

    # clean up the snippet
    snippet = ' '.join(snippet.split())  # normalize whitespace
    snippet = snippet.strip('., \t\n')

    # trim to avoid cutting mid-word
    if start > 0:
        first_space = snippet.find(' ')
        if first_space > 0 and first_space < 20:
            snippet = '...' + snippet[first_space:]
    if end < len(text):
        last_space = snippet.rfind(' ')
        if last_space > len(snippet) - 20:
            snippet = snippet[:last_space] + '...'

    return snippet


def extract_contacts_with_context(text: str, source_url: str = "") -> dict:
    """
    extract contacts AND their surrounding context from text.
    returns dict of contact_type -> list of {value, context} dicts
    """
    contacts = extract_contacts(text)
    enriched = {}

    for contact_type, values in contacts.items():
        enriched[contact_type] = []
        for val in values:
            context = _get_context(text, val)
            enriched[contact_type].append({
                "value": val,
                "context": context,
                "source": source_url,
            })

    return enriched


def _is_private_ip(ip_str: str) -> bool:
    """check if an IP address is in a private/reserved range"""
    try:
        ip = ipaddress.ip_address(ip_str)
        return any(ip in network for network in PRIVATE_IP_NETWORKS)
    except ValueError:
        return False


def _is_blacklisted_domain(domain: str) -> bool:
    """check if a domain or any of its parent domains are blacklisted"""
    domain_lower = domain.lower()
    if domain_lower in DOMAIN_BLACKLIST:
        return True
    # check parent domains (e.g., fonts.googleapis.com -> googleapis.com)
    parts = domain_lower.split('.')
    for i in range(1, len(parts) - 1):
        parent = '.'.join(parts[i:])
        if parent in DOMAIN_BLACKLIST:
            return True
    return False


def _is_valid_credential_pair(match_str: str) -> bool:
    """validate a potential credential pair to reduce false positives"""
    # split on : or |
    sep = ':' if ':' in match_str else '|'
    parts = match_str.split(sep, 1)
    if len(parts) != 2:
        return False

    left, right = parts[0].strip(), parts[1].strip()

    # left side must be at least 3 chars
    if len(left) < 3 or len(right) < 6:
        return False

    # reject if left side is a known label
    if left.lower() in CREDENTIAL_FALSE_POSITIVE_LABELS:
        return False

    # reject if right side looks like a URL
    if right.lower().startswith(('http://', 'https://', '//', 'ftp://')):
        return False

    # reject if right side contains .onion
    if '.onion' in right.lower():
        return False

    # reject if left is a pure protocol/scheme prefix
    if left.lower() in ('http', 'https', 'ftp', 'ssh'):
        return False

    # reject patterns like "Word|Word" (both capitalized words, likely labels)
    if sep == '|' and left[0].isupper() and right[0].isupper() and left.isalpha() and right.isalpha():
        return False

    return True


def _validate_btc_wallet(addr: str) -> bool:
    """basic validation for Bitcoin wallet addresses"""
    if addr.startswith('bc1'):
        return 42 <= len(addr) <= 62
    elif addr.startswith('1') or addr.startswith('3'):
        return 25 <= len(addr) <= 34
    return False


def _validate_eth_wallet(addr: str) -> bool:
    """basic validation for Ethereum wallet addresses"""
    return len(addr) == 42 and addr.startswith('0x')


def _validate_xmr_wallet(addr: str) -> bool:
    """basic validation for Monero wallet addresses"""
    return len(addr) == 95 and addr.startswith('4')


def _validate_ltc_wallet(addr: str) -> bool:
    """basic validation for Litecoin wallet addresses"""
    if addr.startswith('ltc1'):
        return 43 <= len(addr) <= 63
    elif addr.startswith(('L', 'M', '3')):
        return 26 <= len(addr) <= 34
    return False


def _extract_domain_from_url(url: str) -> str:
    """extract hostname from a URL, returns empty string on failure"""
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname
        if hostname:
            return hostname.lower()
    except Exception:
        pass
    return ""


def extract_iocs(text: str, source_url: str = "") -> dict:
    """
    extract indicators of compromise from text.
    returns dict of ioc_type -> list of unique values
    """
    iocs = {}
    url_domains = set()  # domains extracted from URLs, added to domain IOCs
    credential_emails = set()  # emails extracted from credential pairs

    for ioc_type, pattern in IOC_PATTERNS.items():
        matches = set(pattern.findall(text))

        # -- filter false positives per IOC type --

        if ioc_type == "domain":
            # normalize to lowercase and deduplicate
            matches = {m.lower() for m in matches}
            # filter .onion domains
            matches = {m for m in matches if not m.endswith('.onion')}
            # filter blacklisted domains (including subdomains)
            matches = {m for m in matches if not _is_blacklisted_domain(m)}

        elif ioc_type == "url":
            # remove onion URLs
            matches = {m for m in matches if '.onion' not in m.lower()}
            # remove the source url itself and common web resources
            matches = {m for m in matches if m != source_url
                      and not _is_blacklisted_domain(_extract_domain_from_url(m))}
            # extract domains from URLs for the domain IOC set
            for url in matches:
                domain = _extract_domain_from_url(url)
                if domain and not domain.endswith('.onion') and not _is_blacklisted_domain(domain):
                    url_domains.add(domain)

        elif ioc_type == "ipv4":
            # filter private/reserved IP addresses
            matches = {m for m in matches if not _is_private_ip(m)}

        elif ioc_type in ("md5_hash", "sha256_hash"):
            matches = {m for m in matches if m.lower() not in HASH_COMMON_FP}

        elif ioc_type == "email":
            # filter out obvious non-emails
            matches = {m for m in matches if not m.endswith(".png")
                      and not m.endswith(".jpg") and not m.endswith(".css")
                      and not m.endswith(".js") and not m.endswith(".svg")}

        elif ioc_type == "credential_pair":
            # validate each credential pair
            matches = {m for m in matches if _is_valid_credential_pair(m)}
            # extract emails from valid credential pairs
            for cred in matches:
                sep = ':' if ':' in cred else '|'
                left = cred.split(sep, 1)[0].strip()
                if '@' in left and '.' in left.split('@')[-1]:
                    credential_emails.add(left)

        elif ioc_type == "btc_wallet":
            matches = {m for m in matches if _validate_btc_wallet(m)}

        elif ioc_type == "eth_wallet":
            matches = {m for m in matches if _validate_eth_wallet(m)}

        elif ioc_type == "xmr_wallet":
            matches = {m for m in matches if _validate_xmr_wallet(m)}

        elif ioc_type == "ltc_wallet":
            matches = {m for m in matches if _validate_ltc_wallet(m)}

        elif ioc_type == "telegram_user":
            # findall returns tuples from groups, extract the non-empty group
            cleaned = set()
            for m in matches:
                if isinstance(m, tuple):
                    username = next((g for g in m if g), None)
                else:
                    username = m
                if username:
                    username = username.lower()
                    if username not in TELEGRAM_FP and len(username) >= 3:
                        cleaned.add(username)
            matches = cleaned

        if matches:
            iocs[ioc_type] = sorted(matches)

    # merge URL-extracted domains into domain IOCs
    if url_domains:
        existing_domains = set(iocs.get("domain", []))
        existing_domains.update(url_domains)
        iocs["domain"] = sorted(existing_domains)

    # merge credential-extracted emails into email IOCs
    if credential_emails:
        existing_emails = set(iocs.get("email", []))
        existing_emails.update(credential_emails)
        iocs["email"] = sorted(existing_emails)

    return iocs


def extract_all(text: str, source_url: str = "") -> dict:
    """
    extract both IOCs and threat actor contacts from text.
    returns dict with 'iocs' and 'contacts' keys
    """
    return {
        "iocs": extract_iocs(text, source_url),
        "contacts": extract_contacts(text),
    }


def extract_iocs_from_scraped(scraped_data: dict) -> dict:
    """
    extract IOCs from all scraped pages.
    returns dict of url -> {ioc_type: [values]}
    """
    all_iocs = {}
    total_count = 0

    for url, content in scraped_data.items():
        if content.startswith("[ERROR"):
            continue

        iocs = extract_iocs(content, source_url=url)
        if iocs:
            all_iocs[url] = iocs
            count = sum(len(v) for v in iocs.values())
            total_count += count

    return all_iocs


def extract_contacts_from_scraped(scraped_data: dict) -> dict:
    """
    extract threat actor contacts with context from all scraped pages.
    returns dict of url -> {contact_type: [{value, context, source}]}
    """
    all_contacts = {}

    for url, content in scraped_data.items():
        if content.startswith("[ERROR"):
            continue

        contacts = extract_contacts_with_context(content, source_url=url)
        if contacts:
            all_contacts[url] = contacts

    return all_contacts


def _onion_url_label(url: str) -> str:
    """convert a long onion URL into a short readable label."""
    try:
        parsed = urlparse(url)
        path = parsed.path.strip("/")
        if path:
            segments = [s for s in path.split("/") if s]
            label = " – ".join(segments[-2:]) if len(segments) >= 2 else segments[-1]
            return label.replace("-", " ").replace("_", " ").title()
        host = parsed.hostname or ""
        if host.endswith(".onion") and len(host) > 20:
            return host
        return host
    except Exception:
        return url


def format_iocs_summary(all_iocs: dict, all_contacts: dict = None, company_categories: dict = None) -> str:
    """format extracted IOCs and contacts into a combined markdown summary,
    grouped by source URL so all IOCs from the same page appear together.
    if company_categories is provided, splits into company-specific and general sections."""
    if not all_iocs and not all_contacts:
        return "No IOCs or contacts extracted."

    lines = []
    lines.append("## Indicators of Compromise (Auto-Extracted)")
    lines.append("")

    labels = {
        "email": "Email Addresses",
        "credential_pair": "Credential Pairs",
        "ipv4": "IP Addresses",
        "domain": "Domains",
        "url": "URLs",
        "telegram_user": "Telegram Users",
        "btc_wallet": "Bitcoin Wallets",
        "eth_wallet": "Ethereum Wallets",
        "xmr_wallet": "Monero Wallets",
        "ltc_wallet": "Litecoin Wallets",
        "md5_hash": "MD5 Hashes",
        "sha256_hash": "SHA-256 Hashes",
        "phone": "Phone Numbers",
        "credit_card": "Credit Card Numbers",
        "ssn": "SSN-like Patterns",
    }

    # Credential Pairs → Crypto Wallets → Emails → Telegram → Hashes → IPs → Domains → URLs
    ioc_display_order = [
        "credential_pair", "credit_card", "ssn",
        "btc_wallet", "eth_wallet", "xmr_wallet", "ltc_wallet",
        "email",
        "telegram_user",
        "md5_hash", "sha256_hash",
        "ipv4", "phone",
        "domain",
        "url",
    ]

    # ── aggregate totals ──
    totals = {}
    cs_totals = {}
    gen_totals = {}
    for url, iocs in (all_iocs or {}).items():
        rel = company_categories.get(url, "general") if company_categories else None
        for ioc_type, values in iocs.items():
            totals[ioc_type] = totals.get(ioc_type, 0) + len(values)
            if company_categories:
                if rel == "company_specific":
                    cs_totals[ioc_type] = cs_totals.get(ioc_type, 0) + len(values)
                else:
                    gen_totals[ioc_type] = gen_totals.get(ioc_type, 0) + len(values)

    grand_total = sum(totals.values())

    # ── top IOC summary ──
    if totals:
        lines.append("### IOC Summary")
        lines.append("")
        lines.append(f"**Total Indicators: {grand_total}** · **{len(all_iocs or {})} sources** scanned")
        if company_categories:
            cs_src = sum(1 for url in (all_iocs or {}) if company_categories.get(url) == "company_specific")
            gen_src = sum(1 for url in (all_iocs or {}) if company_categories.get(url) != "company_specific")
            cs_total = sum(cs_totals.values())
            gen_total = sum(gen_totals.values())
            lines.append(f"- **Company-Specific**: {cs_total} indicators from {cs_src} sources")
            lines.append(f"- **General Dark Web**: {gen_total} indicators from {gen_src} sources")
        lines.append("")
        for ioc_type in ioc_display_order:
            if ioc_type in totals:
                label = labels.get(ioc_type, ioc_type)
                lines.append(f"- **{label}**: {totals[ioc_type]}")
        lines.append("")

    # ── helper: render a group of IOC sources ──
    def _render_source_group(source_items, group_label=None):
        """render IOC tables for a list of (url, iocs) tuples."""
        if not source_items:
            if group_label:
                lines.append(f"*No {group_label.lower()} IOCs found.*")
                lines.append("")
            return

        sorted_sources = sorted(
            source_items,
            key=lambda x: sum(len(v) for v in x[1].values()),
            reverse=True
        )

        for url, iocs in sorted_sources:
            total = sum(len(v) for v in iocs.values())

            if ".onion" in url:
                label = _onion_url_label(url)
                lines.append(f'#### <a href="{url}" title="{url}">{label}</a> ({total} indicators)')
            else:
                lines.append(f"#### Source: {url} ({total} indicators)")

            # per-source type summary
            type_parts = []
            for ioc_type in ioc_display_order:
                if ioc_type in iocs:
                    type_parts.append(f"{labels.get(ioc_type, ioc_type)}: {len(iocs[ioc_type])}")
            if type_parts:
                lines.append("> " + " · ".join(type_parts))
            lines.append("")

            for ioc_type in ioc_display_order:
                if ioc_type not in iocs:
                    continue
                values = iocs[ioc_type]
                lbl = labels.get(ioc_type, ioc_type)

                if len(values) <= 8:
                    val_list = ", ".join(f"`{v}`" for v in sorted(values))
                    lines.append(f"- **{lbl}** ({len(values)}): {val_list}")
                else:
                    lines.append(f"- **{lbl}** ({len(values)}):")
                    lines.append("")
                    cols = 5
                    seps = " | ".join(["---"] * cols)
                    empty_hdr = " | ".join([" "] * cols)
                    lines.append(f"| {empty_hdr} |")
                    lines.append(f"| {seps} |")
                    sorted_vals = sorted(values)
                    for i in range(0, len(sorted_vals), cols):
                        row_vals = sorted_vals[i:i + cols]
                        cells = [f"`{v.replace(chr(124), chr(92) + chr(124))}`" for v in row_vals]
                        while len(cells) < cols:
                            cells.append("")
                        lines.append(f"| {' | '.join(cells)} |")
                    lines.append("")

            lines.append("")

    # ── IOCs grouped by source URL ──
    if all_iocs:
        lines.append("---")
        lines.append("")

        if company_categories:
            # split into company-specific and general
            cs_sources = [(url, iocs) for url, iocs in all_iocs.items()
                          if company_categories.get(url) == "company_specific"]
            gen_sources = [(url, iocs) for url, iocs in all_iocs.items()
                           if company_categories.get(url) != "company_specific"]

            lines.append('<div style="display: flex; gap: 24px; align-items: flex-start; flex-wrap: wrap;">')
            lines.append("")

            lines.append('<!-- LEFT COLUMN: COMPANY SPECIFIC -->')
            lines.append('<div style="flex: 1; min-width: 320px; background: rgba(0, 200, 255, 0.03); padding: 20px; padding-top: 1px; border-radius: 10px; border: 1px solid rgba(0, 200, 255, 0.1);">')
            lines.append("### 🏢 Company-Specific IOCs")
            lines.append("")
            _render_source_group(cs_sources, "company-specific")
            lines.append("</div>")

            lines.append("")
            lines.append('<!-- RIGHT COLUMN: GENERAL DARK WEB -->')
            lines.append('<div style="flex: 1; min-width: 320px; background: rgba(255, 255, 255, 0.02); padding: 20px; padding-top: 1px; border-radius: 10px; border: 1px solid rgba(255, 255, 255, 0.08);">')
            lines.append("### 🌐 General Dark Web IOCs")
            lines.append("")
            _render_source_group(gen_sources, "general")
            lines.append("</div>")

            lines.append("")
            lines.append("</div> <!-- END FLEXBOX WRAPPER -->")
            lines.append("")
        else:
            _render_source_group(list(all_iocs.items()))

    # ── threat actor contacts section ──
    if all_contacts:
        contact_agg = {}
        for url, contacts in all_contacts.items():
            for contact_type, items in contacts.items():
                if contact_type not in contact_agg:
                    contact_agg[contact_type] = {}
                for item in items:
                    val = item["value"] if isinstance(item, dict) else item
                    ctx = item.get("context", "") if isinstance(item, dict) else ""
                    if val not in contact_agg[contact_type]:
                        contact_agg[contact_type][val] = {"contexts": [], "sources": []}
                    if ctx and ctx not in contact_agg[contact_type][val]["contexts"]:
                        contact_agg[contact_type][val]["contexts"].append(ctx)
                    if url not in contact_agg[contact_type][val]["sources"]:
                        contact_agg[contact_type][val]["sources"].append(url)

        if contact_agg:
            contact_labels = {
                "telegram": "Telegram", "wickr": "Wickr", "signal": "Signal",
                "session": "Session", "jabber_xmpp": "Jabber/XMPP",
                "discord": "Discord", "matrix": "Matrix", "keybase": "Keybase",
                "whatsapp": "WhatsApp", "element_riot": "Element/Riot",
                "threema": "Threema", "briar": "Briar", "simplex": "SimpleX",
                "tox_id": "TOX ID", "pgp_fingerprint": "PGP Fingerprint",
                "pgp_keyid": "PGP Key ID", "protonmail": "ProtonMail",
                "tutanota": "Tutanota/Tuta", "onionmail": "OnionMail/DNMX",
                "cock_li": "cock.li", "forum_handle": "Forum Handle",
                "onion_contact": "Onion Contact Page", "icq": "ICQ", "skype": "Skype",
            }

            contact_order = [
                "telegram", "jabber_xmpp", "wickr", "session", "signal", "tox_id",
                "discord", "matrix", "keybase", "whatsapp", "element_riot",
                "threema", "briar", "simplex", "icq", "skype",
                "protonmail", "tutanota", "onionmail", "cock_li",
                "pgp_fingerprint", "pgp_keyid", "forum_handle", "onion_contact",
            ]

            lines.append("---")
            lines.append("## Threat Actor Contacts")
            lines.append("")

            for ct in contact_order:
                if ct in contact_agg:
                    label = contact_labels.get(ct, ct)
                    items = contact_agg[ct]
                    lines.append(f"#### {label} ({len(items)} found)")
                    lines.append("")
                    lines.append("| Contact | Context | Source(s) |")
                    lines.append("|---|---|---|")
                    for val, data in sorted(items.items()):
                        val_escaped = val.replace("|", "\\|")
                        ctx = ""
                        if data["contexts"]:
                            best_ctx = min(data["contexts"], key=len)
                            if len(best_ctx) > 500:
                                best_ctx = best_ctx[:500] + "..."
                            ctx = best_ctx.replace("|", "\\|").replace("\n", " ")
                        src_count = f"{len(data['sources'])} page(s)"
                        lines.append(f"| `{val_escaped}` | {ctx} | {src_count} |")
                    lines.append("")

    return "\n".join(lines)






def format_contacts_summary(all_contacts: dict) -> str:
    """format extracted threat actor contacts with context into a markdown summary"""
    if not all_contacts:
        return "No threat actor contacts extracted."

    lines = []
    lines.append("## 📬 Threat Actor Contacts (Auto-Extracted)")
    lines.append("")

    # aggregate across all sources, keeping context
    aggregated = {}  # contact_type -> {value: {contexts: [], sources: []}}
    for url, contacts in all_contacts.items():
        for contact_type, items in contacts.items():
            if contact_type not in aggregated:
                aggregated[contact_type] = {}
            for item in items:
                val = item["value"] if isinstance(item, dict) else item
                ctx = item.get("context", "") if isinstance(item, dict) else ""
                if val not in aggregated[contact_type]:
                    aggregated[contact_type][val] = {"contexts": [], "sources": []}
                if ctx and ctx not in aggregated[contact_type][val]["contexts"]:
                    aggregated[contact_type][val]["contexts"].append(ctx)
                if url not in aggregated[contact_type][val]["sources"]:
                    aggregated[contact_type][val]["sources"].append(url)

    labels = {
        "telegram": "📱 Telegram",
        "wickr": "💬 Wickr",
        "signal": "📶 Signal",
        "session": "🔒 Session",
        "jabber_xmpp": "💭 Jabber/XMPP",
        "discord": "🎮 Discord",
        "matrix": "🔷 Matrix",
        "keybase": "🔑 Keybase",
        "whatsapp": "📲 WhatsApp",
        "element_riot": "🟢 Element/Riot",
        "threema": "🟩 Threema",
        "briar": "🌿 Briar",
        "simplex": "🔐 SimpleX",
        "tox_id": "☠️ TOX ID",
        "pgp_fingerprint": "🔏 PGP Fingerprint",
        "pgp_keyid": "🔏 PGP Key ID",
        "protonmail": "📧 ProtonMail",
        "tutanota": "📧 Tutanota/Tuta",
        "onionmail": "🧅 OnionMail/DNMX",
        "cock_li": "📧 cock.li",
        "forum_handle": "👤 Forum Handle",
        "onion_contact": "🧅 Onion Contact Page",
        "icq": "💬 ICQ",
        "skype": "💬 Skype",
    }

    display_order = [
        "telegram", "jabber_xmpp", "wickr", "session", "signal", "tox_id",
        "discord", "matrix", "keybase", "whatsapp", "element_riot",
        "threema", "briar", "simplex", "icq", "skype",
        "protonmail", "tutanota", "onionmail", "cock_li",
        "pgp_fingerprint", "pgp_keyid",
        "forum_handle", "onion_contact",
    ]

    # overview table
    overview_rows = []
    for contact_type in display_order:
        if contact_type in aggregated:
            label = labels.get(contact_type, contact_type)
            overview_rows.append(f"| {label} | {len(aggregated[contact_type])} |")

    if overview_rows:
        lines.append("### Overview")
        lines.append("| Platform | Count |")
        lines.append("|---|---|")
        lines.extend(overview_rows)
        lines.append("")

    for contact_type in display_order:
        if contact_type in aggregated:
            label = labels.get(contact_type, contact_type)
            items = aggregated[contact_type]
            lines.append(f"### {label} ({len(items)} found)")
            lines.append("")
            lines.append("| Contact | Context | Sources |")
            lines.append("|---|---|---|")
            for val, data in sorted(items.items()):
                val_escaped = val.replace("|", "\\|")
                # pick the shortest non-empty context (most focused)
                ctx = ""
                if data["contexts"]:
                    best_ctx = min(data["contexts"], key=len)
                    if len(best_ctx) > 500:
                        best_ctx = best_ctx[:500] + "..."
                    ctx = best_ctx.replace("|", "\\|").replace("\n", " ")
                src_count = f"{len(data['sources'])} page(s)"
                lines.append(f"| `{val_escaped}` | {ctx} | {src_count} |")
            lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    # test with sample dark web text
    sample = """
    admin@company.com:password123
    john.doe@example.org:secretpass
    IP: 192.168.1.100
    bitcoin: 1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa
    hash: 5d41402abc4b2a76b9719d911017c592
    card: 4532-1234-5678-9012

    Contact me on telegram: @darkvendor99
    Or t.me/darkvendor99
    wickr me: ghostseller
    jabber: hackerman@jabber.de
    signal: +1-555-867-5309
    tg:@muzan_b
    hackteam@dnmx.su
    seller@protonmail.com
    PGP: 9C022BAB61127CE71B556C5D8C55E330107402F1
    ICQ: 748291034
    discord.gg/h4ck3rs
    """
    print("=== IOCs ===")
    iocs = extract_iocs(sample)
    for ioc_type, values in iocs.items():
        print(f"  {ioc_type}: {values}")

    print("\n=== CONTACTS ===")
    contacts = extract_contacts(sample)
    for contact_type, values in contacts.items():
        print(f"  {contact_type}: {values}")
