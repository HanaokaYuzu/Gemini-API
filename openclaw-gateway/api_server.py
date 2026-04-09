#!/usr/bin/env python3
"""
Gemini-OpenClaw Gateway API Server
OpenClaw-compatible HTTP API endpoint for Google Gemini with full multimodal support
"""

import sys
import json
import uuid
import asyncio
from pathlib import Path
from typing import Optional, Dict
from datetime import datetime
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# Add parent directory to path for gemini_webapi imports
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from gemini_webapi import GeminiClient, logger, set_log_level
from gemini_webapi.exceptions import AuthError, GeminiError
from gemini_webapi.constants import Model

from .config import config
from .models import ResponseRequest
from .handlers import InputProcessor, ModelRouter, SessionManager, OutputHandler


# ============================================================================
# Gemini Client Manager
# ============================================================================

class GeminiClientManager:
    """Manages Gemini client instances per agent"""
    
    def __init__(self):
        self.clients: Dict[str, GeminiClient] = {}
        self.session_manager = SessionManager()
    
    async def get_client(self, agent_id: str = "main") -> GeminiClient:
        """Get or create a Gemini client for an agent"""
        if agent_id in self.clients:
            return self.clients[agent_id]
        
        # Load cookies
        psid = config.GEMINI_SECURE_1PSID
        psidts = config.GEMINI_SECURE_1PSIDTS
        
        if config.GEMINI_COOKIES_JSON and Path(config.GEMINI_COOKIES_JSON).exists():
            try:
                cookies_data = json.loads(Path(config.GEMINI_COOKIES_JSON).read_text())
                if isinstance(cookies_data, dict):
                    psid = cookies_data.get("__Secure-1PSID") or psid
                    psidts = cookies_data.get("__Secure-1PSIDTS") or psidts
            except Exception as e:
                logger.warning(f"Failed to load cookies from JSON: {e}")
        
        if not psid:
            raise HTTPException(
                status_code=401,
                detail="Missing Gemini credentials. Set GEMINI_SECURE_1PSID or GEMINI_COOKIES_JSON"
            )
        
        # Create client
        client = GeminiClient(
            secure_1psid=psid,
            secure_1psidts=psidts or "",
        )
        
        try:
            await client.init(
                timeout=config.REQUEST_TIMEOUT,
                auto_refresh=True,
                verbose=(config.LOG_LEVEL == "DEBUG")
            )
            self.clients[agent_id] = client
            logger.info(f"Initialized Gemini client for agent: {agent_id}")
            return client
        except AuthError as e:
            raise HTTPException(status_code=401, detail=f"Gemini auth failed: {e}")
    
    async def cleanup(self):
        """Close all clients"""
        for client in self.clients.values():
            await client.close()
        self.clients.clear()


# ============================================================================
# FastAPI Application
# ============================================================================

