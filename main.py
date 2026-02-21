import argparse
from search import search_dark_web, save_results, SEARCH_ENGINES
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
        description="Dark Web Leak Monitor - Search and scrape .onion sites",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py "data breach"
  python main.py "leaked passwords" -e 5 -l 10
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
    return parser.parse_args()


def main():
    args = parse_args()
    total_engines = len(SEARCH_ENGINES)
    
    print("\n" + "=" * 50)
    print("   DARK WEB LEAK MONITOR")
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
    print("-" * 50)
    
    # search
    print("\n" + "-" * 50)
    print("STEP 1: SEARCHING DARK WEB")
    print("-" * 50)
    urls = search_dark_web(query, max_workers=args.threads, num_engines=num_engines)
    
    if not urls:
        print("\n[-] No results found. Check if Tor is running (port 9050/9150).")
        return
    
    save_results(urls)
    print(f"[+] Found {len(urls)} unique URLs")
    
    # scrape
    print("\n" + "-" * 50)
    print("STEP 2: SCRAPING CONTENT")
    print("-" * 50)
    
    urls_to_scrape = urls[:scrape_limit]
    print(f"[*] Scraping first {len(urls_to_scrape)} URLs...")
    
    results = scrape_all(urls_to_scrape, max_workers=args.threads)
    save_scraped_data(results)
    
    # summary
    success = sum(1 for v in results.values() if not v.startswith("[ERROR"))
    dead_links = sum(1 for v in results.values() if "Dead link" in v)
    print("\n" + "=" * 50)
    print("SUMMARY")
    print("=" * 50)
    print(f"  - Search Query: {query}")
    print(f"  - Search Engines Used: {num_engines}/{total_engines}")
    print(f"  - Concurrent Tasks: {args.threads}")
    print(f"  - Mode: ASYNC (aiohttp)")
    print(f"  - Circuit Isolation: ENABLED")
    print(f"  - HEAD Pre-checks: ENABLED")
    print(f"  - URLs Found: {len(urls)}")
    print(f"  - Dead Links Skipped: {dead_links}")
    print(f"  - URLs Scraped: {success}/{len(urls_to_scrape)}")
    print(f"  - Results saved to: output/results.txt")
    print(f"  - Scraped data saved to: output/scraped_data.txt")
    print("=" * 50 + "\n")


if __name__ == "__main__":
    main()
