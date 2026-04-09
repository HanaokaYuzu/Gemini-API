# Gemini-OpenClaw Gateway

OpenClaw-compatible HTTP API endpoint for Google Gemini with **full multimodal support** (text, images, PDFs, videos, audio).

## Features

✅ **OpenClaw `/v1/responses` API compatibility**  
✅ **All 9 Gemini model variants** (Basic, Plus, Advanced tiers)  
✅ **Multimodal inputs**: Images (URL/base64), PDFs, documents  
✅ **Multimodal outputs**: Generated images, videos, audio  
✅ **Streaming support** via Server-Sent Events (SSE)  
✅ **Session continuity** with `previous_response_id`  
✅ **Thinking models** with thought process streaming  
✅ **Security hardening**: URL validation, private IP blocking, allowlists  
✅ **Docker deployment** ready  

---

## Quick Start

### 1. Installation

```bash
cd openclaw-gateway

# Install dependencies
pip install -r requirements.txt

# Copy environment template
cp .env.example .env
```

### 2. Configuration

Edit `.env` and set your Gemini cookies:

```bash
# Get these from gemini.google.com (F12 > Network > Cookie)
GEMINI_SECURE_1PSID=your_cookie_value
GEMINI_SECURE_1PSIDTS=your_cookie_value
```

### 3. Run Server

```bash
# Development mode
python api_server.py --reload

# Production mode
python api_server.py --host 0.0.0.0 --port 18789
```

Server will start at `http://localhost:18789`

---

## API Endpoints

### Health Check
```bash
GET /health
```

### List Models
```bash
GET /v1/models
```

### Create Response
```bash
POST /v1/responses
```

---

## Supported Models

| Model Name | Tier | Thinking | Use Case |
|------------|------|----------|----------|
| `openclaw` | Default | No | Auto-select |
| `gemini-3-flash` | Basic | No | Fast responses |
| `gemini-3-pro` | Basic | No | Balanced quality |
| `gemini-3-flash-thinking` | Basic | Yes | Reasoning tasks |
| `gemini-3-flash-plus` | Plus | No | Enhanced fast |
| `gemini-3-pro-plus` | Plus | No | Enhanced quality |
| `gemini-3-flash-thinking-plus` | Plus | Yes | Advanced reasoning |
| `gemini-3-flash-advanced` | Advanced | No | Premium fast |
| `gemini-3-pro-advanced` | Advanced | No | Premium quality |
| `gemini-3-flash-thinking-advanced` | Advanced | Yes | Premium reasoning |

---

## Usage Examples

### Text Query

```bash
curl -X POST http://localhost:18789/v1/responses \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gemini-3-pro",
    "input": "Explain quantum computing in simple terms"
  }'
```

### Image Analysis (URL)

```bash
curl -X POST http://localhost:18789/v1/responses \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gemini-3-flash",
    "input": [
      {
        "type": "input_image",
        "source": {
          "type": "url",
          "url": "https://example.com/chart.png"
        }
      },
      {
        "type": "message",
        "role": "user",
        "content": "Analyze this chart"
      }
    ]
  }'
```

### Image Analysis (Base64)

```bash
curl -X POST http://localhost:18789/v1/responses \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gemini-3-pro",
    "input": [
      {
        "type": "input_image",
        "source": {
          "type": "base64",
          "media_type": "image/jpeg",
          "data": "'$(base64 -w0 image.jpg)'"
        }
      },
      {
        "type": "message",
        "role": "user",
        "content": "What is in this image?"
      }
    ]
  }'
```

### PDF Analysis

```bash
curl -X POST http://localhost:18789/v1/responses \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gemini-3-pro-plus",
    "input": [
      {
        "type": "input_file",
        "source": {
          "type": "base64",
          "media_type": "application/pdf",
          "data": "'$(base64 -w0 document.pdf)'",
          "filename": "document.pdf"
        }
      },
      {
        "type": "message",
        "role": "user",
        "content": "Summarize this document"
      }
    ]
  }'
```

