"""Route requests to appropriate Gemini model"""

import sys
from pathlib import Path
from typing import Optional

# Add parent directory to path for imports
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))

from gemini_webapi.constants import Model


class ModelRouter:
    """Route model selection to Gemini models"""
    
    # Mapping from OpenClaw model names to Gemini Model enum
    MODEL_MAPPING = {
        "openclaw": Model.UNSPECIFIED,
        "gemini-3-flash": Model.BASIC_FLASH,
        "gemini-3-pro": Model.BASIC_PRO,
        "gemini-3-flash-thinking": Model.BASIC_THINKING,
        "gemini-3-flash-plus": Model.PLUS_FLASH,
        "gemini-3-pro-plus": Model.PLUS_PRO,
        "gemini-3-flash-thinking-plus": Model.PLUS_THINKING,
        "gemini-3-flash-advanced": Model.ADVANCED_FLASH,
        "gemini-3-pro-advanced": Model.ADVANCED_PRO,
        "gemini-3-flash-thinking-advanced": Model.ADVANCED_THINKING,
    }
    
    @classmethod
    def get_model(cls, model_name: str) -> Model:
        """
        Get Gemini model from model name
        
        Args:
            model_name: Model name from request
        
        Returns:
            Gemini Model enum value
        """
        # Direct mapping
        if model_name in cls.MODEL_MAPPING:
            return cls.MODEL_MAPPING[model_name]
        
        # Try to match by model_name attribute
        for gemini_model in Model:
            if gemini_model.model_name == model_name:
                return gemini_model
        
        # Default to unspecified
        return Model.UNSPECIFIED
    
    @classmethod
    def get_all_models(cls) -> list:
        """
        Get list of all available model names
        
        Returns:
            List of model name strings
        """
        return list(cls.MODEL_MAPPING.keys())
    
    @classmethod
    def model_requires_advanced(cls, model: Model) -> bool:
        """
        Check if model requires advanced subscription
        
        Args:
            model: Gemini Model enum
        
        Returns:
            True if advanced subscription required
        """
        return model.advanced_only if hasattr(model, 'advanced_only') else False
