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
import http.client
import json
import subprocess
import sys
import time

QUERY_SERVICE_HOST = "127.0.0.1"
QUERY_SERVICE_PORT = 8001
HEALTH_TIMEOUT = 300  # seconds to wait for services


# ── HTTP helpers (using http.client to avoid Python 3.14 SSL bug) ────────

def _http_get(path: str, timeout: float = 10.0) -> dict | None:
    """GET request to query service. Returns parsed JSON or None on error."""
    try:
        conn = http.client.HTTPConnection(
            QUERY_SERVICE_HOST, QUERY_SERVICE_PORT, timeout=timeout
        )
        conn.request("GET", path)
        resp = conn.getresponse()
        if resp.status == 200:
            return json.loads(resp.read().decode())
        conn.close()
    except Exception:
        pass
    return None


def _http_post(path: str, body: dict, timeout: float = 180.0) -> dict:
    """POST JSON to query service. Returns parsed JSON or raises."""
    data = json.dumps(body).encode("utf-8")
    conn = http.client.HTTPConnection(
        QUERY_SERVICE_HOST, QUERY_SERVICE_PORT, timeout=timeout
    )
    conn.request(
        "POST", path, body=data,
        headers={"Content-Type": "application/json"},
    )
    resp = conn.getresponse()
    result = json.loads(resp.read().decode())
    conn.close()
    if resp.status >= 400:
        raise RuntimeError(f"HTTP {resp.status}: {result}")
    return result


# ── CLI ──────────────────────────────────────────────────────────────────

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


# ── Docker helpers ───────────────────────────────────────────────────────

def _get_compose_cmd() -> list[str]:
    """Detect whether to use 'docker compose' (v2) or 'docker-compose' (v1)."""
    for cmd in [["docker", "compose", "version"], ["docker-compose", "version"]]:
        try:
            r = subprocess.run(cmd, capture_output=True)
            if r.returncode == 0:
                return cmd[:-1]
        except FileNotFoundError:
            continue
    return ["docker", "compose"]


_COMPOSE_CMD = _get_compose_cmd()


def stop_containers() -> None:
    """Shut down all containers."""
    print("\n[*] Stopping containers...")
    subprocess.run(
        [*_COMPOSE_CMD, "down"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    print("[+] Containers stopped.")


def start_containers() -> None:
    """Run docker-compose up -d --build with real-time output."""
    print("\n[*] Building and starting Docker containers...")
    print("[*] This may take several minutes on first run.\n")

    try:
        proc = subprocess.Popen(
            [*_COMPOSE_CMD, "up", "-d", "--build"],
            stdout=sys.stdout,
            stderr=sys.stderr,
        )
        returncode = proc.wait()
        if returncode == 0:
            print("\n[+] Containers started successfully!")
            return
    except FileNotFoundError:
        pass

    print("[-] Failed to start containers. Is Docker running?")
    sys.exit(1)


# ── Service interaction ─────────────────────────────────────────────────

def wait_for_service(service_name: str, timeout: int = HEALTH_TIMEOUT) -> None:
    """Wait until the query-generator /health endpoint responds."""
    print(f"[*] Waiting for {service_name} to be ready...", end="", flush=True)
    start = time.time()
    while time.time() - start < timeout:
        result = _http_get("/health")
        if result is not None:
            print(" ready!")
            return
        print(".", end="", flush=True)
        time.sleep(3)

    # Health check failed — show diagnostics
    elapsed = int(time.time() - start)
    print(f"\n[-] {service_name} did not become ready within {elapsed}s")
    print("\n[*] Container status:")
    subprocess.run([*_COMPOSE_CMD, "ps", "-a"], stdout=sys.stdout, stderr=sys.stderr)
    print(f"\n[*] {service_name} logs (last 20 lines):")
    subprocess.run(
        ["docker", "logs", "--tail", "20", "query-generator"],
        stdout=sys.stdout, stderr=sys.stderr,
    )
    stop_containers()
    sys.exit(1)


def configure_query_service(company_name: str, description: str) -> None:
    """POST company info to the query-generator service."""
    print(f"\n[*] Configuring query service for: '{company_name}'")
    print("[*] Generating queries via LLM (this may take a moment)...")
    try:
        data = _http_post(
            "/configure",
            {"company_name": company_name, "description": description},
        )
        print(f"[+] {data['message']}")
        print(f"    Queries generated: {data['queries_generated']}")
        print(f"    Search strings:    {data['search_strings_count']}")
    except Exception as exc:
        print(f"[-] Failed to configure query service: {exc}")
        stop_containers()
        sys.exit(1)


# ── Main ─────────────────────────────────────────────────────────────────

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

    try:
        # Step 1: Start containers
        start_containers()

        # Step 2: Wait for query-generator to be healthy
        wait_for_service("Query Generator")

        # Step 3: Configure with company info
        configure_query_service(company_name, description)

        print("\n" + "=" * 60)
        print("  System is now running autonomously!")
        print("  - Scraper is polling for queries and scraping the dark web")
        print("  - Analysis results are written to output/results.txt")
        print("  - Logs: logs/analysis.log")
        print("  ")
        print(f"  Stop with: {' '.join(_COMPOSE_CMD)} down")
        print("=" * 60 + "\n")

    except KeyboardInterrupt:
        print("\n\n[!] Interrupted by user.")
        stop_containers()
        sys.exit(1)


if __name__ == "__main__":
    main()