### Multiple Files

```bash
curl -X POST http://localhost:18789/v1/responses \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gemini-3-pro",
    "input": [
      {
        "type": "input_image",
        "source": {
          "type": "url",
          "url": "https://example.com/chart.png"
        }
      },
      {
        "type": "input_file",
        "source": {
          "type": "base64",
          "media_type": "application/pdf",
          "data": "'$(base64 -w0 report.pdf)'",
          "filename": "report.pdf"
        }
      },
      {
        "type": "message",
        "role": "user",
        "content": "Compare the chart with the report data"
      }
    ]
  }'
```

### Streaming Response

```bash
curl -N -X POST http://localhost:18789/v1/responses \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gemini-3-flash-thinking",
    "stream": true,
    "input": "Solve this complex problem step by step: ..."
  }'
```

### Session Continuity

```bash
# First request
RESPONSE=$(curl -X POST http://localhost:18789/v1/responses \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gemini-3-pro",
    "input": "What is the capital of France?"
  }')

RESPONSE_ID=$(echo $RESPONSE | jq -r '.id')

# Follow-up request
curl -X POST http://localhost:18789/v1/responses \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gemini-3-pro",
    "input": "What is its population?",
    "previous_response_id": "'$RESPONSE_ID'"
  }'
```

### Image Generation

```bash
curl -X POST http://localhost:18789/v1/responses \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gemini-3-pro",
    "input": "Generate an image of a futuristic city at sunset"
  }'
```

---

## OpenClaw Integration

### Configuration

Add to your OpenClaw config (`~/.openclaw/openclaw.json`):

```json
{
  "providers": {
    "gemini": {
      "type": "openai",
      "baseURL": "http://localhost:18789/v1",
      "apiKey": "dummy-key-not-required"
    }
  },
  "agents": {
    "defaults": {
      "model": "gemini/gemini-3-pro",
      "imageModel": "gemini/gemini-3-flash",
      "workspace": "~/.openclaw/workspace"
    }
  }
}
```

### Usage with OpenClaw

```bash
# Text query
openclaw agent --message "Hello, how are you?"

# With specific model
openclaw agent --model gemini/gemini-3-flash-thinking \
  --message "Solve this complex reasoning task"

# With image
openclaw agent --model gemini/gemini-3-pro \
  --message "Describe this image" \
  --image photo.jpg
```

---

## Docker Deployment

### Using Docker Compose

```bash
# Create .env file with your credentials
cp .env.example .env
# Edit .env and add your GEMINI_SECURE_1PSID and GEMINI_SECURE_1PSIDTS

# Start service
docker-compose up -d

# View logs
docker-compose logs -f

# Stop service
docker-compose down
```

### Using Docker directly

```bash
# Build image
docker build -t gemini-openclaw-gateway -f Dockerfile ..

# Run container
docker run -d \
  --name gemini-gateway \
  -p 18789:18789 \
  -e GEMINI_SECURE_1PSID="your_cookie" \
  -e GEMINI_SECURE_1PSIDTS="your_cookie" \
  -e LOG_LEVEL=INFO \
  gemini-openclaw-gateway
```

---

## Security

### Authentication

Set bearer token in `.env`:

```bash
API_BEARER_TOKEN=your_secret_token_here
```

Then include in requests:

```bash
curl -X POST http://localhost:18789/v1/responses \
  -H "Authorization: Bearer your_secret_token_here" \
  -H "Content-Type: application/json" \
  -d '{"model": "gemini-3-pro", "input": "Hello"}'
```

### URL Allowlists

Restrict which URLs can be fetched:

```bash
# In .env
IMAGE_URL_ALLOWLIST=cdn.example.com,*.assets.example.com
FILE_URL_ALLOWLIST=docs.example.com
```

### Security Features

