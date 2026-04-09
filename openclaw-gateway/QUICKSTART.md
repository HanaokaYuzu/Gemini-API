# Quick Start Guide

Get the Gemini-OpenClaw Gateway running in 5 minutes.

## Step 1: Install Dependencies

```bash
cd openclaw-gateway

# Install Python dependencies
pip install -r requirements.txt
```

## Step 2: Get Gemini Cookies

1. Open https://gemini.google.com in your browser
2. Log in with your Google account
3. Press **F12** to open Developer Tools
4. Go to **Network** tab
5. Refresh the page
6. Click any request
7. Find **Cookie** header and copy:
   - `__Secure-1PSID`
   - `__Secure-1PSIDTS`

## Step 3: Configure

```bash
# Copy environment template
cp .env.example .env

# Edit .env and add your cookies
nano .env
```

Set these values:
```bash
GEMINI_SECURE_1PSID=your_cookie_value_here
GEMINI_SECURE_1PSIDTS=your_cookie_value_here
```

## Step 4: Run Server

```bash
python api_server.py
```

You should see:
```
INFO:     Started server process
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:18789
```

## Step 5: Test

Open a new terminal and test:

```bash
# Health check
curl http://localhost:18789/health

# Simple query
curl -X POST http://localhost:18789/v1/responses \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gemini-3-flash",
    "input": "Hello, how are you?"
  }' | jq
```

## Step 6: Use with OpenClaw

Add to `~/.openclaw/openclaw.json`:

```json
{
  "providers": {
    "gemini": {
      "type": "openai",
      "baseURL": "http://localhost:18789/v1",
      "apiKey": "dummy"
    }
  },
  "agents": {
    "defaults": {
      "model": "gemini/gemini-3-pro"
    }
  }
}
```

Test with OpenClaw:

```bash
openclaw agent --message "Hello from OpenClaw!"
```

## Next Steps

- Read [README.md](README.md) for full documentation
- Check [EXAMPLES.md](EXAMPLES.md) for more usage examples
- Try multimodal inputs (images, PDFs)
- Enable authentication with `API_BEARER_TOKEN`
- Deploy with Docker

## Troubleshooting

### "Missing Gemini credentials"

Make sure you set `GEMINI_SECURE_1PSID` in `.env`

### "Gemini auth failed"

Your cookies may have expired. Re-export them from gemini.google.com

### Port already in use

Change port in `.env`:
```bash
API_PORT=18790
```

### Import errors

Make sure you're in the correct directory and installed dependencies:
```bash
cd openclaw-gateway
pip install -r requirements.txt
```

## Docker Quick Start

```bash
# Create .env file
cp .env.example .env
# Edit .env with your cookies

# Start with Docker Compose
docker-compose up -d

# View logs
docker-compose logs -f

# Test
curl http://localhost:18789/health
```

## Development Mode

Run with auto-reload for development:

```bash
python api_server.py --reload
```

Changes to code will automatically restart the server.

## Support

- Full documentation: [README.md](README.md)
- Examples: [EXAMPLES.md](EXAMPLES.md)
- Issues: Report on GitHub
