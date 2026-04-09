"""Validation utilities for security and input checking"""

import ipaddress
import socket
from typing import List
from urllib.parse import urlparse


# Supported MIME types
SUPPORTED_IMAGE_TYPES = {
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/gif",
    "image/webp",
    "image/heic",
    "image/heif",
    "image/bmp",
    "image/svg+xml",
}

SUPPORTED_FILE_TYPES = {
    "application/pdf",
    "text/plain",
    "text/markdown",
    "text/html",
    "text/csv",
    "application/json",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # .docx
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",  # .xlsx
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",  # .pptx
}

# Private IP ranges
PRIVATE_IP_RANGES = [
    ipaddress.ip_network("127.0.0.0/8"),      # Loopback
    ipaddress.ip_network("10.0.0.0/8"),       # Private
    ipaddress.ip_network("172.16.0.0/12"),    # Private
    ipaddress.ip_network("192.168.0.0/16"),   # Private
    ipaddress.ip_network("169.254.0.0/16"),   # Link-local
    ipaddress.ip_network("::1/128"),          # IPv6 loopback
    ipaddress.ip_network("fc00::/7"),         # IPv6 private
    ipaddress.ip_network("fe80::/10"),        # IPv6 link-local
]


def validate_mime_type(mime_type: str, allowed_types: set) -> bool:
    """
    Validate if MIME type is in allowed list
    
    Args:
        mime_type: MIME type to check
        allowed_types: Set of allowed MIME types
    
    Returns:
        True if valid
    """
    # Normalize and extract base type
    base_type = mime_type.lower().split(";")[0].strip()
    return base_type in allowed_types


def is_private_ip(hostname: str) -> bool:
    """
    Check if hostname resolves to a private IP address
    
    Args:
        hostname: Hostname to check
    
    Returns:
        True if private IP
    """
    try:
        # Resolve hostname to IP
        ip_str = socket.gethostbyname(hostname)
        ip = ipaddress.ip_address(ip_str)
        
        # Check against private ranges
        for private_range in PRIVATE_IP_RANGES:
            if ip in private_range:
                return True
        
        return False
    except (socket.gaierror, ValueError):
        # DNS resolution failed or invalid IP
        return True  # Treat as suspicious


def validate_url(url: str) -> bool:
    """
    Validate URL format and scheme
    
    Args:
        url: URL to validate
    
    Returns:
        True if valid HTTP(S) URL
    """
    try:
        parsed = urlparse(url)
        
        # Must have http or https scheme
        if parsed.scheme not in ("http", "https"):
            return False
        
        # Must have hostname
        if not parsed.hostname:
            return False
        
        return True
    except Exception:
        return False


def validate_url_allowlist(url: str, allowlist: List[str]) -> bool:
    """
    Check if URL matches allowlist patterns
    
    Args:
        url: URL to check
        allowlist: List of allowed patterns (exact or wildcard)
    
    Returns:
        True if allowed or allowlist is empty
    """
    if not allowlist:
        return True
    
    hostname = urlparse(url).hostname or ""
    
    for pattern in allowlist:
        # Exact match
        if pattern == hostname:
            return True
        # Wildcard subdomain match (*.example.com)
        if pattern.startswith("*."):
            domain = pattern[2:]
            if hostname.endswith(f".{domain}"):
                return True
    
    return False
