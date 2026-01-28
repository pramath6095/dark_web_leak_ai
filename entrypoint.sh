#!/bin/bash

# Start Tor in background
echo "[*] Starting Tor service..."
tor &

# Wait for Tor to bootstrap
echo "[*] Waiting for Tor to connect..."
sleep 10

# Check if Tor is running
if pgrep -x "tor" > /dev/null; then
    echo "[+] Tor is running on port 9050"
else
    echo "[-] Failed to start Tor"
    exit 1
fi

# Run the main application with provided query or prompt for input
if [ $# -gt 0 ]; then
    echo "[*] Running search with query: $@"
    python main.py "$@"
else
    echo "[*] Running in interactive mode"
    python main.py
fi
