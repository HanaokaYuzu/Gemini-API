import json
import time
from typing import List, Optional
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

app = FastAPI(
    title="Gemini Web API OpenAI-Compatible Server",
    description="An OpenAI-compatible FastAPI proxy server wrapping the reverse-engineered Gemini Web API.",
)

class ChatMessage(BaseModel):
    role: str
    content: str

class ChatCompletionRequest(BaseModel):
    model: str = "gemini"
    messages: List[ChatMessage]
    stream: bool = False
    temperature: Optional[float] = 1.0
    max_tokens: Optional[int] = None

@app.get("/")
async def root():
    """
    Status endpoint to verify the server is running.
    """
    return {
        "status": "online",
        "service": "Gemini Web API OpenAI-Compatible Server",
        "endpoints": ["/v1/chat/completions"],
    }

@app.post("/v1/chat/completions")
async def chat_completions(req: ChatCompletionRequest, request: Request):
    """
    OpenAI-compatible chat completions endpoint.
    """
    cl = getattr(request.app.state, "client", None)
    if cl is None:
        raise HTTPException(
            status_code=500,
            detail="Gemini client session has not been initialized on the FastAPI app state."
        )

    if not req.messages:
        raise HTTPException(status_code=400, detail="Messages list cannot be empty.")

    # Grab the last user message as prompt
    prompt = req.messages[-1].content

    # Handle multi-turn history by formatting context if more than 1 message
    if len(req.messages) > 1:
        formatted_prompt = ""
        for msg in req.messages[:-1]:
            role_name = "User" if msg.role == "user" else "Assistant"
            formatted_prompt += f"{role_name}: {msg.content}\n"
        formatted_prompt += f"User: {prompt}\nAssistant: "
        prompt = formatted_prompt

    # Default to basic flash if unspecified/default "gemini" is passed
    model_param = req.model if req.model != "gemini" else "gemini-3-flash"

    if req.stream:
        async def generate():
            chunk_id = f"chatcmpl-{int(time.time())}"
            async for chunk in cl.generate_content_stream(prompt, model=model_param):
                data = {
                    "id": chunk_id,
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": req.model,
                    "choices": [{
                        "index": 0,
                        "delta": {
                            "role": "assistant",
                            "content": chunk.text_delta
                        },
                        "finish_reason": None
                    }]
                }
                yield f"data: {json.dumps(data)}\n\n"

            # Yield final stop chunk
            yield f"data: {json.dumps({
                'id': chunk_id,
                'object': 'chat.completion.chunk',
                'created': int(time.time()),
                'model': req.model,
                'choices': [{
                    'index': 0,
                    'delta': {},
                    'finish_reason': 'stop'
                }]
            })}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(generate(), media_type="text/event-stream")
    else:
        response = await cl.generate_content(prompt, model=model_param)
        return {
            "id": f"chatcmpl-{int(time.time())}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": req.model,
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": response.text
                },
                "finish_reason": "stop"
            }],
            "usage": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0
            }
        }
