from gemini_webapi.client import GeminiClient
from gemini_webapi.constants import Model
from gemini_webapi.types import AvailableModel


def test_extended_thinking_has_a_stable_model_identity():
    """The model used by the web UI's Extended Thinking mode is addressable."""
    assert Model.BASIC_THINKING.model_name == "gemini-3-flash-thinking"
    assert Model.BASIC_THINKING.model_id == "5bf011840784117a"


def test_model_registry_can_represent_extended_thinking():
    model = AvailableModel(
        model_id=Model.BASIC_THINKING.model_id,
        model_name=Model.BASIC_THINKING.model_name,
        display_name="Thinking",
        description="Solves complex problems",
        capacity=1,
    )
    assert model.model_header == Model.BASIC_THINKING.model_header
