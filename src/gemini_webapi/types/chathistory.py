from textwrap import shorten

from pydantic import BaseModel

from .modeloutput import ModelOutput


class ChatTurn(BaseModel):
    """Represents a single turn (message) in a chat conversation.

    Parameters
    ----------
    role: `str`
        The role of the message sender, either "user" or "model".
    text: `str`
        The text content of the message.
    model_output: `ModelOutput`, optional
        The full model output if the role is "model". This contains candidates, images, and metadata.

    """

    role: str
    text: str
    model_output: ModelOutput | None = None

    def __str__(self) -> str:
        return f"{self.role.upper()}: {shorten(self.text, width=100)}"

    def __repr__(self) -> str:
        return f"ChatTurn(role={self.role!r}, text={shorten(self.text, width=100)!r})"


class ChatHistory(BaseModel):
    """Represents the complete history of a chat conversation, ordered from the latest turn to the oldest.

    Parameters
    ----------
    cid: `str`
        Chat ID.
    turns: `list[ChatTurn]`
        The list of messages in the conversation.

    """

    cid: str
    turns: list[ChatTurn]

    def __str__(self) -> str:
        return f"ChatHistory(cid={self.cid!r})"

    def __repr__(self) -> str:
        return f"ChatHistory(cid={self.cid!r}, turns={self.turns!r})"
