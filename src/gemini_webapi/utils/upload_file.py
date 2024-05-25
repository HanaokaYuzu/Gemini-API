from pathlib import Path

from httpx import AsyncClient
from pydantic import validate_call

from ..constants import Endpoint, Headers


@validate_call
async def upload_file(file: bytes | str | Path, proxies: dict | None = None) -> str:
    """
    Upload a file to Google's server and return its identifier.

    Parameters
    ----------
    file : `bytes` | `str` | `Path`
        File data in bytes, or path to the file to be uploaded.
    proxies: `dict`, optional
        Dict of proxies.

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

    if not isinstance(file, bytes):
        with open(file, "rb") as f:
            file = f.read()

    async with AsyncClient(proxies=proxies) as client:
        response = await client.post(
            url=Endpoint.UPLOAD.value,
            headers=Headers.UPLOAD.value,
            files={"file": file},
            follow_redirects=True,
        )
        response.raise_for_status()
        return response.text
