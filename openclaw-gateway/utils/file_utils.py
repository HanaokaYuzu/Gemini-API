"""File handling utilities for downloading and processing files"""

import base64
import hashlib
import aiohttp
import asyncio
from pathlib import Path
from typing import Tuple
from urllib.parse import urlparse

from ..config import config
from .validators import validate_url, is_private_ip, validate_url_allowlist


class FileDownloadError(Exception):
    """Error during file download"""
    pass


async def download_url_safely(
    url: str,
    max_size: int,
    max_redirects: int = 5,
    timeout: int = 30,
    allowlist: list = None
) -> Tuple[bytes, str]:
    """
    Download file from URL with security checks
    
    Args:
        url: URL to download
        max_size: Maximum file size in bytes
        max_redirects: Maximum number of redirects to follow
        timeout: Request timeout in seconds
        allowlist: Optional URL allowlist
    
    Returns:
        Tuple of (file_content, content_type)
    
    Raises:
        FileDownloadError: If download fails or security check fails
    """
    # Validate URL format
    if not validate_url(url):
        raise FileDownloadError(f"Invalid URL format: {url}")
    
    # Check allowlist
    if allowlist and not validate_url_allowlist(url, allowlist):
        raise FileDownloadError(f"URL not in allowlist: {url}")
    
    # Check for private IP
    parsed = urlparse(url)
    if is_private_ip(parsed.hostname):
        raise FileDownloadError(f"Private IP address not allowed: {parsed.hostname}")
    
    # Download with aiohttp
    timeout_obj = aiohttp.ClientTimeout(total=timeout)
    
    try:
        async with aiohttp.ClientSession(timeout=timeout_obj) as session:
            async with session.get(
                url,
                allow_redirects=True,
                max_redirects=max_redirects
            ) as response:
                # Check status
                if response.status != 200:
                    raise FileDownloadError(
                        f"HTTP {response.status} error downloading {url}"
                    )
                
                # Check content length
                content_length = response.headers.get("Content-Length")
                if content_length and int(content_length) > max_size:
                    raise FileDownloadError(
                        f"File too large: {content_length} bytes (max: {max_size})"
                    )
                
                # Read content with size limit
                content = bytearray()
                async for chunk in response.content.iter_chunked(8192):
                    content.extend(chunk)
                    if len(content) > max_size:
                        raise FileDownloadError(
                            f"File exceeds size limit: {max_size} bytes"
                        )
                
                content_type = response.headers.get("Content-Type", "application/octet-stream")
                
                return bytes(content), content_type
    
    except aiohttp.ClientError as e:
        raise FileDownloadError(f"Network error downloading {url}: {e}")
    except asyncio.TimeoutError:
        raise FileDownloadError(f"Timeout downloading {url}")


def decode_base64_file(base64_data: str) -> bytes:
    """
    Decode base64 encoded file data
    
    Args:
        base64_data: Base64 encoded string
    
    Returns:
        Decoded bytes
    
    Raises:
        ValueError: If base64 decoding fails
    """
    try:
        return base64.b64decode(base64_data)
    except Exception as e:
        raise ValueError(f"Invalid base64 data: {e}")


def save_temp_file(content: bytes, filename: str = None, extension: str = None) -> Path:
    """
    Save content to temporary file
    
    Args:
        content: File content bytes
        filename: Optional filename to preserve
        extension: Optional file extension (e.g., '.pdf')
    
    Returns:
        Path to saved temporary file
    """
    # Generate unique filename
    content_hash = hashlib.md5(content).hexdigest()[:12]
    
    if filename:
        # Preserve original filename with hash prefix
        safe_filename = f"{content_hash}_{filename}"
    elif extension:
        # Use hash with extension
        safe_filename = f"{content_hash}{extension}"
    else:
        # Just hash
        safe_filename = content_hash
    
    # Save to temp directory
    temp_path = config.TEMP_DIR / safe_filename
    temp_path.write_bytes(content)
    
    return temp_path


def cleanup_temp_file(file_path: Path) -> None:
    """
    Delete temporary file
    
    Args:
        file_path: Path to file to delete
    """
    try:
        if file_path.exists():
            file_path.unlink()
    except Exception:
        pass  # Ignore cleanup errors


def get_file_extension_from_mime(mime_type: str) -> str:
    """
    Get file extension from MIME type
    
    Args:
        mime_type: MIME type string
    
    Returns:
        File extension with dot (e.g., '.pdf')
    """
    mime_to_ext = {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "image/heic": ".heic",
        "image/heif": ".heif",
        "image/bmp": ".bmp",
        "image/svg+xml": ".svg",
        "application/pdf": ".pdf",
        "text/plain": ".txt",
        "text/markdown": ".md",
        "text/html": ".html",
        "text/csv": ".csv",
        "application/json": ".json",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    }
    
    base_type = mime_type.lower().split(";")[0].strip()
    return mime_to_ext.get(base_type, ".bin")
