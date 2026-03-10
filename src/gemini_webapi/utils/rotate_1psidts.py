import os
import time
from pathlib import Path

import orjson as json

from curl_cffi.requests import AsyncSession, Cookies

from ..constants import Endpoint, Headers
from ..exceptions import AuthError
from .logger import logger


def _extract_cookie_value(cookies: Cookies, name: str) -> str | None:
    """
    Extract a cookie value from a curl_cffi Cookies jar, trying domain-specific
    lookups first to avoid CookieConflict, then falling back to iteration.
    """
    for domain in (
        ".google.com",
        "google.com",
        ".accounts.google.com",
        "accounts.google.com",
    ):
        value = cookies.get(name, domain=domain)
        if value:
            return value

    for cookie in cookies.jar:
        if cookie.name == name:
            return cookie.value

    return None


async def rotate_1psidts(client: AsyncSession, verbose: bool = False) -> str | None:
    """
    Refresh the __Secure-1PSIDTS cookie and store the refreshed cookie value in cache file.

    Parameters
    ----------
    client : `curl_cffi.requests.AsyncSession`
        The shared async session to use for the request.
    verbose: `bool`, optional
        If `True`, will print more infomation in logs.

    Returns
    -------
    `str | None`
        New value of the __Secure-1PSIDTS cookie if rotation was successful.

    Raises
    ------
    `gemini_webapi.AuthError`
        If request failed with 401 Unauthorized.
    `curl_cffi.requests.exceptions.HTTPError`
        If request failed with other status codes.
    """

    gemini_cookie_path = os.getenv("GEMINI_COOKIE_PATH")
    if gemini_cookie_path:
        path = Path(gemini_cookie_path)
    else:
        path = Path(__file__).parent / "temp"
    path.mkdir(parents=True, exist_ok=True)

    # Safely get __Secure-1PSID value for filename
    secure_1psid = _extract_cookie_value(client.cookies, "__Secure-1PSID")

    if not secure_1psid:
        return None

    filename = f".cached_cookies_{secure_1psid}.json"
    path = path / filename

    # Check if the cache file was modified in the last minute to avoid 429 Too Many Requests
    if path.is_file() and time.time() - os.path.getmtime(path) <= 60:
        if verbose:
            logger.debug("Rotation skipped, cache is still fresh (< 60s).")
        return _extract_cookie_value(client.cookies, "__Secure-1PSIDTS")

    response = await client.post(
        url=Endpoint.ROTATE_COOKIES,
        headers=Headers.ROTATE_COOKIES.value,
        data='[000,"-0000000000000000000"]',
    )
    if verbose:
        logger.debug(
            f"HTTP Request: POST {Endpoint.ROTATE_COOKIES} [{response.status_code}]"
        )
    if response.status_code == 401:
        raise AuthError
    response.raise_for_status()

    new_1psidts = _extract_cookie_value(client.cookies, "__Secure-1PSIDTS")

    if new_1psidts:
        cookie_list = []
        for cookie in client.cookies.jar:
            # Only save persistent cookies for .google.com
            if (
                cookie.domain == ".google.com"
                and cookie.expires
                and not cookie.is_expired()
            ):
                cookie_list.append(
                    {
                        "name": cookie.name,
                        "value": cookie.value,
                        "domain": cookie.domain,
                        "path": cookie.path,
                        "expires": cookie.expires,
                    }
                )
        path.write_text(json.dumps(cookie_list).decode("utf-8"))
        path.chmod(0o600)  # Restrict cookie cache to owner read/write only
        logger.debug(
            f"Rotated and cached cookies successfully ({len(cookie_list)} cookies)."
        )
        return new_1psidts

    cookie_names = [c.name for c in client.cookies.jar]
    logger.debug(f"Rotation response cookies: {cookie_names}")
    return None