# Global manager instance
manager = GeminiClientManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle"""
    # Startup
    log_level = config.LOG_LEVEL
    set_log_level(log_level)
    logger.info("Gemini-OpenClaw Gateway starting...")
    
    yield
    
    # Shutdown
    await manager.cleanup()
    logger.info("Gemini-OpenClaw Gateway stopped")


app = FastAPI(
    title="Gemini-OpenClaw Gateway",
    description="OpenClaw-compatible API endpoint for Google Gemini with multimodal support",
    version="1.0.0",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================================
# Authentication Middleware
# ============================================================================

async def verify_bearer_token(authorization: Optional[str] = Header(None)):
    """Verify bearer token if configured"""
    if config.API_BEARER_TOKEN:
        if not authorization:
            raise HTTPException(status_code=401, detail="Missing authorization header")
        
        if not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Invalid authorization format")
        
        token = authorization[7:]  # Remove "Bearer " prefix
        if token != config.API_BEARER_TOKEN:
            raise HTTPException(status_code=401, detail="Invalid bearer token")


# ============================================================================
# API Endpoints
# ============================================================================

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "ok",
        "service": "gemini-openclaw-gateway",
        "version": "1.0.0"
    }


@app.get("/v1/models")
async def list_models(
    authorization: Optional[str] = Header(None),
    x_openclaw_agent_id: str = Header("main", alias="x-openclaw-agent-id")
):
    """List available models (OpenClaw-compatible)"""
    await verify_bearer_token(authorization)
    
    try:
        client = await manager.get_client(x_openclaw_agent_id)
        
        # Get models from Gemini
        gemini_models = client.list_models()
        
        model_list = []
        
        # Add all supported models
        for model_name in ModelRouter.get_all_models():
            model_list.append({
                "id": model_name,
                "object": "model",
                "created": int(datetime.now().timestamp()),
                "owned_by": "google-gemini"
            })
        
        # Add dynamic models from Gemini if available
        if gemini_models:
            for m in gemini_models:
                if m.is_available:
                    model_list.append({
                        "id": m.model_name or m.display_name,
                        "object": "model",
                        "created": int(datetime.now().timestamp()),
                        "owned_by": "google-gemini",
                        "description": m.description
                    })
        
        return {"object": "list", "data": model_list}
    
    except Exception as e:
        logger.error(f"Error listing models: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/v1/responses")
async def create_response(
    request: ResponseRequest,
    authorization: Optional[str] = Header(None),
    x_openclaw_agent_id: str = Header("main", alias="x-openclaw-agent-id")
):
    """
    OpenClaw-compatible /v1/responses endpoint
    
    Supports:
    - Text input (string or message items)
    - Image input (URL or base64)
    - File input (PDF, documents via base64)
    - Streaming via SSE
    - Session continuity via previous_response_id
    - All 9 Gemini model variants
    """
    await verify_bearer_token(authorization)
    
    input_processor = InputProcessor()
    
    try:
        # Get Gemini client
        client = await manager.get_client(x_openclaw_agent_id)
        
        # Process inputs
        prompt, files = await input_processor.process_request(request)
        
        if not prompt:
            raise HTTPException(status_code=400, detail="Empty prompt")
        
        # Route to correct model
        gemini_model = ModelRouter.get_model(request.model)
        
        # Generate response ID
        response_id = f"resp_{uuid.uuid4().hex[:16]}"
        
        # Check for session continuity
        chat_session = await manager.session_manager.get_or_create_chat_session(
            client=client,
            user_id=request.user,
            previous_response_id=request.previous_response_id,
            model=gemini_model
        )
        
        # Handle streaming
        if request.stream:
            async def stream_generator():
                try:
                    if chat_session:
                        # Continue existing conversation
                        stream = chat_session.send_message_stream(prompt, files=files)
                    else:
                        # New conversation
                        stream = client.generate_content_stream(
                            prompt,
                            files=files,
                            model=gemini_model
                        )
                    
                    # Stream with output handler
                    async for sse_event in OutputHandler.stream_response(
                        stream,
                        request.model,
                        response_id
                    ):
                        yield sse_event
                
                finally:
                    # Cleanup temp files
                    input_processor.cleanup()
            
            return StreamingResponse(
                stream_generator(),
                media_type="text/event-stream"
            )
        
        # Non-streaming response
        if chat_session:
            # Continue existing conversation
            gemini_output = await chat_session.send_message(prompt, files=files)
        else:
            # New conversation
            gemini_output = await client.generate_content(
                prompt,
                files=files,
                model=gemini_model
            )
        
        # Store session for continuity
        manager.session_manager.store_response(
            response_id=response_id,
            metadata=gemini_output.metadata,
            user_id=request.user,
            model=gemini_model
        )
        
        # Format response
        response = OutputHandler.format_response(
            gemini_output,
            request.model,
            response_id
        )
        
        return response
    
    except GeminiError as e:
        logger.error(f"Gemini error: {e}")
        raise HTTPException(status_code=500, detail=f"Gemini error: {e}")
    
    except ValueError as e:
        logger.error(f"Validation error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    
    finally:
        # Always cleanup temp files
        input_processor.cleanup()


# ============================================================================
# CLI Entry Point
# ============================================================================

def main():
    """Run the API server"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Gemini-OpenClaw Gateway API Server"
    )
    parser.add_argument(
        "--host",
        default=config.API_HOST,
        help=f"Host to bind (default: {config.API_HOST})"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=config.API_PORT,
        help=f"Port to bind (default: {config.API_PORT})"
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload for development"
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Number of worker processes (default: 1)"
    )
    
    args = parser.parse_args()
    
    # Run server
    uvicorn.run(
        "openclaw-gateway.api_server:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        workers=args.workers if not args.reload else 1,
        log_level=config.LOG_LEVEL.lower()
    )


if __name__ == "__main__":
    main()
