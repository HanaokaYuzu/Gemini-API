from pydantic import BaseModel

from .chatinfo import ChatInfo


class ChatListPage(BaseModel):
    """
    A single page of chat listing results with pagination cursor.

    Parameters
    ----------
    items: `list[ChatInfo]`
        Chat items on this page.
    cursor: `str`
        Next-page cursor. Empty string when there are no more pages.
    """

    items: list[ChatInfo]
    cursor: str = ""