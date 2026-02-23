import asyncio
import os
import re
from pathlib import Path

from curl_cffi.requests import AsyncSession, Cookies, Response

from .load_browser_cookies import HAS_BC3, load_browser_cookies
from .logger import logger
from .rotate_1psidts import _extract_cookie_value
from ..constants import Endpoint, Headers
from ..exceptions import AuthError


async def send_request(
    cookies: dict | Cookies, proxy: str | None = None, verbose: bool = False
) -> tuple[Response | None, Cookies]:
    """
    Send http request with provided cookies.
    """

    async with AsyncSession(
        impersonate="chrome",
        proxy=proxy,
        headers=Headers.GEMINI.value,
        cookies=cookies,
        allow_redirects=True,
    ) as client:
        response = await client.get(Endpoint.INIT)
        if verbose:
            logger.debug(f"HTTP Request: GET {Endpoint.INIT} [{response.status_code}]")
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
    base_cookies : `dict | curl_cffi.requests.Cookies`
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

    async with AsyncSession(
        impersonate="chrome", proxy=proxy, allow_redirects=True, verify=verify
    ) as client:
        response = await client.get(Endpoint.GOOGLE)
        if verbose:
            logger.debug(
                f"HTTP Request: GET {Endpoint.GOOGLE} [{response.status_code}]"
            )
        preflight_cookies = client.cookies

    extra_cookies = Cookies()
    if response.status_code == 200:
        extra_cookies = preflight_cookies

    # Phase 1: Prepare & Try Cache (Highest Priority)
    cache_tasks = []
    tried_psid_ts = set()

    if isinstance(base_cookies, Cookies):
        base_psid = _extract_cookie_value(base_cookies, "__Secure-1PSID")
        base_psidts = _extract_cookie_value(base_cookies, "__Secure-1PSIDTS")
    else:
        base_psid = base_cookies.get("__Secure-1PSID")
        base_psidts = base_cookies.get("__Secure-1PSIDTS")

    cache_dir = (
        (GEMINI_COOKIE_PATH := os.getenv("GEMINI_COOKIE_PATH"))
        and Path(GEMINI_COOKIE_PATH)
        or (Path(__file__).parent / "temp")
    )

    if base_psid:
        filename = f".cached_1psidts_{base_psid}.txt"
        cache_file = cache_dir / filename
        if cache_file.is_file():
            cached_1psidts = cache_file.read_text().strip()
            if cached_1psidts:
                jar = Cookies(extra_cookies)
                jar.update(base_cookies)
                jar.set("__Secure-1PSIDTS", cached_1psidts, domain=".google.com")
                cache_tasks.append(
                    asyncio.create_task(send_request(jar, proxy=proxy, verbose=verbose))
                )
                tried_psid_ts.add((base_psid, cached_1psidts))
            elif verbose:
                logger.debug("Skipping loading cached cookies. Cache file is empty.")
        elif verbose:
            logger.debug("Skipping loading cached cookies. Cache file not found.")

    if not base_psid:
        for cache_file in cache_dir.glob(".cached_1psidts_*.txt"):
            psid = cache_file.stem[16:]
            cached_1psidts = cache_file.read_text().strip()
            if cached_1psidts:
                jar = Cookies(extra_cookies)
                jar.set("__Secure-1PSID", psid, domain=".google.com")
                jar.set("__Secure-1PSIDTS", cached_1psidts, domain=".google.com")
                cache_tasks.append(
                    asyncio.create_task(send_request(jar, proxy=proxy, verbose=verbose))
                )
                tried_psid_ts.add((psid, cached_1psidts))

    async def try_run_group(tasks, group_name):
        nonlocal current_attempt
        if not tasks:
            return None

        for future in asyncio.as_completed(tasks):
            current_attempt += 1
            try:
                res, request_cookies = await future
                snlm0e = re.search(r'"SNlM0e":\s*"(.*?)"', res.text)
                if snlm0e:
                    for t in tasks:
                        if not t.done():
                            t.cancel()

                    cfb2h = re.search(r'"cfb2h":\s*"(.*?)"', res.text)
                    fdrfje = re.search(r'"FdrFJe":\s*"(.*?)"', res.text)
                    if verbose:
                        logger.debug(
                            f"Init attempt ({current_attempt}) from {group_name} succeeded."
                        )
                    return (
                        snlm0e.group(1),
                        cfb2h.group(1) if cfb2h else None,
                        fdrfje.group(1) if fdrfje else None,
                        request_cookies,
                    )
            except asyncio.CancelledError:
                continue
            except Exception as err:
                if verbose:
                    logger.debug(
                        f"Init attempt ({current_attempt}) from {group_name} failed: {err}"
                    )
        return None

    current_attempt = 0

    result = await try_run_group(cache_tasks, "Cache")
    if result:
        return result

    # Phase 2: Base Cookies (If Cache failed)
    base_tasks = []
    if base_psid and base_psidts:
        if (base_psid, base_psidts) not in tried_psid_ts:
            jar = Cookies(extra_cookies)
            jar.update(base_cookies)
            base_tasks.append(
                asyncio.create_task(send_request(jar, proxy=proxy, verbose=verbose))
            )
            tried_psid_ts.add((base_psid, base_psidts))
        elif verbose:
            logger.debug("Skipping base cookies as they match cached cookies.")
    elif verbose and not cache_tasks:
        logger.debug(
            "Skipping loading base cookies. Either __Secure-1PSID or __Secure-1PSIDTS is not provided."
        )

    result = await try_run_group(base_tasks, "Base Cookies")
    if result:
        return result

    # Phase 3: Browser Cookies (Last Resort - Lazy Loaded)
    browser_tasks = []
    try:
        browser_cookies = load_browser_cookies(
            domain_name="google.com", verbose=verbose
        )
        if browser_cookies:
            for browser, cookies in browser_cookies.items():
                if secure_1psid := cookies.get("__Secure-1PSID"):
                    if base_psid and base_psid != secure_1psid:
                        if verbose:
                            logger.debug(
                                f"Skipping loading local browser cookies from {browser}. "
                                "__Secure-1PSID does not match the one provided."
                            )
                        continue

                    secure_1psidts = cookies.get("__Secure-1PSIDTS")
                    if (secure_1psid, secure_1psidts or "") in tried_psid_ts:
                        continue

                    local_cookies = {"__Secure-1PSID": secure_1psid}
                    if secure_1psidts:
                        local_cookies["__Secure-1PSIDTS"] = secure_1psidts
                    if nid := cookies.get("NID"):
                        local_cookies["NID"] = nid

                    browser_tasks.append(
                        asyncio.create_task(
                            send_request(local_cookies, proxy=proxy, verbose=verbose)
                        )
                    )
                    tried_psid_ts.add((secure_1psid, secure_1psidts or ""))
                    if verbose:
                        logger.debug(f"Prepared local browser cookies from {browser}")

        if HAS_BC3 and not browser_tasks and verbose:
            logger.debug(
                "Skipping loading local browser cookies. Login to gemini.google.com in your browser first."
            )
    except Exception as err:
        if verbose:
            logger.warning(f"Skipping loading local browser cookies. {err}")

    result = await try_run_group(browser_tasks, "Browser")
    if result:
        return result

    raise AuthError(
        f"Failed to initialize client after {current_attempt} attempts. SECURE_1PSIDTS could get expired frequently, please make sure cookie values are up to date."
    )
