from pathlib import Path

from httpx import AsyncClient
from pydantic import validate_call

from ..constants import Endpoint, Headers


@validate_call
async def upload_file(file: str | Path, proxy: str | None = None) -> str:
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
    `str`
        Identifier of the uploaded file.
        E.g. "/contrib_service/ttl_1d/1709764705i7wdlyx3mdzndme3a767pluckv4flj"

    Raises
    ------
    `httpx.HTTPStatusError`
        If the upload request failed.
    """

    with open(file, "rb") as f:
        file = f.read()

    async with AsyncClient(http2=True, proxy=proxy) as client:
        response = await client.post(
            url=Endpoint.UPLOAD.value,
            headers=Headers.UPLOAD.value,
            files={"file": file},
            follow_redirects=True,
        )
        response.raise_for_status()
        return response.text


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
