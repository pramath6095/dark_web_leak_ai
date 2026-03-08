#!/bin/bash

# Start Tor in background
echo "[*] Starting Tor service..."
tor &

# Wait for Tor to actually be ready (check SOCKS port)
echo "[*] Waiting for Tor to connect..."
MAX_WAIT=60
WAITED=0

while ! (echo > /dev/tcp/127.0.0.1/9050) 2>/dev/null; do
    if [ $WAITED -ge $MAX_WAIT ]; then
        echo "[-] Tor failed to start after ${MAX_WAIT}s"
        exit 1
    fi
    sleep 2
    WAITED=$((WAITED + 2))
    echo "[*] Waiting... (${WAITED}s)"
done

echo "[+] Tor is running on port 9050 (took ${WAITED}s)"

# Run the main application with provided query or prompt for input
if [ $# -gt 0 ]; then
    echo "[*] Running search with query: $@"
    python main.py "$@"
else
    echo "[*] Running in interactive mode"
    python main.py
fi
