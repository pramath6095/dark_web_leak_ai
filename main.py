"""
Dark Web Leak Monitor
Main entry point - Search and Scrape dark web content
"""
import sys
from search import search_dark_web, save_results
from scrape import load_urls, scrape_all, save_scraped_data


def main():
    print("\n" + "=" * 50)
    print("   DARK WEB LEAK MONITOR")
    print("=" * 50)
    
    # Step 1: Get search query
    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
    else:
        query = input("\nEnter search query: ")
    
    if not query.strip():
        print("[-] Empty query. Exiting.")
        return
    
    # Step 2: Search dark web
    print("\n" + "-" * 50)
    print("STEP 1: SEARCHING DARK WEB")
    print("-" * 50)
    urls = search_dark_web(query)
    
    if not urls:
        print("\n[-] No results found. Check if Tor is running (port 9050).")
        return
    
    # Save results
    save_results(urls)
    print(f"[+] Found {len(urls)} unique URLs")
    
    # Step 3: Scrape content
    print("\n" + "-" * 50)
    print("STEP 2: SCRAPING CONTENT")
    print("-" * 50)
    
    # Limit to first 10 URLs for safety/speed
    urls_to_scrape = urls[:10]
    print(f"[*] Scraping first {len(urls_to_scrape)} URLs...")
    
    results = scrape_all(urls_to_scrape)
    save_scraped_data(results)
    
    # Summary
    success = sum(1 for v in results.values() if not v.startswith("[ERROR"))
    print("\n" + "=" * 50)
    print("SUMMARY")
    print("=" * 50)
    print(f"  - Search Query: {query}")
    print(f"  - URLs Found: {len(urls)}")
    print(f"  - URLs Scraped: {success}/{len(urls_to_scrape)}")
    print(f"  - Results saved to: results.txt")
    print(f"  - Scraped data saved to: scraped_data.txt")
    print("=" * 50 + "\n")


if __name__ == "__main__":
    main()
