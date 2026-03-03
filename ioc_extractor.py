import re


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
        r'\b(?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)+(?:com|net|org|io|co|info|biz|xyz|onion|ru|cn|tk|cc|pw|top|site|online|live)\b',
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
        r'[a-zA-Z0-9._%+\-]+(?:@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})?[:\|][^\s]{3,}',
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


def extract_iocs(text: str, source_url: str = "") -> dict:
    """
    extract indicators of compromise from text.
    returns dict of ioc_type -> list of unique values
    """
    iocs = {}

    for ioc_type, pattern in IOC_PATTERNS.items():
        matches = set(pattern.findall(text))

        # filter false positives
        if ioc_type == "domain":
            matches = {m for m in matches if m.lower() not in DOMAIN_BLACKLIST}
        elif ioc_type in ("md5_hash", "sha256_hash"):
            matches = {m for m in matches if m.lower() not in HASH_COMMON_FP}
        elif ioc_type == "url":
            # remove the source url itself and common web resources
            matches = {m for m in matches if m != source_url
                      and "w3.org" not in m and "schema.org" not in m}
        elif ioc_type == "email":
            # filter out obvious non-emails
            matches = {m for m in matches if not m.endswith(".png")
                      and not m.endswith(".jpg") and not m.endswith(".css")}

        if matches:
            iocs[ioc_type] = sorted(matches)

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


def format_iocs_summary(all_iocs: dict) -> str:
    """format extracted IOCs into a readable text summary"""
    if not all_iocs:
        return "No IOCs extracted."

    lines = []
    lines.append("=" * 60)
    lines.append("INDICATORS OF COMPROMISE (Auto-Extracted)")
    lines.append("=" * 60)

    # aggregate across all sources
    aggregated = {}
    for url, iocs in all_iocs.items():
        for ioc_type, values in iocs.items():
            if ioc_type not in aggregated:
                aggregated[ioc_type] = {}
            for val in values:
                if val not in aggregated[ioc_type]:
                    aggregated[ioc_type][val] = []
                aggregated[ioc_type][val].append(url)

    # display label mapping
    labels = {
        "email": "Email Addresses",
        "credential_pair": "Credential Pairs",
        "ipv4": "IP Addresses",
        "domain": "Domains",
        "url": "URLs",
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

    for ioc_type in ["credential_pair", "email", "credit_card", "ssn", "btc_wallet",
                      "eth_wallet", "xmr_wallet", "ltc_wallet", "ipv4", "domain",
                      "phone", "md5_hash", "sha256_hash", "url"]:
        if ioc_type in aggregated:
            label = labels.get(ioc_type, ioc_type)
            items = aggregated[ioc_type]
            lines.append(f"\n{label} ({len(items)} found):")
            for val, sources in sorted(items.items())[:20]:  # cap display at 20 per type
                source_short = sources[0][:40] + "..." if len(sources[0]) > 40 else sources[0]
                lines.append(f"  • {val}  [from: {source_short}]")
            if len(items) > 20:
                lines.append(f"  ... and {len(items) - 20} more")

    return "\n".join(lines)


def format_contacts_summary(all_contacts: dict) -> str:
    """format extracted threat actor contacts with context into a readable summary"""
    if not all_contacts:
        return "No threat actor contacts extracted."

    lines = []
    lines.append("=" * 60)
    lines.append("THREAT ACTOR CONTACTS (Auto-Extracted)")
    lines.append("=" * 60)

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
        "telegram": "Telegram",
        "wickr": "Wickr",
        "signal": "Signal",
        "session": "Session",
        "jabber_xmpp": "Jabber/XMPP",
        "discord": "Discord",
        "matrix": "Matrix",
        "keybase": "Keybase",
        "whatsapp": "WhatsApp",
        "element_riot": "Element/Riot",
        "threema": "Threema",
        "briar": "Briar",
        "simplex": "SimpleX",
        "tox_id": "TOX ID",
        "pgp_fingerprint": "PGP Fingerprint",
        "pgp_keyid": "PGP Key ID",
        "protonmail": "ProtonMail",
        "tutanota": "Tutanota/Tuta",
        "onionmail": "OnionMail/DNMX",
        "cock_li": "cock.li",
        "forum_handle": "Forum Handle",
        "onion_contact": "Onion Contact Page",
        "icq": "ICQ",
        "skype": "Skype",
    }

    display_order = [
        "telegram", "jabber_xmpp", "wickr", "session", "signal", "tox_id",
        "discord", "matrix", "keybase", "whatsapp", "element_riot",
        "threema", "briar", "simplex", "icq", "skype",
        "protonmail", "tutanota", "onionmail", "cock_li",
        "pgp_fingerprint", "pgp_keyid",
        "forum_handle", "onion_contact",
    ]

    for contact_type in display_order:
        if contact_type in aggregated:
            label = labels.get(contact_type, contact_type)
            items = aggregated[contact_type]
            lines.append(f"\n{label} ({len(items)} found):")
            for val, data in sorted(items.items())[:15]:
                lines.append(f"  • {val}")
                # show the best context snippet
                if data["contexts"]:
                    # pick the shortest non-empty context (most focused)
                    best_ctx = min(data["contexts"], key=len)
                    if len(best_ctx) > 120:
                        best_ctx = best_ctx[:120] + "..."
                    lines.append(f"    Found near: \"{best_ctx}\"")
                lines.append(f"    Pages: {len(data['sources'])} source(s)")
            if len(items) > 15:
                lines.append(f"  ... and {len(items) - 15} more")

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
