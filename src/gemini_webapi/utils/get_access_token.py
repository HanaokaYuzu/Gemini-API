import re
import asyncio
from asyncio import Task
from pathlib import Path

from httpx import AsyncClient, Response

from ..constants import Endpoint, Headers
from ..exceptions import AuthError
from .load_browser_cookies import load_browser_cookies
from .logger import logger


async def get_access_token(
    base_cookies: dict, proxies: dict | None = None, verbose: bool = False
) -> tuple[str, dict]:
    """
    Send a get request to gemini.google.com for each group of available cookies and return
    the value of "SNlM0e" as access token on the first successful request.

    Possible cookie sources:
    - Base cookies passed to the function.
    - __Secure-1PSID from base cookies with __Secure-1PSIDTS from cache.
    - Local browser cookies (if optional dependency `browser-cookie3` is installed).

    Parameters
    ----------
    base_cookies : `dict`
        Base cookies to be used in the request.
    proxies: `dict`, optional
        Dict of proxies.
    verbose: `bool`, optional
        If `True`, will print more infomation in logs.

    Returns
    -------
    `str`
        Access token.
    `dict`
        Cookies of the successful request.

    Raises
    ------
    `gemini_webapi.AuthError`
        If all requests failed.
    """

    async def send_request(cookies: dict) -> tuple[Response | None, dict]:
        async with AsyncClient(
            proxies=proxies,
            headers=Headers.GEMINI.value,
            cookies=cookies,
            follow_redirects=True,
        ) as client:
            response = await client.get(Endpoint.INIT.value)
            response.raise_for_status()
            return response, cookies

    tasks = []

    if "__Secure-1PSID" in base_cookies:
        tasks.append(Task(send_request(base_cookies)))

        filename = f".cached_1psidts_{base_cookies['__Secure-1PSID']}.txt"
        path = Path(__file__).parent / "temp" / filename
        if path.is_file():
            cached_1psidts = path.read_text()
            if cached_1psidts:
                cached_cookies = {**base_cookies, "__Secure-1PSIDTS": cached_1psidts}
                tasks.append(Task(send_request(cached_cookies)))
            elif verbose:
                logger.debug("Skipping loading cached cookies. Cache file is empty.")
        elif verbose:
            logger.debug("Skipping loading cached cookies. Cache file not found.")
    elif verbose:
        logger.debug(
            "Skipping loading base cookies and cached cookies. __Secure-1PSID is not provided."
        )

    try:
        browser_cookies = load_browser_cookies(
            domain_name="google.com", verbose=verbose
        )
        if browser_cookies and (secure_1psid := browser_cookies.get("__Secure-1PSID")):
            local_cookies = {"__Secure-1PSID": secure_1psid}
            if secure_1psidts := browser_cookies.get("__Secure-1PSIDTS"):
                local_cookies["__Secure-1PSIDTS"] = secure_1psidts
            tasks.append(Task(send_request(local_cookies)))
        elif verbose:
            logger.debug(
                "Skipping loading local browser cookies. Login to gemini.google.com in your browser first."
            )
    except ImportError:
        if verbose:
            logger.debug(
                "Skipping loading local browser cookies. Optional dependency 'browser-cookie3' is not installed."
            )
    except Exception as e:
        if verbose:
            logger.warning(f"Skipping loading local browser cookies. {e}")

    for i, future in enumerate(asyncio.as_completed(tasks)):
        try:
            response, request_cookies = await future
            match = re.search(r'"SNlM0e":"(.*?)"', response.text)
            if match:
                if verbose:
                    logger.debug(
                        f"Init attempt ({i + 1}/{len(tasks)}) succeeded. Initializing client..."
                    )
                return match.group(1), request_cookies
            elif verbose:
                logger.debug(
                    f"Init attempt ({i + 1}/{len(tasks)}) failed. Cookies invalid."
                )
        except Exception as e:
            if verbose:
                logger.debug(
                    f"Init attempt ({i + 1}/{len(tasks)}) failed with error: {e}"
                )

    raise AuthError(
        "Failed to initialize client. SECURE_1PSIDTS could get expired frequently, please make sure cookie values are up to date."
    )
