import io
import mimetypes
import random
from pathlib import Path

from curl_cffi import CurlMime
from curl_cffi.requests import AsyncSession
from pydantic import ConfigDict, validate_call

from .logger import logger
from ..constants import Endpoint, Headers


def _generate_random_name(extension: str = ".txt") -> str:
    """
    Generate a random filename using a large integer for better performance.
    """

    return f"input_{random.randint(1000000, 9999999)}{extension}"


@validate_call(config=ConfigDict(arbitrary_types_allowed=True))
async def upload_file(
    file: str | Path | bytes | io.BytesIO,
    client: AsyncSession,
    push_id: str,
    filename: str | None = None,
    verbose: bool = False,
) -> str:
    """
    Upload a file to Google's server and return its identifier.

    Parameters
    ----------
    file : `str` | `Path` | `bytes` | `io.BytesIO`
        Path to the file or file content to be uploaded.
    client: `curl_cffi.requests.AsyncSession`
        Shared async session to use for upload.
    push_id: `str`
        Push-ID header.
    filename: `str`, optional
        Name of the file to be uploaded. Required if file is bytes or BytesIO.
    verbose: `bool`, optional
        If `True`, will print more infomation in logs.

    Returns
    -------
    `str`
        Identifier of the uploaded file.
        E.g. "/contrib_service/ttl_1d/1709764705i7wdlyx3mdzndme3a767pluckv4flj"

    Raises
    ------
    `curl_cffi.requests.exceptions.HTTPError`
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

    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"

    mime_part = CurlMime()
    mime_part.addpart(
        name="file",
        content_type=content_type,
        filename=filename,
        data=file_content,
    )

    try:
        request_headers = {
            **Headers.REFERER.value,
            **Headers.UPLOAD.value,
            "Push-ID": push_id,
        }

        response = await client.post(
            url=Endpoint.UPLOAD,
            headers=request_headers,
            multipart=mime_part,
            allow_redirects=True,
        )
        if verbose:
            logger.debug(
                f"HTTP Request: POST {Endpoint.UPLOAD} [{response.status_code}]"
            )
        response.raise_for_status()
        return response.text
    finally:
        mime_part.close()


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
