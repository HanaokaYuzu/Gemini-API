import os
import time
from pathlib import Path

from httpx import AsyncClient

from ..constants import Endpoint, Headers
from ..exceptions import AuthError


async def rotate_1psidts(cookies: dict, proxies: dict | None = None) -> str:
    """
    Refresh the __Secure-1PSIDTS cookie and store the refreshed cookie value in cache file.

    Parameters
    ----------
    cookies : `dict`
        Cookies to be used in the request.
    proxies: `dict`, optional
        Dict of proxies.

    Returns
    -------
    `str`
        New value of the __Secure-1PSIDTS cookie.

    Raises
    ------
    `gemini_webapi.AuthError`
        If request failed with 401 Unauthorized.
    `httpx.HTTPStatusError`
        If request failed with other status codes.
    """

    path = Path(__file__).parent / "temp"
    path.mkdir(parents=True, exist_ok=True)
    filename = f".cached_1psidts_{cookies['__Secure-1PSID']}.txt"
    path = path / filename

    # Check if the cache file was modified in the last minute to avoid 429 Too Many Requests
    if not (path.is_file() and time.time() - os.path.getmtime(path) <= 60):
        async with AsyncClient(proxies=proxies) as client:
            response = await client.post(
                url=Endpoint.ROTATE_COOKIES.value,
                headers=Headers.ROTATE_COOKIES.value,
                cookies=cookies,
                data='[000,"-0000000000000000000"]',
            )
            if response.status_code == 401:
                raise AuthError
            response.raise_for_status()

            if new_1psidts := response.cookies.get("__Secure-1PSIDTS"):
                path.write_text(new_1psidts)
                return new_1psidts
