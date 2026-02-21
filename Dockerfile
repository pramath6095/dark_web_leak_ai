FROM python:3.11-slim

# Install Tor and build dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    tor \
    gcc \
    python3-dev \
    libffi-dev && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create output directory
RUN mkdir -p /app/output

# Make entrypoint executable
RUN chmod +x /app/entrypoint.sh

ENTRYPOINT ["/app/entrypoint.sh"]