- ✅ Private IP blocking (127.0.0.1, 192.168.x.x, etc.)
- ✅ URL validation (HTTP/HTTPS only)
- ✅ File size limits
- ✅ MIME type validation
- ✅ Redirect limits
- ✅ Request timeouts
- ✅ Optional URL allowlisting

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `GEMINI_SECURE_1PSID` | - | **Required** Gemini cookie |
| `GEMINI_SECURE_1PSIDTS` | - | **Required** Gemini cookie |
| `GEMINI_COOKIES_JSON` | - | Path to cookies JSON file |
| `API_HOST` | `0.0.0.0` | Server host |
| `API_PORT` | `18789` | Server port |
| `LOG_LEVEL` | `INFO` | Log level (DEBUG/INFO/WARNING/ERROR) |
| `API_BEARER_TOKEN` | - | Optional bearer token for auth |
| `ALLOWED_ORIGINS` | `*` | CORS origins (comma-separated) |
| `MAX_FILE_SIZE_MB` | `100` | Max file size in MB |
| `MAX_IMAGE_SIZE_MB` | `50` | Max image size in MB |
| `REQUEST_TIMEOUT` | `300` | Request timeout in seconds |
| `ENABLE_URL_FETCH` | `true` | Allow URL fetching |
| `IMAGE_URL_ALLOWLIST` | - | Allowed image URL patterns |
| `FILE_URL_ALLOWLIST` | - | Allowed file URL patterns |

---

## Response Format

### Non-Streaming

```json
{
  "id": "resp_abc123",
  "object": "response",
  "created": 1712345678,
  "model": "gemini-3-pro",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "Response text here...",
        "images": [
          {
            "type": "generated",
            "url": "https://...",
            "title": "Image title"
          }
        ],
        "videos": [...],
        "media": [...],
        "thoughts": "Thinking process..."
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 10,
    "completion_tokens": 150,
    "total_tokens": 160
  }
}
```

### Streaming (SSE)

```
data: {"id":"resp_abc","object":"response.delta","choices":[{"delta":{"content":"Text"}}]}

data: {"id":"resp_abc","object":"response.images","images":[{"url":"..."}]}

data: {"id":"resp_abc","object":"response.done","choices":[{"finish_reason":"stop"}]}

data: [DONE]
```

---

## Troubleshooting

### Authentication Errors

```
Missing Gemini credentials
```

**Solution**: Set `GEMINI_SECURE_1PSID` and `GEMINI_SECURE_1PSIDTS` in `.env`

### Cookie Expiration

```
Gemini auth failed: 401
```

**Solution**: Re-export cookies from gemini.google.com

### File Too Large

```
File too large: X bytes
```

**Solution**: Increase `MAX_FILE_SIZE_MB` or `MAX_IMAGE_SIZE_MB` in `.env`

### Private IP Blocked

```
Private IP address not allowed
```

**Solution**: This is a security feature. Use public URLs only.

---

## Development

### Run in Development Mode

```bash
python api_server.py --reload
```

### Run Tests

```bash
# TODO: Add test suite
pytest tests/
```

### Project Structure

```
openclaw-gateway/
├── api_server.py          # Main FastAPI application
├── config.py              # Configuration management
├── models/
│   ├── requests.py        # Request models
│   └── responses.py       # Response models
├── handlers/
│   ├── input_processor.py # Process multimodal inputs
│   ├── model_router.py    # Route to Gemini models
│   ├── session_manager.py # Manage sessions
│   └── output_handler.py  # Format outputs
├── utils/
│   ├── file_utils.py      # File handling
│   └── validators.py      # Input validation
├── requirements.txt       # Python dependencies
├── Dockerfile            # Docker image
├── docker-compose.yml    # Docker Compose config
└── README.md             # This file
```

---

## License

This project follows the same license as the parent Gemini-API project (AGPL-3.0).

---

## Credits

Built on top of [Gemini-API](https://github.com/HanaokaYuzu/Gemini-API) by HanaokaYuzu.

Compatible with [OpenClaw](https://openclaw.ai) agent framework.
