"""
Dark Web Leak Monitor
Main entry point - Search and Scrape dark web content
"""
import argparse
from search import search_dark_web, save_results
from scrape import load_urls, scrape_all, save_scraped_data


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Dark Web Leak Monitor - Search and scrape .onion sites",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py "data breach"              # Search with default 3 threads
  python main.py "leaked passwords" -t 5    # Search with 5 threads
  python main.py -t 10 -l 15 "credentials"  # 10 threads, scrape 15 URLs
        """
    )
    parser.add_argument(
        "query",
        nargs="?",
        help="Search query (interactive prompt if not provided)"
    )
    parser.add_argument(
        "-t", "--threads",
        type=int,
        default=3,
        metavar="N",
        help="Number of concurrent tasks (default: 3). Each task uses a different Tor circuit."
    )
    parser.add_argument(
        "-l", "--limit",
        type=int,
        default=10,
        metavar="N",
        help="Maximum number of URLs to scrape (default: 10)"
    )
    return parser.parse_args()


def main():
    args = parse_args()
    
    print("\n" + "=" * 50)
    print("   DARK WEB LEAK MONITOR")
    print("=" * 50)
    print(f"   Threads: {args.threads} | Scrape Limit: {args.limit}")
    print("=" * 50)
    
    # Step 1: Get search query
    query = args.query
    if not query:
        query = input("\nEnter search query: ")
    
    if not query.strip():
        print("[-] Empty query. Exiting.")
        return
    
    # Step 2: Search dark web
    print("\n" + "-" * 50)
    print("STEP 1: SEARCHING DARK WEB")
    print("-" * 50)
    urls = search_dark_web(query, max_workers=args.threads)
    
    if not urls:
        print("\n[-] No results found. Check if Tor is running (port 9050/9150).")
        return
    
    # Save results
    save_results(urls)
    print(f"[+] Found {len(urls)} unique URLs")
    
    # Step 3: Scrape content
    print("\n" + "-" * 50)
    print("STEP 2: SCRAPING CONTENT")
    print("-" * 50)
    
    # Limit URLs to scrape
    urls_to_scrape = urls[:args.limit]
    print(f"[*] Scraping first {len(urls_to_scrape)} URLs...")
    
    results = scrape_all(urls_to_scrape, max_workers=args.threads)
    save_scraped_data(results)
    
    # Summary
    success = sum(1 for v in results.values() if not v.startswith("[ERROR"))
    dead_links = sum(1 for v in results.values() if "Dead link" in v)
    print("\n" + "=" * 50)
    print("SUMMARY")
    print("=" * 50)
    print(f"  - Search Query: {query}")
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
