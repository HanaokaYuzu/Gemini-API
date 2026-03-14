import os
import time
from pathlib import Path

from httpx import AsyncClient, Cookies

from ..constants import Endpoint, Headers
from ..exceptions import AuthError


async def rotate_1psidts(
    cookies: dict | Cookies, proxy: str | None = None
) -> tuple[str | None, Cookies | None]:
    """
    Refresh the __Secure-1PSIDTS cookie and store the refreshed cookie value in cache file.

    Parameters
    ----------
    cookies : `dict | httpx.Cookies`
        Cookies to be used in the request.
    proxy: `str`, optional
        Proxy URL.

    Returns
    -------
    `tuple[str | None, httpx.Cookies | None]`
        New value of the __Secure-1PSIDTS cookie and the full updated cookies jar.

    Raises
    ------
    `gemini_webapi.AuthError`
        If request failed with 401 Unauthorized.
    `httpx.HTTPStatusError`
        If request failed with other status codes.
    """

    path = (
        (GEMINI_COOKIE_PATH := os.getenv("GEMINI_COOKIE_PATH"))
        and Path(GEMINI_COOKIE_PATH)
        or (Path(__file__).parent / "temp")
    )
    path.mkdir(parents=True, exist_ok=True)

    # Safely get __Secure-1PSID value for filename
    if isinstance(cookies, Cookies):
        # Prefer .google.com domain to avoid CookieConflict
        secure_1psid = cookies.get(
            "__Secure-1PSID", domain=".google.com"
        ) or cookies.get("__Secure-1PSID")
    else:
        secure_1psid = cookies.get("__Secure-1PSID")

    if not secure_1psid:
        return None, None

    filename = f".cached_1psidts_{secure_1psid}.txt"
    path = path / filename

    # Check if the cache file was modified in the last minute to avoid 429 Too Many Requests
    if path.is_file() and time.time() - os.path.getmtime(path) <= 60:
        return path.read_text(), None

    async with AsyncClient(http2=True, proxy=proxy, follow_redirects=True) as client:
        merged_cookies = Cookies(cookies)

        # Bootstrap cookie context first. In some sessions, Google refreshes
        # *PSIDCC style cookies on GET before RotateCookies accepts the request.
        for bootstrap_url in (Endpoint.GOOGLE, "https://gemini.google.com/"):
            try:
                bootstrap_resp = await client.get(bootstrap_url, cookies=merged_cookies)
                if bootstrap_resp.cookies:
                    merged_cookies.update(bootstrap_resp.cookies)
            except Exception:
                pass

        response = await client.post(
            url=Endpoint.ROTATE_COOKIES,
            headers=Headers.ROTATE_COOKIES.value,
            cookies=merged_cookies,
            content='[000,"-0000000000000000000"]',
        )

        # One retry after refreshing bootstrap cookies if the first attempt is unauthorized.
        if response.status_code == 401:
            try:
                bootstrap_resp = await client.get(
                    "https://gemini.google.com/", cookies=merged_cookies
                )
                if bootstrap_resp.cookies:
                    merged_cookies.update(bootstrap_resp.cookies)
            except Exception:
                pass

            response = await client.post(
                url=Endpoint.ROTATE_COOKIES,
                headers=Headers.ROTATE_COOKIES.value,
                cookies=merged_cookies,
                content='[000,"-0000000000000000000"]',
            )

        if response.status_code == 401:
            raise AuthError
        response.raise_for_status()

        if new_1psidts := response.cookies.get("__Secure-1PSIDTS"):
            path.write_text(new_1psidts)
            path.chmod(0o600)  # Restrict cookie cache to owner read/write only
            return new_1psidts, response.cookies

        return None, response.cookies
