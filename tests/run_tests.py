"""ASCII-safe test runner for debugging."""
import sys, os, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ioc_extractor import extract_iocs

def run():
    passed = failed = 0
    failures = []

    def check(name, condition, msg=""):
        nonlocal passed, failed
        if condition:
            print(f"  PASS {name}")
            passed += 1
        else:
            print(f"  FAIL {name}: {msg}")
            failed += 1
            failures.append(name)

    # 1. onion URLs
    iocs = extract_iocs("https://darkleak-site.com/login http://abcdef1234567890.onion/page")
    urls = iocs.get("url", [])
    check("onion_url_excluded", not any(".onion" in u for u in urls), f"urls={urls}")
    check("non_onion_url_kept", any("darkleak-site.com" in u for u in urls), f"urls={urls}")

    # 2. onion domains
    iocs = extract_iocs("abcdef1234567890.onion darkleak-site.com")
    domains = iocs.get("domain", [])
    check("onion_domain_excluded", not any(".onion" in d for d in domains), f"domains={domains}")

    # 3. domain from URL
    iocs = extract_iocs("https://malicious-site.com/panel/login")
    check("domain_from_url", "malicious-site.com" in iocs.get("domain", []), f"domains={iocs.get('domain',[])}")

    # 4. private IPs
    iocs = extract_iocs("192.168.1.5 10.0.0.1 127.0.0.1 172.16.5.3 185.220.101.25")
    ips = iocs.get("ipv4", [])
    check("public_ip_kept", "185.220.101.25" in ips, f"ips={ips}")
    check("private_192_filtered", "192.168.1.5" not in ips, f"ips={ips}")
    check("private_10_filtered", "10.0.0.1" not in ips, f"ips={ips}")
    check("private_127_filtered", "127.0.0.1" not in ips, f"ips={ips}")
    check("private_172_filtered", "172.16.5.3" not in ips, f"ips={ips}")

    # 5. credential pairs
    iocs = extract_iocs("admin@corp.com:Password123")
    creds = iocs.get("credential_pair", [])
    check("valid_cred_detected", any("admin@corp.com" in c for c in creds), f"creds={creds}")

    iocs = extract_iocs("title: hacking tutorial")
    creds = iocs.get("credential_pair", [])
    check("title_fp_rejected", not any("title" in c.lower() for c in creds), f"creds={creds}")

    iocs = extract_iocs("BTC:1JdvS63gBEFH3auYStgeSB3Q2xMdi5cZiF")
    creds = iocs.get("credential_pair", [])
    check("btc_label_rejected", not any("BTC:" in c for c in creds), f"creds={creds}")

    # 6. telegram
    iocs = extract_iocs("contact us at t.me/darkvendor99")
    check("tg_tme", "darkvendor99" in iocs.get("telegram_user", []), f"tg={iocs.get('telegram_user',[])}")

    iocs = extract_iocs("telegram: @darkvendor99")
    check("tg_at", "darkvendor99" in iocs.get("telegram_user", []), f"tg={iocs.get('telegram_user',[])}")

    iocs = extract_iocs("tg:@muzan_b")
    check("tg_tg", "muzan_b" in iocs.get("telegram_user", []), f"tg={iocs.get('telegram_user',[])}")

    # 7. domain normalization
    iocs = extract_iocs("DarkLeak.COM darkleak.com DARKLEAK.COM")
    domains = iocs.get("domain", [])
    check("domain_normalized", domains.count("darkleak.com") == 1, f"domains={domains}")

    # 8. crypto wallets
    iocs = extract_iocs("1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa")
    check("valid_btc", "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa" in iocs.get("btc_wallet", []),
          f"btc={iocs.get('btc_wallet',[])}")

    iocs = extract_iocs("0x9e2f075d3fff657695dc4661f42115588ee13263")
    check("valid_eth", "0x9e2f075d3fff657695dc4661f42115588ee13263" in iocs.get("eth_wallet", []),
          f"eth={iocs.get('eth_wallet',[])}")

    # 9. blacklist
    iocs = extract_iocs("w3.org schema.org mozilla.org")
    domains = iocs.get("domain", [])
    check("blacklist_filtered", "w3.org" not in domains and "schema.org" not in domains, f"domains={domains}")

    iocs = extract_iocs("fonts.googleapis.com")
    domains = iocs.get("domain", [])
    check("blacklist_subdomain", "fonts.googleapis.com" not in domains, f"domains={domains}")

    # 10. email from cred
    iocs = extract_iocs("admin@corp.com:Password123")
    check("email_from_cred", "admin@corp.com" in iocs.get("email", []), f"emails={iocs.get('email',[])}")

    print(f"\n{passed} passed, {failed} failed")
    if failures:
        print(f"Failures: {', '.join(failures)}")
    return failed

if __name__ == "__main__":
    sys.exit(run())
