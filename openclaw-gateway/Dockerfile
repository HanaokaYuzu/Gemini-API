FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy parent project requirements first
COPY ../requirements.txt /app/parent-requirements.txt
COPY requirements.txt /app/gateway-requirements.txt

# Install Python dependencies
RUN pip install --no-cache-dir -r /app/parent-requirements.txt
RUN pip install --no-cache-dir -r /app/gateway-requirements.txt

# Copy parent gemini_webapi source
COPY ../src /app/src

# Copy gateway application
COPY . /app/openclaw-gateway

# Create temp directory
RUN mkdir -p /tmp/gemini-gateway

# Expose port
EXPOSE 18789

# Health check
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:18789/health || exit 1

# Run server
CMD ["python", "-m", "openclaw-gateway.api_server"]
