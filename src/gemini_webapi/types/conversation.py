import html
from datetime import datetime

from pydantic import BaseModel, field_validator


class ConversationTurn(BaseModel):
    """
    A single user+assistant exchange in a conversation history.

    Parameters
    ----------
    rid: `str`
        Reply ID for this turn.
    user_prompt: `str`
        The user's input text for this turn.
    assistant_response: `str`
        The assistant's response text.
    rcid: `str`
        Reply candidate ID for the chosen response.
    thoughts: `str`, optional
        Model's thought process, only populated with thinking models.
    timestamp: `datetime`, optional
        When this exchange occurred.
    """

    rid: str
    user_prompt: str
    assistant_response: str
    rcid: str
    thoughts: str | None = None
    timestamp: datetime | None = None

    def __str__(self):
        return self.assistant_response

    def __repr__(self):
        prompt_preview = (
            self.user_prompt[:30] + "..."
            if len(self.user_prompt) > 30
            else self.user_prompt
        )
        return f"ConversationTurn(rid='{self.rid}', prompt='{prompt_preview}')"

    @field_validator("user_prompt", "assistant_response", "thoughts", mode="before")
    @classmethod
    def decode_html(cls, value: str | None) -> str | None:
        if value:
            value = html.unescape(value)
        return value
