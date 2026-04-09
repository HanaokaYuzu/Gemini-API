# API Usage Examples

Complete examples for testing the Gemini-OpenClaw Gateway.

## Prerequisites

```bash
# Start the server
python api_server.py

# Or with Docker
docker-compose up -d
```

## 1. Simple Text Query

```bash
curl -X POST http://localhost:18789/v1/responses \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gemini-3-flash",
    "input": "What is the capital of France?"
  }' | jq
```

## 2. Text Query with Specific Model

```bash
curl -X POST http://localhost:18789/v1/responses \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gemini-3-pro",
    "input": "Explain quantum entanglement in simple terms"
  }' | jq
```

## 3. Thinking Model

```bash
curl -X POST http://localhost:18789/v1/responses \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gemini-3-flash-thinking",
    "input": "Solve this step by step: If a train travels 120 km in 2 hours, what is its average speed?"
  }' | jq '.choices[0].message.thoughts, .choices[0].message.content'
```

## 4. Image Analysis from URL

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
          "url": "https://upload.wikimedia.org/wikipedia/commons/thumb/3/3a/Cat03.jpg/1200px-Cat03.jpg"
        }
      },
      {
        "type": "message",
        "role": "user",
        "content": "Describe this image in detail"
      }
    ]
  }' | jq
```

## 5. Image Analysis from Base64

```bash
# First, encode an image
IMAGE_BASE64=$(base64 -w0 your_image.jpg)

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
          "data": "'"$IMAGE_BASE64"'"
        }
      },
      {
        "type": "message",
        "role": "user",
        "content": "What objects are in this image?"
      }
    ]
  }' | jq
```

## 6. PDF Document Analysis

```bash
# Encode PDF
PDF_BASE64=$(base64 -w0 document.pdf)

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
          "data": "'"$PDF_BASE64"'",
          "filename": "document.pdf"
        }
      },
      {
        "type": "message",
        "role": "user",
        "content": "Summarize the key points from this document"
      }
    ]
  }' | jq
```

## 7. Multiple Files (Image + PDF)

```bash
IMAGE_BASE64=$(base64 -w0 chart.png)
PDF_BASE64=$(base64 -w0 report.pdf)

curl -X POST http://localhost:18789/v1/responses \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gemini-3-pro",
    "input": [
      {
        "type": "input_image",
        "source": {
          "type": "base64",
          "media_type": "image/png",
          "data": "'"$IMAGE_BASE64"'"
        }
      },
      {
        "type": "input_file",
        "source": {
          "type": "base64",
          "media_type": "application/pdf",
          "data": "'"$PDF_BASE64"'",
          "filename": "report.pdf"
        }
      },
      {
        "type": "message",
        "role": "user",
        "content": "Compare the data in the chart with the information in the report"
      }
    ]
  }' | jq
```

## 8. Streaming Response

```bash
curl -N -X POST http://localhost:18789/v1/responses \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gemini-3-flash",
    "stream": true,
    "input": "Write a short story about a robot learning to paint"
  }'
```

## 9. Streaming with Thinking Model

```bash
curl -N -X POST http://localhost:18789/v1/responses \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gemini-3-flash-thinking-plus",
    "stream": true,
    "input": "Solve this complex math problem: Find the derivative of f(x) = x^3 * sin(x)"
  }'
```

## 10. Session Continuity

```bash
# First message
RESPONSE=$(curl -s -X POST http://localhost:18789/v1/responses \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gemini-3-pro",
    "user": "user123",
    "input": "My favorite color is blue. Remember this."
  }')

# Extract response ID
RESPONSE_ID=$(echo $RESPONSE | jq -r '.id')
echo "Response ID: $RESPONSE_ID"

# Follow-up message using previous_response_id
curl -X POST http://localhost:18789/v1/responses \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gemini-3-pro",
    "user": "user123",
    "previous_response_id": "'"$RESPONSE_ID"'",
    "input": "What is my favorite color?"
  }' | jq
```

## 11. Image Generation

```bash
curl -X POST http://localhost:18789/v1/responses \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gemini-3-pro",
    "input": "Generate an image of a serene mountain landscape at sunrise"
  }' | jq '.choices[0].message.images'
```

## 12. With Authentication

```bash
# Set bearer token in .env
# API_BEARER_TOKEN=my_secret_token

