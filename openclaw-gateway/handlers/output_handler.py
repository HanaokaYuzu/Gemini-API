"""Format Gemini outputs to OpenClaw-compatible format"""

import sys
import json
import uuid
from pathlib import Path
from typing import AsyncGenerator, Dict, Any
from datetime import datetime

# Add parent directory to path for imports
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))

from gemini_webapi.types import ModelOutput
from ..models.responses import ResponseOutput, ResponseChoice, ResponseUsage, ResponseMessage


class OutputHandler:
    """Format Gemini outputs to OpenClaw format"""
    
    @staticmethod
    def format_response(
        gemini_output: ModelOutput,
        request_model: str,
        response_id: str
    ) -> ResponseOutput:
        """
        Convert Gemini ModelOutput to OpenClaw ResponseOutput
        
        Args:
            gemini_output: Gemini response object
            request_model: Model name from request
            response_id: Unique response ID
        
        Returns:
            OpenClaw-compatible ResponseOutput
        """
        # Extract text
        text = gemini_output.text or ""
        
        # Extract thoughts (for thinking models)
        thoughts = gemini_output.thoughts
        
        # Extract images
        images = []
        if gemini_output.images:
            for img in gemini_output.images:
                images.append({
                    "type": "generated" if hasattr(img, 'is_generated') and img.is_generated else "web",
                    "url": img.url if hasattr(img, 'url') else str(img),
                    "title": img.title if hasattr(img, 'title') else None,
                    "alt": img.alt if hasattr(img, 'alt') else None,
                })
        
        # Extract videos
        videos = []
        if gemini_output.videos:
            for video in gemini_output.videos:
                videos.append({
                    "url": video.url if hasattr(video, 'url') else str(video),
                    "title": video.title if hasattr(video, 'title') else None,
                })
        
        # Extract media (audio)
        media = []
        if gemini_output.media:
            for m in gemini_output.media:
                media.append({
                    "url": m.url if hasattr(m, 'url') else str(m),
                    "type": "audio",
                })
        
        # Build message
        message = ResponseMessage(
            role="assistant",
            content=text,
            images=images if images else None,
            videos=videos if videos else None,
            media=media if media else None,
            thoughts=thoughts,
        )
        
        # Calculate token usage (rough estimate)
        prompt_tokens = 0  # We don't have this from Gemini
        completion_tokens = len(text.split())
        
        return ResponseOutput(
            id=response_id,
            created=int(datetime.now().timestamp()),
            model=request_model,
            choices=[
                ResponseChoice(
                    index=0,
                    message=message,
                    finish_reason="stop"
                )
            ],
            usage=ResponseUsage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens
            )
        )
    
    @staticmethod
    async def stream_response(
        gemini_stream: AsyncGenerator,
        request_model: str,
        response_id: str
    ) -> AsyncGenerator[str, None]:
        """
        Stream Gemini output as Server-Sent Events (SSE)
        
        Args:
            gemini_stream: Async generator from Gemini
            request_model: Model name from request
            response_id: Unique response ID
        
        Yields:
            SSE formatted strings
        """
        created = int(datetime.now().timestamp())
        accumulated_images = []
        accumulated_videos = []
        accumulated_media = []
        
        try:
            async for chunk in gemini_stream:
                # Stream text deltas
                if chunk.text_delta:
                    event_data = {
                        "id": response_id,
                        "object": "response.delta",
                        "created": created,
                        "model": request_model,
                        "choices": [{
                            "index": 0,
                            "delta": {
                                "role": "assistant",
                                "content": chunk.text_delta
                            }
                        }]
                    }
                    yield f"data: {json.dumps(event_data)}\n\n"
                
                # Stream thoughts (for thinking models)
                if chunk.thoughts_delta:
                    event_data = {
                        "id": response_id,
                        "object": "response.delta",
                        "created": created,
                        "model": request_model,
                        "choices": [{
                            "index": 0,
                            "delta": {
                                "thoughts": chunk.thoughts_delta
                            }
                        }]
                    }
                    yield f"data: {json.dumps(event_data)}\n\n"
                
                # Detect new images
                if chunk.images and len(chunk.images) > len(accumulated_images):
                    new_images = chunk.images[len(accumulated_images):]
                    accumulated_images.extend(new_images)
                    
                    formatted_images = []
                    for img in new_images:
                        formatted_images.append({
                            "type": "generated" if hasattr(img, 'is_generated') and img.is_generated else "web",
                            "url": img.url if hasattr(img, 'url') else str(img),
                            "title": img.title if hasattr(img, 'title') else None,
                        })
                    
                    event_data = {
                        "id": response_id,
                        "object": "response.images",
                        "created": created,
                        "images": formatted_images
                    }
                    yield f"data: {json.dumps(event_data)}\n\n"
                
                # Detect new videos
                if chunk.videos and len(chunk.videos) > len(accumulated_videos):
                    new_videos = chunk.videos[len(accumulated_videos):]
                    accumulated_videos.extend(new_videos)
                    
                    formatted_videos = []
                    for video in new_videos:
                        formatted_videos.append({
                            "url": video.url if hasattr(video, 'url') else str(video),
                            "title": video.title if hasattr(video, 'title') else None,
                        })
                    
                    event_data = {
                        "id": response_id,
                        "object": "response.videos",
                        "created": created,
                        "videos": formatted_videos
                    }
                    yield f"data: {json.dumps(event_data)}\n\n"
                
                # Detect new media (audio)
                if chunk.media and len(chunk.media) > len(accumulated_media):
                    new_media = chunk.media[len(accumulated_media):]
                    accumulated_media.extend(new_media)
                    
                    formatted_media = []
                    for m in new_media:
                        formatted_media.append({
                            "url": m.url if hasattr(m, 'url') else str(m),
                            "type": "audio",
                        })
                    
                    event_data = {
                        "id": response_id,
                        "object": "response.media",
                        "created": created,
                        "media": formatted_media
                    }
                    yield f"data: {json.dumps(event_data)}\n\n"
            
            # Send final done event
            final_event = {
                "id": response_id,
                "object": "response.done",
                "created": created,
                "model": request_model,
                "choices": [{
                    "index": 0,
                    "finish_reason": "stop"
                }]
            }
            yield f"data: {json.dumps(final_event)}\n\n"
            yield "data: [DONE]\n\n"
        
        except Exception as e:
            # Send error event
            error_event = {
                "error": {
                    "message": str(e),
                    "type": "gemini_error"
                }
            }
            yield f"data: {json.dumps(error_event)}\n\n"
