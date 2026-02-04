import io
import random
from pathlib import Path

from httpx import AsyncClient
from pydantic import ConfigDict, validate_call

from ..constants import Endpoint, Headers


def _generate_random_name(extension: str = ".txt") -> str:
    """
    Generate a random filename using a large integer for better performance.
    """

    return f"input_{random.randint(1000000, 9999999)}{extension}"


@validate_call(config=ConfigDict(arbitrary_types_allowed=True))
async def upload_file(
    file: str | Path | bytes | io.BytesIO,
    proxy: str | None = None,
    filename: str | None = None,
) -> str:
    """
    Upload a file to Google's server and return its identifier.

    Parameters
    ----------
    file : `str` | `Path` | `bytes` | `io.BytesIO`
        Path to the file or file content to be uploaded.
    proxy: `str`, optional
        Proxy URL.
    filename: `str`, optional
        Name of the file to be uploaded. Required if file is bytes or BytesIO.

    Returns
    -------
    `str`
        Identifier of the uploaded file.
        E.g. "/contrib_service/ttl_1d/1709764705i7wdlyx3mdzndme3a767pluckv4flj"

    Raises
    ------
    `httpx.HTTPStatusError`
        If the upload request failed.
    """

    if isinstance(file, (str, Path)):
        file_path = Path(file)
        if not file_path.is_file():
            raise ValueError(f"{file_path} is not a valid file.")
        if not filename:
            filename = file_path.name
        file_content = file_path.read_bytes()
    elif isinstance(file, io.BytesIO):
        file_content = file.getvalue()
        if not filename:
            filename = _generate_random_name()
    elif isinstance(file, bytes):
        file_content = file
        if not filename:
            filename = _generate_random_name()
    else:
        raise ValueError(f"Unsupported file type: {type(file)}")

    async with AsyncClient(http2=True, proxy=proxy) as client:
        response = await client.post(
            url=Endpoint.UPLOAD,
            headers=Headers.UPLOAD.value,
            files={"file": (filename, file_content)},
            follow_redirects=True,
        )
        response.raise_for_status()
        return response.text


def parse_file_name(file: str | Path | bytes | io.BytesIO) -> str:
    """
    Parse the file name from the given path or generate a random one for in-memory data.

    Parameters
    ----------
    file : `str` | `Path` | `bytes` | `io.BytesIO`
        Path to the file or file content.

    Returns
    -------
    `str`
        File name with extension.
    """

    if isinstance(file, (str, Path)):
        file = Path(file)
        if not file.is_file():
            raise ValueError(f"{file} is not a valid file.")
        return file.name

    return _generate_random_name()