curl -X POST http://localhost:18789/v1/responses \
  -H "Authorization: Bearer my_secret_token" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gemini-3-flash",
    "input": "Hello, authenticated world!"
  }' | jq
```

## 13. Multi-Agent Support

```bash
# Agent 1
curl -X POST http://localhost:18789/v1/responses \
  -H "x-openclaw-agent-id: agent1" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gemini-3-flash",
    "input": "Hello from agent 1"
  }' | jq

# Agent 2
curl -X POST http://localhost:18789/v1/responses \
  -H "x-openclaw-agent-id: agent2" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gemini-3-pro",
    "input": "Hello from agent 2"
  }' | jq
```

## 14. List Available Models

```bash
curl -X GET http://localhost:18789/v1/models \
  -H "Content-Type: application/json" | jq
```

## 15. Health Check

```bash
curl -X GET http://localhost:18789/health | jq
```

## Python Examples

### Simple Request

```python
import requests

response = requests.post(
    "http://localhost:18789/v1/responses",
    json={
        "model": "gemini-3-pro",
        "input": "What is the meaning of life?"
    }
)

print(response.json()["choices"][0]["message"]["content"])
```

### Image Analysis

```python
import requests
import base64

# Read and encode image
with open("image.jpg", "rb") as f:
    image_data = base64.b64encode(f.read()).decode()

response = requests.post(
    "http://localhost:18789/v1/responses",
    json={
        "model": "gemini-3-flash",
        "input": [
            {
                "type": "input_image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": image_data
                }
            },
            {
                "type": "message",
                "role": "user",
                "content": "Describe this image"
            }
        ]
    }
)

print(response.json()["choices"][0]["message"]["content"])
```

### Streaming

```python
import requests
import json

response = requests.post(
    "http://localhost:18789/v1/responses",
    json={
        "model": "gemini-3-flash",
        "stream": True,
        "input": "Tell me a story"
    },
    stream=True
)

for line in response.iter_lines():
    if line:
        line = line.decode('utf-8')
        if line.startswith('data: '):
            data = line[6:]
            if data == '[DONE]':
                break
            try:
                event = json.loads(data)
                if 'choices' in event and event['choices']:
                    delta = event['choices'][0].get('delta', {})
                    if 'content' in delta:
                        print(delta['content'], end='', flush=True)
            except json.JSONDecodeError:
                pass

print()
```

## JavaScript/Node.js Examples

### Simple Request

```javascript
const response = await fetch('http://localhost:18789/v1/responses', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
  },
  body: JSON.stringify({
    model: 'gemini-3-pro',
    input: 'What is artificial intelligence?'
  })
});

const data = await response.json();
console.log(data.choices[0].message.content);
```

### Streaming

```javascript
const response = await fetch('http://localhost:18789/v1/responses', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
  },
  body: JSON.stringify({
    model: 'gemini-3-flash',
    stream: true,
    input: 'Write a poem about the ocean'
  })
});

const reader = response.body.getReader();
const decoder = new TextDecoder();

while (true) {
  const { done, value } = await reader.read();
  if (done) break;
  
  const chunk = decoder.decode(value);
  const lines = chunk.split('\n');
  
  for (const line of lines) {
    if (line.startsWith('data: ')) {
      const data = line.slice(6);
      if (data === '[DONE]') break;
      
      try {
        const event = JSON.parse(data);
        if (event.choices?.[0]?.delta?.content) {
          process.stdout.write(event.choices[0].delta.content);
        }
      } catch (e) {
        // Skip invalid JSON
      }
    }
  }
}

console.log();
```

## Testing Tips

1. **Start with simple text queries** to verify basic functionality
2. **Test streaming** to ensure SSE works correctly
3. **Try different models** to verify routing
4. **Test multimodal inputs** with small files first
5. **Verify session continuity** with follow-up questions
6. **Check error handling** with invalid inputs

## Common Issues

### Base64 Encoding

On macOS/Linux, use `-w0` to avoid line wrapping:
```bash
base64 -w0 file.jpg
```

On macOS without `-w0` support:
```bash
base64 -i file.jpg | tr -d '\n'
```

### Large Files

For files larger than limits, increase in `.env`:
```bash
MAX_FILE_SIZE_MB=200
MAX_IMAGE_SIZE_MB=100
```

### Streaming Not Working

Ensure you use `-N` flag with curl:
```bash
curl -N -X POST ...
```
