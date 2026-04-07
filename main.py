import os
import time
import argparse
import functools
print = functools.partial(print, flush=True)
from search import search_dark_web, save_results, get_urls_from_results, SEARCH_ENGINES
from scrape import scrape_all, save_scraped_data
from ioc_extractor import extract_iocs_from_scraped, extract_contacts_from_scraped, format_iocs_summary


def get_int_input(prompt: str, default: int, min_val: int = 1, max_val: int = None) -> int:
    while True:
        try:
            user_input = input(f"{prompt} [{default}]: ").strip()
            if not user_input:
                return default
            value = int(user_input)
            if value < min_val:
                print(f"  [!] Must be at least {min_val}")
                continue
            if max_val and value > max_val:
                print(f"  [!] Maximum is {max_val}")
                continue
            return value
        except ValueError:
            print("  [!] Please enter a valid number")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Dark Web Leak Monitor - AI-Powered OSINT Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py "data breach"
  python main.py "leaked passwords" -e 5 -l 10
  python main.py --no-ai "credentials"
  python main.py -t 10 -e 17 -l 20 "credentials"
        """
    )
    parser.add_argument("query", nargs="?", help="Search query")
    parser.add_argument("-t", "--threads", type=int, default=3, metavar="N",
                        help="Concurrent tasks (default: 3)")
    parser.add_argument("-e", "--engines", type=int, default=None, metavar="N",
                        help=f"Number of search engines (max: {len(SEARCH_ENGINES)})")
    parser.add_argument("-l", "--limit", type=int, default=None, metavar="N",
                        help="Max URLs to scrape")
    parser.add_argument("--no-ai", action="store_true",
                        help="Skip all AI stages (search + scrape only)")
    parser.add_argument("--no-download", action="store_true",
                        help="Skip file header download and analysis")
    parser.add_argument("-d", "--depth", type=int, default=2, choices=[1, 2],
                        help="Scrape depth: 1=landing page only, 2=follow up to 5 sublinks (default: 2)")
    parser.add_argument("-p", "--pages", type=int, default=1, metavar="N",
                        help="Max pages to follow per URL via pagination (default: 1, max: 10)")
    parser.add_argument("--check-engines", action="store_true",
                        help="Test which search engines are alive and exit")
    parser.add_argument("--dashboard", action="store_true",
                        help="Launch web dashboard instead of CLI")
    return parser.parse_args()


def save_summary(summary: str, filename: str = "output/summary.txt"):
    """save the ai-generated intelligence summary to file"""
    os.makedirs("output", exist_ok=True)
    with open(filename, "w", encoding="utf-8") as f:
        f.write(summary)
    print(f"[+] Intelligence summary saved to {filename}")


def main():
    args = parse_args()
    
    # handle special modes
    if args.check_engines:
        from search import check_engines
        check_engines()
        return
    
    if args.dashboard:
        try:
            from dashboard import app
            print("\n[+] Starting web dashboard on http://localhost:5000")
            app.run(host="0.0.0.0", port=5000, debug=True)
        except ImportError:
            print("[-] Flask not installed. Run: pip install flask")
        return
    
    total_engines = len(SEARCH_ENGINES)
    use_ai = not args.no_ai
    max_pages = min(args.pages, 10)  # cap at 10
    
    print("\n" + "=" * 50)
    print("   DARK WEB LEAK MONITOR")
    if use_ai:
        print("   AI-Powered Intelligence Pipeline")
    print("=" * 50)
    
    query = args.query
    if not query:
        query = input("\nEnter search query: ")
    
    if not query.strip():
        print("[-] Empty query. Exiting.")
        return
    
    # get engine count
    if args.engines is not None:
        num_engines = min(args.engines, total_engines)
    else:
        print(f"\n[*] Available search engines: {total_engines}")
        num_engines = get_int_input("How many search engines to use?", default=total_engines, max_val=total_engines)
    
    if args.limit is not None:
        scrape_limit = args.limit
    else:
        scrape_limit = get_int_input("How many URLs to scrape?", default=20)
    
    print("\n" + "-" * 50)
    print(f"   Engines: {num_engines}/{total_engines} | Threads: {args.threads} | Scrape: {scrape_limit}")
    print(f"   AI Pipeline: {'ENABLED' if use_ai else 'DISABLED'}")
    print("-" * 50)
    
    # ==========================================
    # STEP 1: AI QUERY REFINEMENT (if enabled)
    # ==========================================
    search_queries = [query]  # default: just original
    if use_ai:
        print("\n" + "-" * 50)
        print("STEP 1: AI QUERY REFINEMENT")
        print("-" * 50)
        
        from ai_engine import refine_query
        print(f"[*] Original query: {query}")
        keywords = refine_query(query)
        print(f"[+] AI-generated keywords:")
        for i, kw in enumerate(keywords, 1):
            print(f"    {i}. {kw}")
        
        # search all 3 AI keywords + original query for company-specific results
        search_queries = keywords + [query]
        print(f"[+] Will search {len(search_queries)} queries (3 AI + original)")
    
    # ==========================================
    # STEP 2: SEARCH DARK WEB
    # ==========================================
    step_num = 2 if use_ai else 1
    print("\n" + "-" * 50)
    print(f"STEP {step_num}: SEARCHING DARK WEB")
    print("-" * 50)
    
    all_search_results = []
    seen_urls = set()
    
    for i, sq in enumerate(search_queries, 1):
        # rate limit: delay between keyword searches to avoid getting blocked
        if i > 1:
            print(f"\n[*] Waiting 3s before next search (rate limit protection)...")
            time.sleep(3)
        
        label = "original" if sq == query and use_ai else f"keyword {i}"
        print(f"\n[*] Searching [{label}]: '{sq}'")
        batch = search_dark_web(sq, max_workers=args.threads, num_engines=num_engines)
        
        # merge + dedup
        new_count = 0
        for item in batch:
            url = item["url"] if isinstance(item, dict) else item
            if url not in seen_urls:
                seen_urls.add(url)
                all_search_results.append(item)
                new_count += 1
        print(f"  [+] {len(batch)} results ({new_count} new, {len(batch) - new_count} duplicates)")
    
    search_results = all_search_results
    
    if not search_results:
        print("\n[-] No results found. Check if Tor is running (port 9050/9150).")
        return
    
    save_results(search_results)
    print(f"\n[+] Total: {len(search_results)} unique results across {len(search_queries)} queries")
    
    # ==========================================
    # STEP 3: AI RESULT FILTERING (if enabled)
    # ==========================================
    if use_ai and len(search_results) > scrape_limit:
        step_num = 3
        print("\n" + "-" * 50)
        print(f"STEP {step_num}: AI RESULT FILTERING")
        print("-" * 50)
        
        from ai_engine import filter_results
        print(f"[*] Filtering {len(search_results)} results down to {scrape_limit}...")
        search_results = filter_results(query, search_results, limit=scrape_limit)
        print(f"[+] Selected top {len(search_results)} relevant results")
    
    # extract plain urls for scraper
    urls = get_urls_from_results(search_results)
    
    # ==========================================
    # STEP 4: SCRAPE CONTENT
    # ==========================================
    step_num = 4 if use_ai else 2
    print("\n" + "-" * 50)
    print(f"STEP {step_num}: SCRAPING CONTENT")
    print("-" * 50)
    
    urls_to_scrape = urls[:scrape_limit]
    print(f"[*] Scraping first {len(urls_to_scrape)} URLs...")
    
    scraped_data, html_cache = scrape_all(urls_to_scrape, max_workers=args.threads, depth=args.depth, max_pages=max_pages, target_query=query)
    save_scraped_data(scraped_data)
    
    # stats
    success = sum(1 for v in scraped_data.values() if not v.startswith("[ERROR"))
    dead_links = sum(1 for v in scraped_data.values() if "Dead link" in v)
    
    # ==========================================
    # STEP 4.5: IOC + CONTACT AUTO-EXTRACTION
    # ==========================================
    print("\n" + "-" * 50)
    print("IOC & CONTACT AUTO-EXTRACTION")
    print("-" * 50)
    all_iocs = extract_iocs_from_scraped(scraped_data)
    ioc_count = sum(len(v) for iocs in all_iocs.values() for v in iocs.values())
    print(f"[+] Extracted {ioc_count} IOCs from {len(all_iocs)} pages")
    
    # extract threat actor contacts
    all_contacts = extract_contacts_from_scraped(scraped_data)
    contact_count = sum(len(v) for contacts in all_contacts.values() for v in contacts.values())
    print(f"[+] Extracted {contact_count} threat actor contacts from {len(all_contacts)} pages")
    
    file_analysis = {}
    file_verdicts = {}
    company_categories = {}
    
    if use_ai and success > 0:
        # ==========================================
        # STEP 5: COMPANY CATEGORIZATION
        # ==========================================
        print("\n" + "-" * 50)
        print("STEP 5: COMPANY CATEGORIZATION")
        print("-" * 50)
        
        from ai_engine import categorize_company_relevance
        print(f"[*] Checking {success} pages for company relevance to \"{query}\"...")
        company_categories = categorize_company_relevance(query, scraped_data)
        
        if company_categories:
            cs_count = sum(1 for v in company_categories.values() if v == "company_specific")
            gen_count = sum(1 for v in company_categories.values() if v == "general")
            print(f"[+] Categorization results:")
            print(f"    Company-Specific: {cs_count}")
            print(f"    General: {gen_count}")

    # save IOCs + contacts (after company categorization if AI enabled)
    if all_iocs or all_contacts:
        ioc_text = format_iocs_summary(all_iocs, all_contacts, company_categories=company_categories or None)
        os.makedirs("output", exist_ok=True)
        with open("output/iocs.txt", "w", encoding="utf-8") as f:
            f.write(ioc_text)
        print(f"[+] IOCs + contacts saved to output/iocs.txt")

    if use_ai and success > 0:
        # ==========================================
        # STEP 5.5: AI THREAT CLASSIFICATION
        # ==========================================
        print("\n" + "-" * 50)
        print("STEP 5.5: AI THREAT CLASSIFICATION")
        print("-" * 50)
        
        from ai_engine import classify_threats
        print(f"[*] Classifying {success} scraped pages...")
        classifications = classify_threats(query, scraped_data, company_categories=company_categories)
        
        if classifications:
            # print classification summary grouped by company relevance
            cs_cls = {u: c for u, c in classifications.items() if c.get("company_relevance") == "company_specific"}
            gen_cls = {u: c for u, c in classifications.items() if c.get("company_relevance") != "company_specific"}
            
            if cs_cls:
                print(f"\n  [COMPANY-SPECIFIC] ({len(cs_cls)} pages):")
                cs_cats = {}
                for cls in cs_cls.values():
                    cat = cls.get("category", "other")
                    cs_cats[cat] = cs_cats.get(cat, 0) + 1
                for cat, count in sorted(cs_cats.items(), key=lambda x: -x[1]):
                    print(f"    {cat}: {count}")
            
            if gen_cls:
                print(f"\n  [GENERAL] ({len(gen_cls)} pages):")
                gen_cats = {}
                for cls in gen_cls.values():
                    cat = cls.get("category", "other")
                    gen_cats[cat] = gen_cats.get(cat, 0) + 1
                for cat, count in sorted(gen_cats.items(), key=lambda x: -x[1]):
                    print(f"    {cat}: {count}")
            
            cat_counts = {}
            sev_counts = {}
            for cls in classifications.values():
                cat = cls.get("category", "other")
                sev = cls.get("severity", "low")
                cat_counts[cat] = cat_counts.get(cat, 0) + 1
                sev_counts[sev] = sev_counts.get(sev, 0) + 1
            
            print(f"\n[+] Severity breakdown:")
            for sev in ["critical", "high", "medium", "low"]:
                if sev in sev_counts:
                    print(f"    {sev}: {sev_counts[sev]}")
        else:
            classifications = {}
        
        # ==========================================
        # STEP 5.5: FILE HEADER ANALYSIS
        # ==========================================
        if not args.no_download and classifications:
            print("\n" + "-" * 50)
            print("STEP 5.5: FILE HEADER ANALYSIS")
            print("-" * 50)
            
            try:
                from file_analyzer import analyze_threat_files, format_file_analysis
                print(f"[*] Scanning threat pages for downloadable files...")
                file_analysis = analyze_threat_files(html_cache, classifications, max_workers=args.threads)
                
                if file_analysis:
                    print(f"\n[+] Analyzed {len(file_analysis)} files")
                    
                    # ==========================================
                    # STEP 5.7: AI FILE VERIFICATION
                    # ==========================================
                    print("\n" + "-" * 50)
                    print("STEP 5.7: AI FILE VERIFICATION")
                    print("-" * 50)
                    
                    from ai_engine import verify_threat_files
                    print(f"[*] Verifying {len(file_analysis)} files with AI...")
                    file_verdicts = verify_threat_files(query, file_analysis)
                    
                    if file_verdicts:
                        # print verdict summary
                        verdict_counts = {}
                        for v in file_verdicts.values():
                            vd = v.get('verdict', 'inconclusive')
                            verdict_counts[vd] = verdict_counts.get(vd, 0) + 1
                        
                        print(f"[+] File verdicts:")
                        for vd, count in sorted(verdict_counts.items(), key=lambda x: -x[1]):
                            print(f"    {vd}: {count}")
                    
                    # save file analysis report
                    report = format_file_analysis(file_analysis, file_verdicts)
                    os.makedirs("output", exist_ok=True)
                    with open("output/file_analysis.txt", "w", encoding="utf-8") as f:
                        f.write(report)
                    print(f"[+] File analysis saved to output/file_analysis.txt")
                else:
                    print("[*] No downloadable files found on threat pages")
            except Exception as e:
                print(f"[!] File analysis failed: {str(e)[:100]}")
                import traceback
                traceback.print_exc()
        
        # ==========================================
        # STEP 7: AI INTELLIGENCE SUMMARY
        # ==========================================
        print("\n" + "-" * 50)
        print("STEP 7: AI INTELLIGENCE SUMMARY")
        print("-" * 50)
        
        from ai_engine import generate_summary
        print("[*] Generating incident response brief...")
        summary = generate_summary(query, scraped_data, classifications, regex_iocs=all_iocs, actor_contacts=all_contacts, company_categories=company_categories)
        save_summary(summary)
    
    # ==========================================
    # FINAL SUMMARY
    # ==========================================
    print("\n" + "=" * 50)
    print("PIPELINE COMPLETE")
    print("=" * 50)
    print(f"  - Search Query: {query}")
    if use_ai and len(search_queries) > 1:
        print(f"  - AI Keywords: {', '.join(search_queries[:-1])}")
        print(f"  - Queries Searched: {len(search_queries)} (3 AI + original)")
    print(f"  - Search Engines: {num_engines}/{total_engines}")
    print(f"  - Concurrent Tasks: {args.threads}")
    print(f"  - AI Pipeline: {'ENABLED' if use_ai else 'DISABLED'}")
    print(f"  - File Analysis: {'ENABLED' if (use_ai and not args.no_download) else 'DISABLED'}")
    print(f"  - Scrape Depth: {args.depth}")
    print(f"  - Circuit Isolation: ENABLED")
    print(f"  - HEAD Pre-checks: ENABLED")
    if max_pages > 1:
        print(f"  - Pagination: up to {max_pages} pages/URL")
    print(f"  - Results Found: {len(search_results)}")
    print(f"  - Dead Links Skipped: {dead_links}")
    print(f"  - URLs Scraped: {success}/{len(urls_to_scrape)}")
    print(f"  - IOCs Extracted: {ioc_count}")
    print(f"  - Actor Contacts: {contact_count}")
    if file_analysis:
        confirmed = sum(1 for v in file_verdicts.values() if v.get('verdict') == 'confirmed_threat')
        print(f"  - Files Analyzed: {len(file_analysis)}")
        print(f"  - Confirmed Threats: {confirmed}")
    if company_categories:
        target_specific = sum(1 for v in company_categories.values() if v == 'company_specific')
        generic = sum(1 for v in company_categories.values() if v == 'general')
        print(f"  - Company-Specific: {target_specific}")
        print(f"  - General: {generic}")
    print(f"  - Output:")
    print(f"      results.txt, scraped_data.txt, iocs.txt")
    if file_analysis:
        print(f"      file_analysis.txt")
    if use_ai and success > 0:
        print(f"      summary.txt")
    print("=" * 50 + "\n")


if __name__ == "__main__":
    main()
