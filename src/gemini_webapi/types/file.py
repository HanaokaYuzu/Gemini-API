from pathlib import Path
from typing import TypedDict

from pydantic import BaseModel, field_validator


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

    @field_validator("mime_type")
    @classmethod
    def validate_mime_type(cls, v: str) -> str:
        if not v or "/" not in v:
            raise ValueError(f"Invalid MIME type format: {v}")
        return v
