from pathlib import Path
from typing import Any

from httpx import AsyncClient
from pydantic import validate_call

from ..constants import Endpoint, Headers
from ..types.file import File

FILES_ENUM_INT = {
    "application/octet-stream": 0,
    "image": 1,
    "video": 2,
    "text": 3,
    "audio": 4,
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": 7,
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": 10,
    "application/pdf": 11,
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": 12,
    "application/json": 16,
}


@validate_call
async def upload_file(file: File, proxy: str | None = None) -> list[Any]:
    """
    Upload a file to Google's server and return its identifier.

    Parameters
    ----------
    file : `str` | `Path`
        Path to the file to be uploaded.
    proxy: `str`, optional
        Proxy URL.

    Returns
    -------
    `list[Any | list[Any | None | str] | str]`
        A list containing the file identifier, file-type int, None, and the MIME type,
        along with the file name.

    Raises
    ------
    `httpx.HTTPStatusError`
        If the upload request failed.
    """

    filename = parse_file_name(file.path)
    file_code = get_file_id(file)

    with open(file.path, "rb") as f:
        file_content = f.read()

    data = f"File name: {filename}"

    async with AsyncClient(proxy=proxy) as client:
        response = await client.post(
            url=Endpoint.UPLOAD.value,
            headers=dict(
                **Headers.UPLOAD.value,
                **{
                    "x-goog-upload-command": "start",
                    "x-goog-upload-header-content-length": str(len(file_content)),
                },
            ),
            content=data,
        )
        response.raise_for_status()

        upload_url = response.headers.get("x-goog-upload-url")

        if not upload_url:
            raise ValueError("Upload URL not found in the response headers.")

        response = await client.post(
            url=upload_url,
            headers=dict(
                **Headers.UPLOAD.value,
                **{
                    "x-goog-upload-command": "upload, finalize",
                    "x-goog-upload-offset": "0",
                },
            ),
            content=file_content,
            follow_redirects=True,
        )

        response.raise_for_status()
        return [[response.text, file_code, None, file.mime_type], filename]


def parse_file_name(file: str | Path) -> str:
    """
    Parse the file name from the given path.

    Parameters
    ----------
    file : `str` | `Path`
        Path to the file.

    Returns
    -------
    `str`
        File name with extension.
    """

    file = Path(file)
    if not file.is_file():
        raise ValueError(f"{file} is not a valid file.")

    return file.name


def get_file_id(file: File) -> int:
    """
    Get the file ID based on its MIME type.

    Parameters
    ----------
    file : `File`
        File object.

    Returns
    -------
    `int`
        File ID.
    """

    # If mime type doesn't start with application, then match the first part
    mime_type_key = (
        file.mime_type
        if file.mime_type.startswith("application")
        else file.mime_type.split("/")[0]
    )
    return FILES_ENUM_INT.get(mime_type_key, 0)
