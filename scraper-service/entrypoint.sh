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

# Start the FastAPI scraper service
echo "[*] Starting scraper service..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8002
