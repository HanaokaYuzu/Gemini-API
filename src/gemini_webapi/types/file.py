import mimetypes
from pathlib import Path
from typing import TypedDict

from pydantic import BaseModel, model_validator
from typing_extensions import NotRequired


class FileDict(TypedDict):
    path: str | Path
    mime_type: NotRequired[str]


class File(BaseModel):
    """
    File object to be uploaded to Gemini.

    Parameters
    ----------
    path: `str | Path`
        Path to the file to be uploaded.
    mime_type: `str`, optional
        MIME type of the file. If not provided, it will be guessed from the file extension.
    """

    path: str | Path
    mime_type: str | None = None

    @model_validator(mode="after")
    def validate_mime_type(self) -> "File":
        if not self.mime_type:
            self.mime_type = mimetypes.guess_type(str(self.path))[0]

        if not self.mime_type or "/" not in self.mime_type:
            raise ValueError(f"Invalid MIME type: {self.mime_type}")
        return self
