from httpx import AsyncClient
from pydantic import validate_call

from .constant import UPLOAD_PUSHID


@validate_call
async def upload_file(file: bytes | str) -> str:
    """
    Upload a file to Google's server and return its identifier.

    Parameters
    ----------
    file : `bytes` | `str`
        File data in bytes, or path to the file to be uploaded.

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

    if isinstance(file, str):
        with open(file, "rb") as f:
            file = f.read()

    async with AsyncClient() as client:
        response = await client.post(
            url="https://content-push.googleapis.com/upload/",
            headers={"Push-ID": UPLOAD_PUSHID},
            files={"file": file},
            follow_redirects=True,
        )
        response.raise_for_status()
        return response.text
