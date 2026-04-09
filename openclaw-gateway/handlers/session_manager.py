"""Manage chat sessions and conversation continuity"""

import sys
from pathlib import Path
from typing import Dict, Optional, Any
from datetime import datetime, timedelta

# Add parent directory to path for imports
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))

from gemini_webapi import GeminiClient
from gemini_webapi.constants import Model


class SessionManager:
    """Manage chat sessions for conversation continuity"""
    
    def __init__(self):
        # Store session metadata: response_id -> session_data
        self.sessions: Dict[str, Dict[str, Any]] = {}
        
        # Store chat sessions: session_key -> ChatSession
        self.chat_sessions: Dict[str, Any] = {}
        
        # Cleanup old sessions after 1 hour
        self.session_ttl = timedelta(hours=1)
    
    def store_response(
        self,
        response_id: str,
        metadata: list,
        user_id: Optional[str] = None,
        model: Optional[Model] = None
    ):
        """
        Store response metadata for future continuity
        
        Args:
            response_id: Unique response ID
            metadata: Gemini response metadata [cid, rid, rcid]
            user_id: Optional user identifier
            model: Model used for this response
        """
        self.sessions[response_id] = {
            "metadata": metadata,
            "user_id": user_id,
            "model": model,
            "timestamp": datetime.now(),
        }
        
        # Cleanup old sessions
        self._cleanup_old_sessions()
    
    def get_session_metadata(self, response_id: str) -> Optional[Dict[str, Any]]:
        """
        Get stored session metadata
        
        Args:
            response_id: Response ID to look up
        
        Returns:
            Session data dict or None if not found
        """
        return self.sessions.get(response_id)
    
    async def get_or_create_chat_session(
        self,
        client: GeminiClient,
        user_id: Optional[str],
        previous_response_id: Optional[str],
        model: Model
    ):
        """
        Get existing chat session or create new one
        
        Args:
            client: GeminiClient instance
            user_id: User identifier
            previous_response_id: Previous response ID for continuity
            model: Model to use
        
        Returns:
            ChatSession object or None for new conversation
        """
        # If no previous response, start fresh
        if not previous_response_id:
            return None
        
        # Look up previous session
        session_data = self.get_session_metadata(previous_response_id)
        if not session_data:
            return None
        
        # Check if user matches (if provided)
        if user_id and session_data.get("user_id") != user_id:
            return None
        
        # Create session key
        session_key = f"{user_id or 'default'}:{previous_response_id}"
        
        # Check if we have cached ChatSession
        if session_key in self.chat_sessions:
            return self.chat_sessions[session_key]
        
        # Create new ChatSession with previous metadata
        metadata = session_data.get("metadata", [])
        if metadata:
            chat = client.start_chat(
                metadata=metadata,
                model=model
            )
            self.chat_sessions[session_key] = chat
            return chat
        
        return None
    
    def _cleanup_old_sessions(self):
        """Remove sessions older than TTL"""
        now = datetime.now()
        expired_ids = [
            response_id
            for response_id, data in self.sessions.items()
            if now - data["timestamp"] > self.session_ttl
        ]
        
        for response_id in expired_ids:
            del self.sessions[response_id]
            
            # Also cleanup chat sessions
            keys_to_remove = [
                key for key in self.chat_sessions.keys()
                if response_id in key
            ]
            for key in keys_to_remove:
                del self.chat_sessions[key]
