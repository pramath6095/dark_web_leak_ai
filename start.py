"""start.py — One-command launcher for the AIDarkLeak system.

Usage:
    python start.py "CompanyName" "Detailed description of the company..."
    python start.py --file company_info.txt

The company info text file format:
    Line 1: Company name
    Lines 2+: Detailed description

This script:
1. Starts all Docker containers via docker-compose
2. Waits for services to become healthy
3. Sends company info to the query-generator via POST /configure
4. The system then runs autonomously (scraper polls → scrapes → analysis → results)
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time

import httpx

QUERY_SERVICE_URL = "http://localhost:8001"
HEALTH_TIMEOUT = 120  # seconds to wait for services


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="AIDarkLeak — Dark Web Leak Monitor",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python start.py "Acme Corp" "Acme Corp is a tech company at acme.com"
  python start.py --file company_info.txt
        """,
    )
    parser.add_argument("company_name", nargs="?", help="Company name")
    parser.add_argument("description", nargs="?", default="", help="Company description")
    parser.add_argument(
        "--file", "-f",
        help="Path to a text file (line 1 = name, rest = description)",
    )
    return parser.parse_args()


def load_from_file(filepath: str) -> tuple[str, str]:
    """Read company info from a text file."""
    with open(filepath, "r", encoding="utf-8") as f:
        lines = f.read().strip().splitlines()
    if not lines:
        print("[-] Company info file is empty")
        sys.exit(1)
    name = lines[0].strip()
    description = "\n".join(lines[1:]).strip()
    return name, description


def start_containers() -> None:
    """Run docker-compose up -d."""
    print("\n[*] Starting Docker containers...")
    result = subprocess.run(
        ["docker-compose", "up", "-d", "--build"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        # Try docker compose (v2) if docker-compose fails
        result = subprocess.run(
            ["docker", "compose", "up", "-d", "--build"],
            capture_output=True,
            text=True,
        )
    if result.returncode != 0:
        print(f"[-] Failed to start containers:\n{result.stderr}")
        sys.exit(1)
    print("[+] Containers starting...")


def wait_for_service(url: str, service_name: str, timeout: int = HEALTH_TIMEOUT) -> None:
    """Wait until a service's /health endpoint responds."""
    print(f"[*] Waiting for {service_name} to be ready...", end="", flush=True)
    start = time.time()
    while time.time() - start < timeout:
        try:
            resp = httpx.get(f"{url}/health", timeout=5.0)
            if resp.status_code == 200:
                print(" ready!")
                return
        except Exception:
            pass
        print(".", end="", flush=True)
        time.sleep(2)
    print(f"\n[-] {service_name} did not become ready within {timeout}s")
    sys.exit(1)


def configure_query_service(company_name: str, description: str) -> None:
    """POST company info to the query-generator service."""
    print(f"\n[*] Configuring query service for: '{company_name}'")
    resp = httpx.post(
        f"{QUERY_SERVICE_URL}/configure",
        json={"company_name": company_name, "description": description},
        timeout=120.0,  # LLM calls can be slow
    )
    resp.raise_for_status()
    data = resp.json()
    print(f"[+] {data['message']}")
    print(f"    Queries generated: {data['queries_generated']}")
    print(f"    Search strings:    {data['search_strings_count']}")


def main() -> None:
    args = parse_args()

    # Get company info
    if args.file:
        company_name, description = load_from_file(args.file)
    elif args.company_name:
        company_name = args.company_name
        description = args.description
    else:
        print("Usage: python start.py <company_name> [description]")
        print("       python start.py --file company_info.txt")
        sys.exit(1)

    print("=" * 60)
    print("  AIDarkLeak — Dark Web Leak Monitor")
    print("=" * 60)
    print(f"  Company: {company_name}")
    print(f"  Description: {description[:80]}{'...' if len(description) > 80 else ''}")
    print("=" * 60)

    # Step 1: Start containers
    start_containers()

    # Step 2: Wait for query-generator to be healthy
    wait_for_service(QUERY_SERVICE_URL, "Query Generator")

    # Step 3: Configure with company info
    configure_query_service(company_name, description)

    print("\n" + "=" * 60)
    print("  System is now running autonomously!")
    print("  - Scraper is polling for queries and scraping the dark web")
    print("  - Analysis results are written to output/results.txt")
    print("  - Logs: logs/analysis.log")
    print("  ")
    print("  Stop with: docker-compose down")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
