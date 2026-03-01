#!/bin/bash

# Start Tor in background
echo "[*] Starting Tor service..."
tor &
TOR_PID=$!

# Wait for Tor to bootstrap (check logs for "Bootstrapped 100%")
echo "[*] Waiting for Tor to connect..."
for i in $(seq 1 30); do
    if kill -0 $TOR_PID 2>/dev/null; then
        sleep 1
    else
        echo "[-] Tor process exited unexpectedly"
        exit 1
    fi
done

# Verify Tor process is still alive
if kill -0 $TOR_PID 2>/dev/null; then
    echo "[+] Tor is running (PID $TOR_PID)"
else
    echo "[-] Tor failed to start"
    exit 1
fi

# Start the FastAPI scraper service
echo "[*] Starting scraper service..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8002
