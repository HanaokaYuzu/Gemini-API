import os
import tempfile
import time
from pathlib import Path

import orjson as json
from curl_cffi.requests import AsyncSession, Cookies

from .logger import logger
from ..constants import Endpoint, Headers
from ..exceptions import AuthError


def _extract_cookie_value(cookies: Cookies, name: str) -> str | None:
    """
    Extract a cookie value from a curl_cffi Cookies jar.
    """

    for cookie in cookies.jar:
        if cookie.name == name:
            return cookie.value

    return None


def _get_cookie_cache_dir() -> Path:
    """
    Lazy helper to get the cookie cache directory.
    """

    _path = os.getenv("GEMINI_COOKIE_PATH")
    return Path(_path) if _path else Path(tempfile.gettempdir()) / "gemini_webapi"


def _get_cookies_cache_path(cookies: Cookies, verbose: bool = False) -> Path | None:
    """
    Helper to get and ensure the cache file path based on __Secure-1PSID.
    """

    secure_1psid = _extract_cookie_value(cookies, "__Secure-1PSID")
    if not secure_1psid:
        if verbose:
            logger.warning("Cannot save cookies: __Secure-1PSID not found.")
        return None

    return _get_cookie_cache_dir() / f".cached_cookies_{secure_1psid}.json"


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

    path = _get_cookies_cache_path(client.cookies, verbose)
    if not path:
        return None

    # Check if the cache file was modified in the last minute to avoid 429 Too Many Requests
    if path.is_file() and time.time() - path.stat().st_mtime <= 60:
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

    save_cookies(client.cookies, verbose)
    new_1psidts = _extract_cookie_value(client.cookies, "__Secure-1PSIDTS")

    if new_1psidts:
        return new_1psidts

    cookie_names = [c.name for c in client.cookies.jar]
    logger.debug(
        f"Rotation completed but __Secure-1PSIDTS not found. Response cookies: {cookie_names}"
    )
    return None


def save_cookies(cookies: Cookies, verbose: bool = False) -> None:
    """
    Save persistent cookies to cache file.
    """

    path = _get_cookies_cache_path(cookies, verbose)
    if not path:
        return

    cookie_list = []
    for cookie in cookies.jar:
        is_auth_cookie = cookie.name in ["__Secure-1PSID", "__Secure-1PSIDTS"]
        domain = cookie.domain.lstrip(".").lower() if cookie.domain else ""
        is_google_domain = domain == "google.com" or domain.endswith(".google.com")
        if is_google_domain and (
            is_auth_cookie or (cookie.expires is not None and not cookie.is_expired())
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

    if cookie_list:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cookie_list).decode("utf-8"))
        path.chmod(0o600)  # Restrict cookie cache to owner read/write only
        if verbose:
            logger.debug(
                f"Saved cookies to cache successfully ({len(cookie_list)} cookies)."
            )
