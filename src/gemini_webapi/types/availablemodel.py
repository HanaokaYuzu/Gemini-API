from pydantic import BaseModel
from ..constants import Model


class AvailableModel(BaseModel):
    """
    Available model configuration for the current account.
    """

    id: str
    name: str
    model: Model
    description: str
