"""Process multimodal inputs from OpenClaw format to Gemini format"""

import sys
from pathlib import Path
from typing import List, Tuple

# Add parent directory to path for imports
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))

from ..models.requests import (
    ResponseRequest,
    InputImageItem,
    InputFileItem,
    MessageItem,
)
from ..utils.file_utils import (
    download_url_safely,
    decode_base64_file,
    save_temp_file,
    get_file_extension_from_mime,
    cleanup_temp_file,
)
from ..utils.validators import (
    validate_mime_type,
    SUPPORTED_IMAGE_TYPES,
    SUPPORTED_FILE_TYPES,
)
from ..config import config


class InputProcessor:
    """Process multimodal inputs for Gemini"""
    
    def __init__(self):
        self.temp_files: List[Path] = []
    
    async def process_request(
        self, 
        request: ResponseRequest
    ) -> Tuple[str, List[Path]]:
        """
        Process OpenClaw request to extract prompt and files
        
        Args:
            request: OpenClaw request object
        
        Returns:
            Tuple of (prompt_text, list_of_file_paths)
        """
        prompt = ""
        files = []
        
        # Handle simple string input
        if isinstance(request.input, str):
            prompt = request.input
            return prompt, files
        
        # Handle list of items
        for item in request.input:
            if isinstance(item, MessageItem):
                # Extract text from message
                if item.content:
                    prompt += item.content + "\n"
            
            elif isinstance(item, InputImageItem):
                # Process image
                file_path = await self._process_image(item)
                if file_path:
                    files.append(file_path)
                    self.temp_files.append(file_path)
            
            elif isinstance(item, InputFileItem):
                # Process file (PDF, documents, etc.)
                file_path = await self._process_file(item)
                if file_path:
                    files.append(file_path)
                    self.temp_files.append(file_path)
        
        # Add instructions if provided
        if request.instructions:
            prompt = f"{request.instructions}\n\n{prompt}"
        
        return prompt.strip(), files
    
    async def _process_image(self, item: InputImageItem) -> Path:
        """
        Process image input item
        
        Args:
            item: InputImageItem with URL or base64 source
        
        Returns:
            Path to saved image file
        """
        source = item.source
        
        if source.type == "url":
            # Download from URL
            if not config.ENABLE_URL_FETCH:
                raise ValueError("URL fetching is disabled")
            
            content, content_type = await download_url_safely(
                source.url,
                max_size=config.max_image_size_bytes,
                allowlist=config.IMAGE_URL_ALLOWLIST
            )
            
            # Validate MIME type
            if not validate_mime_type(content_type, SUPPORTED_IMAGE_TYPES):
                raise ValueError(f"Unsupported image type: {content_type}")
            
            # Save to temp file
            extension = get_file_extension_from_mime(content_type)
            return save_temp_file(content, extension=extension)
        
        elif source.type == "base64":
            # Decode base64
            content = decode_base64_file(source.data)
            
            # Validate MIME type
            if source.media_type:
                if not validate_mime_type(source.media_type, SUPPORTED_IMAGE_TYPES):
                    raise ValueError(f"Unsupported image type: {source.media_type}")
                extension = get_file_extension_from_mime(source.media_type)
            else:
                extension = ".jpg"  # Default
            
            # Check size
            if len(content) > config.max_image_size_bytes:
                raise ValueError(
                    f"Image too large: {len(content)} bytes (max: {config.max_image_size_bytes})"
                )
            
            return save_temp_file(content, extension=extension)
        
        raise ValueError(f"Unsupported image source type: {source.type}")
    
    async def _process_file(self, item: InputFileItem) -> Path:
        """
        Process file input item (PDF, documents, etc.)
        
        Args:
            item: InputFileItem with base64 source
        
        Returns:
            Path to saved file
        """
        source = item.source
        
        # Only base64 is supported for files in OpenClaw spec
        if source.type != "base64":
            raise ValueError(f"Unsupported file source type: {source.type}")
        
        # Decode base64
        content = decode_base64_file(source.data)
        
        # Validate MIME type
        if not validate_mime_type(source.media_type, SUPPORTED_FILE_TYPES):
            raise ValueError(f"Unsupported file type: {source.media_type}")
        
        # Check size
        if len(content) > config.max_file_size_bytes:
            raise ValueError(
                f"File too large: {len(content)} bytes (max: {config.max_file_size_bytes})"
            )
        
        # Save with original filename if provided
        if source.filename:
            return save_temp_file(content, filename=source.filename)
        else:
            extension = get_file_extension_from_mime(source.media_type)
            return save_temp_file(content, extension=extension)
    
    def cleanup(self):
        """Clean up temporary files"""
        for file_path in self.temp_files:
            cleanup_temp_file(file_path)
        self.temp_files.clear()
