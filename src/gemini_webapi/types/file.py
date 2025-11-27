from pathlib import Path
from typing import TypedDict

from pydantic import BaseModel


class FileDict(TypedDict):
    path: str | Path
    mime_type: str


class File(BaseModel):
    """
    File object to be uploaded to Gemini.

    Parameters
    ----------
    path: `str | Path`
        Path to the file to be uploaded.
    mime_type: `str`
        MIME type of the file.
    """
    path: str | Path
    mime_type: str
