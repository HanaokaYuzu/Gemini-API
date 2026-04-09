"""Response models for OpenClaw-compatible API"""

from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel


class ResponseMessage(BaseModel):
    """Response message content"""
    role: str = "assistant"
    content: str
    images: Optional[List[Dict[str, Any]]] = None
    videos: Optional[List[Dict[str, Any]]] = None
    media: Optional[List[Dict[str, Any]]] = None
    thoughts: Optional[str] = None


class ResponseChoice(BaseModel):
    """Response choice"""
    index: int = 0
    message: ResponseMessage
    finish_reason: str = "stop"


class ResponseUsage(BaseModel):
    """Token usage statistics"""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ResponseOutput(BaseModel):
    """
    OpenClaw /v1/responses response format (non-streaming)
    
    Compatible with OpenClaw's OpenResponses API specification
    """
    id: str
    object: Literal["response"] = "response"
    created: int
    model: str
    choices: List[ResponseChoice]
    usage: ResponseUsage


class ResponseDelta(BaseModel):
    """Streaming delta response"""
    id: str
    object: Literal["response.delta"] = "response.delta"
    created: int
    model: str
    choices: List[Dict[str, Any]]  # Contains delta field


class ResponseDone(BaseModel):
    """Streaming done event"""
    id: str
    object: Literal["response.done"] = "response.done"
    created: int
    model: str
    choices: List[Dict[str, Any]]  # Contains finish_reason


class ResponseImages(BaseModel):
    """Streaming images event"""
    id: str
    object: Literal["response.images"] = "response.images"
    created: int
    images: List[Dict[str, Any]]


class ResponseVideos(BaseModel):
    """Streaming videos event"""
    id: str
    object: Literal["response.videos"] = "response.videos"
    created: int
    videos: List[Dict[str, Any]]


class ResponseMedia(BaseModel):
    """Streaming media (audio) event"""
    id: str
    object: Literal["response.media"] = "response.media"
    created: int
    media: List[Dict[str, Any]]
