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
        "md5_hash": "MD5 Hashes",
        "sha256_hash": "SHA-256 Hashes",
        "phone": "Phone Numbers",
        "credit_card": "Credit Card Numbers",
        "ssn": "SSN-like Patterns",
    }
    
    for ioc_type in ["credential_pair", "email", "credit_card", "ssn", "btc_wallet", 
                      "eth_wallet", "ipv4", "domain", "phone", "md5_hash", "sha256_hash", "url"]:
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


if __name__ == "__main__":
    # test with sample text
    sample = """
    admin@company.com:password123
    john.doe@example.org:secretpass
    IP: 192.168.1.100
    bitcoin: 1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa
    hash: 5d41402abc4b2a76b9719d911017c592
    card: 4532-1234-5678-9012
    """
    iocs = extract_iocs(sample)
    for ioc_type, values in iocs.items():
        print(f"{ioc_type}: {values}")
