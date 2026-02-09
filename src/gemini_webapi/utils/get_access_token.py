import os
import re
import asyncio
from asyncio import Task
from pathlib import Path

from httpx import AsyncClient, Cookies, Response

from ..constants import Endpoint, Headers
from ..exceptions import AuthError
from .load_browser_cookies import load_browser_cookies
from .logger import logger


async def send_request(
    cookies: dict | Cookies, proxy: str | None = None
) -> tuple[Response | None, Cookies]:
    """
    Send http request with provided cookies.
    """

    async with AsyncClient(
        http2=True,
        proxy=proxy,
        headers=Headers.GEMINI.value,
        cookies=cookies,
        follow_redirects=True,
    ) as client:
        response = await client.get(Endpoint.INIT)
        response.raise_for_status()
        return response, client.cookies


async def get_access_token(
    base_cookies: dict | Cookies,
    proxy: str | None = None,
    verbose: bool = False,
    verify: bool = True,
) -> tuple[str, Cookies, str | None, str | None]:
    """
    Send a get request to gemini.google.com for each group of available cookies and return
    the value of "SNlM0e" as access token on the first successful request.

    Possible cookie sources:
    - Base cookies passed to the function.
    - __Secure-1PSID from base cookies with __Secure-1PSIDTS from cache.
    - Local browser cookies (if optional dependency `browser-cookie3` is installed).

    Parameters
    ----------
    base_cookies : `dict | httpx.Cookies`
        Base cookies to be used in the request.
    proxy: `str`, optional
        Proxy URL.
    verbose: `bool`, optional
        If `True`, will print more infomation in logs.
    verify: `bool`, optional
        Whether to verify SSL certificates.

    Returns
    -------
    `tuple[str, str | None, str | None, Cookies]`
        By order: access token; build label; session id; cookies of the successful request.

    Raises
    ------
    `gemini_webapi.AuthError`
        If all requests failed.
    """

    async with AsyncClient(
        http2=True, proxy=proxy, follow_redirects=True, verify=verify
    ) as client:
        response = await client.get(Endpoint.GOOGLE)

    extra_cookies = Cookies()
    if response.status_code == 200:
        extra_cookies = response.cookies

    tasks = []

    # Base cookies passed directly on initializing client
    # We use a Jar to merge extra_cookies and base_cookies safely (preserving domains)
    if "__Secure-1PSID" in base_cookies and "__Secure-1PSIDTS" in base_cookies:
        jar = Cookies(extra_cookies)
        jar.update(base_cookies)
        tasks.append(Task(send_request(jar, proxy=proxy)))
    elif verbose:
        logger.debug(
            "Skipping loading base cookies. Either __Secure-1PSID or __Secure-1PSIDTS is not provided."
        )

    # Cached cookies in local file
    cache_dir = (
        (GEMINI_COOKIE_PATH := os.getenv("GEMINI_COOKIE_PATH"))
        and Path(GEMINI_COOKIE_PATH)
        or (Path(__file__).parent / "temp")
    )

    # Safely get __Secure-1PSID value
    if isinstance(base_cookies, Cookies):
        secure_1psid = base_cookies.get(
            "__Secure-1PSID", domain=".google.com"
        ) or base_cookies.get("__Secure-1PSID")
    else:
        secure_1psid = base_cookies.get("__Secure-1PSID")

    if secure_1psid:
        filename = f".cached_1psidts_{secure_1psid}.txt"
        cache_file = cache_dir / filename
        if cache_file.is_file():
            cached_1psidts = cache_file.read_text()
            if cached_1psidts:
                jar = Cookies(extra_cookies)
                jar.update(base_cookies)
                jar.set("__Secure-1PSIDTS", cached_1psidts, domain=".google.com")
                tasks.append(Task(send_request(jar, proxy=proxy)))
            elif verbose:
                logger.debug("Skipping loading cached cookies. Cache file is empty.")
        elif verbose:
            logger.debug("Skipping loading cached cookies. Cache file not found.")
    else:
        valid_caches = 0
        cache_files = cache_dir.glob(".cached_1psidts_*.txt")
        for cache_file in cache_files:
            cached_1psidts = cache_file.read_text()
            if cached_1psidts:
                jar = Cookies(extra_cookies)
                psid = cache_file.stem[16:]
                jar.set("__Secure-1PSID", psid, domain=".google.com")
                jar.set("__Secure-1PSIDTS", cached_1psidts, domain=".google.com")
                tasks.append(Task(send_request(jar, proxy=proxy)))
                valid_caches += 1

        if valid_caches == 0 and verbose:
            logger.debug(
                "Skipping loading cached cookies. Cookies will be cached after successful initialization."
            )

    # Browser cookies (if browser-cookie3 is installed)
    try:
        valid_browser_cookies = 0
        browser_cookies = load_browser_cookies(
            domain_name="google.com", verbose=verbose
        )
        if browser_cookies:
            for browser, cookies in browser_cookies.items():
                if secure_1psid := cookies.get("__Secure-1PSID"):
                    if (
                        "__Secure-1PSID" in base_cookies
                        and base_cookies["__Secure-1PSID"] != secure_1psid
                    ):
                        if verbose:
                            logger.debug(
                                f"Skipping loading local browser cookies from {browser}. "
                                f"__Secure-1PSID does not match the one provided."
                            )
                        continue

                    local_cookies = {"__Secure-1PSID": secure_1psid}
                    if secure_1psidts := cookies.get("__Secure-1PSIDTS"):
                        local_cookies["__Secure-1PSIDTS"] = secure_1psidts
                    if nid := cookies.get("NID"):
                        local_cookies["NID"] = nid
                    tasks.append(Task(send_request(local_cookies, proxy=proxy)))
                    valid_browser_cookies += 1
                    if verbose:
                        logger.debug(f"Loaded local browser cookies from {browser}")

        if valid_browser_cookies == 0 and verbose:
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

    if not tasks:
        raise AuthError(
            "No valid cookies available for initialization. Please pass __Secure-1PSID and __Secure-1PSIDTS manually."
        )

    for i, future in enumerate(asyncio.as_completed(tasks)):
        try:
            response, request_cookies = await future
            snlm0e = re.search(r'"SNlM0e":\s*"(.*?)"', response.text)
            if snlm0e:
                cfb2h = re.search(r'"cfb2h":\s*"(.*?)"', response.text)
                fdrfje = re.search(r'"FdrFJe":\s*"(.*?)"', response.text)
                if verbose:
                    logger.debug(
                        f"Init attempt ({i + 1}/{len(tasks)}) succeeded. Initializing client..."
                    )
                return (
                    snlm0e.group(1),
                    cfb2h.group(1) if cfb2h else None,
                    fdrfje.group(1) if fdrfje else None,
                    request_cookies,
                )
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
        "Failed to initialize client. SECURE_1PSIDTS could get expired frequently, please make sure cookie values are up to date. "
        f"(Failed initialization attempts: {len(tasks)})"
    )
