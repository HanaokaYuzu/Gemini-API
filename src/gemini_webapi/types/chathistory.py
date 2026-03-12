import reprlib
from typing import List, Optional

from pydantic import BaseModel

from .modeloutput import ModelOutput


class ChatTurn(BaseModel):
    """
    Represents a single turn (message) in a chat conversation.

    Parameters
    ----------
    role: `str`
        The role of the message sender, either "user" or "model".
    text: `str`
        The text content of the message.
    info: `ModelOutput`, optional
        The full model output if the role is "model". This contains candidates, images, and metadata.
    """

    role: str
    text: str
    info: Optional[ModelOutput] = None

    def __str__(self):
        text = self.text if len(self.text) <= 100 else self.text[:97] + "..."
        return f"{self.role.upper()}: {text}"

    def __repr__(self):
        return f"ChatTurn(role='{self.role}', text='{reprlib.repr(self.text)}')"


class ChatHistory(BaseModel):
    """
    Represents the complete history of a chat conversation, ordered from the latest turn to the oldest.

    Parameters
    ----------
    cid: `str`
        The chat ID.
    metadata: `list[str]`
        The chat metadata.
    turns: `list[ChatTurn]`
        The list of messages in the conversation.
    """

    cid: str
    metadata: List[str]
    turns: List[ChatTurn]

    def __str__(self) -> str:
        return f"ChatHistory(cid='{self.cid}', turns={len(self.turns)})"

    def __repr__(self) -> str:
        return f"ChatHistory(cid='{self.cid}', turns={len(self.turns)})"
