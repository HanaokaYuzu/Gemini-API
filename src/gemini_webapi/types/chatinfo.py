from pydantic import BaseModel


class ChatInfo(BaseModel):
    """
    Chat information from the user's account.

    Parameters
    ----------
    cid: `str`
        The ID of the chat conversation (cid).
    title: `str`
        The display title of the chat conversation.
    """

    cid: str
    title: str
    is_pinned: bool = False
