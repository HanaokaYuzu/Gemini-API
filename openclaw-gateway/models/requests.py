"""Request models for OpenClaw-compatible API"""

from typing import Optional, List, Dict, Any, Union, Literal
from pydantic import BaseModel, Field


class ImageSource(BaseModel):
    """Image source (URL or base64)"""
    type: Literal["url", "base64"]
    url: Optional[str] = None
    data: Optional[str] = None  # base64 encoded
    media_type: Optional[str] = None  # For base64: image/jpeg, image/png, etc.


class FileSource(BaseModel):
    """File source (base64 only for OpenClaw compatibility)"""
    type: Literal["base64"]
    data: str  # base64 encoded
    media_type: str  # application/pdf, text/plain, etc.
    filename: Optional[str] = None


class MessageItem(BaseModel):
    """Text message item"""
    type: Literal["message"] = "message"
    role: str = "user"
    content: str


class InputImageItem(BaseModel):
    """Image input item"""
    type: Literal["input_image"] = "input_image"
    source: ImageSource


class InputFileItem(BaseModel):
    """File input item (PDF, documents, etc.)"""
    type: Literal["input_file"] = "input_file"
    source: FileSource


# Union type for all input items
InputItem = Union[MessageItem, InputImageItem, InputFileItem]


class ResponseRequest(BaseModel):
    """
    OpenClaw /v1/responses request format
    
    Compatible with OpenClaw's OpenResponses API specification
    """
    model: str = "openclaw"
    input: Union[str, List[InputItem]]
    instructions: Optional[str] = None
    tools: Optional[List[Dict]] = None
    tool_choice: Optional[str] = None
    stream: bool = False
    max_output_tokens: Optional[int] = None
    user: Optional[str] = None
    previous_response_id: Optional[str] = None
    reasoning: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    
    class Config:
        # Allow extra fields for forward compatibility
        extra = "allow"
