import os
import argparse
from search import search_dark_web, save_results, get_urls_from_results, SEARCH_ENGINES
from scrape import load_urls, scrape_all, save_scraped_data


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
    return parser.parse_args()


def save_summary(summary: str, filename: str = "output/summary.txt"):
    """save the ai-generated intelligence summary to file"""
    os.makedirs("output", exist_ok=True)
    with open(filename, "w", encoding="utf-8") as f:
        f.write(summary)
    print(f"[+] Intelligence summary saved to {filename}")


def main():
    args = parse_args()
    total_engines = len(SEARCH_ENGINES)
    use_ai = not args.no_ai
    
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
        scrape_limit = get_int_input("How many URLs to scrape?", default=10)
    
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
    if use_ai and len(search_results) > 20:
        step_num = 3
        print("\n" + "-" * 50)
        print(f"STEP {step_num}: AI RESULT FILTERING")
        print("-" * 50)
        
        from ai_engine import filter_results
        print(f"[*] Filtering {len(search_results)} results...")
        search_results = filter_results(search_query, search_results)
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
    
    scraped_data = scrape_all(urls_to_scrape, max_workers=args.threads)
    save_scraped_data(scraped_data)
    
    # stats
    success = sum(1 for v in scraped_data.values() if not v.startswith("[ERROR"))
    dead_links = sum(1 for v in scraped_data.values() if "Dead link" in v)
    
    if use_ai and success > 0:
        # ==========================================
        # STEP 5: AI THREAT CLASSIFICATION
        # ==========================================
        print("\n" + "-" * 50)
        print("STEP 5: AI THREAT CLASSIFICATION")
        print("-" * 50)
        
        from ai_engine import classify_threats
        print(f"[*] Classifying {success} scraped pages...")
        classifications = classify_threats(query, scraped_data)
        
        if classifications:
            # print classification summary
            cat_counts = {}
            sev_counts = {}
            for cls in classifications.values():
                cat = cls.get("category", "other")
                sev = cls.get("severity", "low")
                cat_counts[cat] = cat_counts.get(cat, 0) + 1
                sev_counts[sev] = sev_counts.get(sev, 0) + 1
            
            print(f"[+] Classified {len(classifications)} pages:")
            for cat, count in sorted(cat_counts.items(), key=lambda x: -x[1]):
                print(f"    {cat}: {count}")
            print(f"[+] Severity breakdown:")
            for sev in ["critical", "high", "medium", "low"]:
                if sev in sev_counts:
                    print(f"    {sev}: {sev_counts[sev]}")
        else:
            classifications = {}
        
        # ==========================================
        # STEP 6: AI INTELLIGENCE SUMMARY
        # ==========================================
        print("\n" + "-" * 50)
        print("STEP 6: AI INTELLIGENCE SUMMARY")
        print("-" * 50)
        
        from ai_engine import generate_summary
        print("[*] Generating incident response brief...")
        summary = generate_summary(query, scraped_data, classifications)
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
    print(f"  - Circuit Isolation: ENABLED")
    print(f"  - HEAD Pre-checks: ENABLED")
    print(f"  - Results Found: {len(search_results)}")
    print(f"  - Dead Links Skipped: {dead_links}")
    print(f"  - URLs Scraped: {success}/{len(urls_to_scrape)}")
    print(f"  - Results: output/results.txt")
    print(f"  - Scraped data: output/scraped_data.txt")
    if use_ai and success > 0:
        print(f"  - Intelligence summary: output/summary.txt")
    print("=" * 50 + "\n")


if __name__ == "__main__":
    main()
