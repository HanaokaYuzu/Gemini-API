from datetime import datetime

from pydantic import BaseModel


class ChatInfo(BaseModel):
    """
    Chat information from the user's account.

    Parameters
    ----------
    cid: `str`
        Chat ID.
    title: `str`
        The display title of the chat conversation.
    is_pinned: `bool`, optional
        Whether the chat is pinned in the user's account. Default is `False`.
    timestamp: `float`
        The modification timestamp of the chat, including seconds and nanoseconds.
    """

    cid: str
    title: str
    is_pinned: bool = False
    timestamp: float

    def __str__(self) -> str:
        pin = "[Pinned] " if self.is_pinned else ""
        title = self.title or f"Chat({self.cid})"
        dt = datetime.fromtimestamp(self.timestamp).strftime("%Y-%m-%d %H:%M:%S")
        return f"{pin}{title} ({dt})"

    def __repr__(self) -> str:
        return (
            f"ChatInfo(cid={self.cid!r}, title={self.title!r}, "
            f"is_pinned={self.is_pinned!r}, timestamp={self.timestamp!r})"
        )
