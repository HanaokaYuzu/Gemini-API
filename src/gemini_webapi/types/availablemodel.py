from pydantic import BaseModel
from ..constants import Model


class AvailableModel(BaseModel):
    """
    Available model configuration for the current account.

    Parameters
    ----------
    id: `str`
        The explicit internal code name of the model.
    name: `str`
        The display name of the model on the web UI.
    model: `gemini_webapi.constants.Model`
        The core model variation enum.
    description: `str`
        A brief description of the model's capabilities.
    """

    id: str
    name: str
    model: Model
    description: str

    def __str__(self) -> str:
        return self.name

    def __repr__(self) -> str:
        return f"AvailableModel(id='{self.id}', name='{self.name}', model={self.model}, description='{self.description}')"
