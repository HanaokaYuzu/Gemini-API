"""
Configuration management for Gemini-OpenClaw Gateway
"""
import os
from typing import List, Optional
from pathlib import Path


class Config:
    """Application configuration loaded from environment variables"""
    
    # Gemini Authentication
    GEMINI_SECURE_1PSID: str = os.getenv("GEMINI_SECURE_1PSID", "")
    GEMINI_SECURE_1PSIDTS: str = os.getenv("GEMINI_SECURE_1PSIDTS", "")
    GEMINI_COOKIES_JSON: Optional[str] = os.getenv("GEMINI_COOKIES_JSON")
    
    # Server Configuration
    API_HOST: str = os.getenv("API_HOST", "0.0.0.0")
    API_PORT: int = int(os.getenv("API_PORT", "18789"))
    API_WORKERS: int = int(os.getenv("API_WORKERS", "4"))
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    
    # Security
    API_BEARER_TOKEN: Optional[str] = os.getenv("API_BEARER_TOKEN")
    ALLOWED_ORIGINS: List[str] = [
        origin.strip() 
        for origin in os.getenv("ALLOWED_ORIGINS", "*").split(",")
    ]
    
    # Limits
    MAX_FILE_SIZE_MB: int = int(os.getenv("MAX_FILE_SIZE_MB", "100"))
    MAX_IMAGE_SIZE_MB: int = int(os.getenv("MAX_IMAGE_SIZE_MB", "50"))
    MAX_URL_PARTS: int = int(os.getenv("MAX_URL_PARTS", "8"))
    REQUEST_TIMEOUT: int = int(os.getenv("REQUEST_TIMEOUT", "300"))
    
    # Features
    ENABLE_URL_FETCH: bool = os.getenv("ENABLE_URL_FETCH", "true").lower() == "true"
    ENABLE_IMAGE_GENERATION: bool = os.getenv("ENABLE_IMAGE_GENERATION", "true").lower() == "true"
    ENABLE_VIDEO_GENERATION: bool = os.getenv("ENABLE_VIDEO_GENERATION", "true").lower() == "true"
    ENABLE_AUDIO_GENERATION: bool = os.getenv("ENABLE_AUDIO_GENERATION", "true").lower() == "true"
    
    # URL Allowlists (comma-separated)
    IMAGE_URL_ALLOWLIST: List[str] = [
        url.strip() 
        for url in os.getenv("IMAGE_URL_ALLOWLIST", "").split(",") 
        if url.strip()
    ]
    FILE_URL_ALLOWLIST: List[str] = [
        url.strip() 
        for url in os.getenv("FILE_URL_ALLOWLIST", "").split(",") 
        if url.strip()
    ]
    
    # Computed properties
    @property
    def max_file_size_bytes(self) -> int:
        return self.MAX_FILE_SIZE_MB * 1024 * 1024
    
    @property
    def max_image_size_bytes(self) -> int:
        return self.MAX_IMAGE_SIZE_MB * 1024 * 1024
    
    # Temp directory for file processing
    TEMP_DIR: Path = Path("/tmp/gemini-gateway")
    
    def __init__(self):
        """Initialize and validate configuration"""
        self.TEMP_DIR.mkdir(parents=True, exist_ok=True)
        
        if not self.GEMINI_SECURE_1PSID and not self.GEMINI_COOKIES_JSON:
            raise ValueError(
                "Missing Gemini credentials. Set GEMINI_SECURE_1PSID or GEMINI_COOKIES_JSON"
            )
    
    def validate_url_allowlist(self, url: str, allowlist: List[str]) -> bool:
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
        
        from urllib.parse import urlparse
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


# Global config instance
config = Config()
