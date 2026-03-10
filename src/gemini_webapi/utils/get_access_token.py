import os
import re
import time
from pathlib import Path

from curl_cffi.requests import AsyncSession, Cookies, Response

import orjson as json

from .load_browser_cookies import HAS_BC3, load_browser_cookies
from .logger import logger
from .rotate_1psidts import _extract_cookie_value
from ..constants import Endpoint, Headers
from ..exceptions import AuthError


async def send_request(
    client: AsyncSession, cookies: dict | Cookies, verbose: bool = False
) -> Response:
    """
    Send http request with provided cookies using a shared session.
    """
    client.cookies.clear()
    if isinstance(cookies, Cookies):
        client.cookies.update(cookies)
    else:
        for k, v in cookies.items():
            client.cookies.set(k, v, domain=".google.com")

    response = await client.get(Endpoint.INIT, headers=Headers.GEMINI.value)
    if verbose:
        logger.debug(f"HTTP Request: GET {Endpoint.INIT} [{response.status_code}]")
    response.raise_for_status()
    return response


async def get_access_token(
    base_cookies: dict | Cookies,
    proxy: str | None = None,
    verbose: bool = False,
    verify: bool = True,
) -> tuple[str | None, str | None, str | None, AsyncSession]:
    """
    Send a get request to gemini.google.com for each group of available cookies and return
    the value of "SNlM0e" as access token on the first successful request.

    Parameters
    ----------
    base_cookies: `dict | curl_cffi.requests.Cookies`
        Initial cookies to try. Can be a dictionary or a Cookies object.
    proxy: `str`, optional
        Proxy URL.
    verbose: `bool`, optional
        If True, log more details.
    verify: `bool`, optional
        Whether to verify SSL certificates.

    Returns the **live** AsyncSession that succeeded so the caller can reuse
    the same TLS connection for subsequent requests.
    """

    client = AsyncSession(
        impersonate="chrome", proxy=proxy, allow_redirects=True, verify=verify
    )

    try:
        response = await client.get(Endpoint.GOOGLE)
        if verbose:
            logger.debug(
                f"HTTP Request: GET {Endpoint.GOOGLE} [{response.status_code}]"
            )
        preflight_cookies = Cookies(client.cookies)
    except Exception:
        await client.close()
        raise

    extra_cookies = Cookies()
    if response.status_code == 200:
        extra_cookies = preflight_cookies

    # Phase 1: Prepare Cache
    cookie_jars_to_test = []
    tried_psid_ts = set()

    if isinstance(base_cookies, Cookies):
        base_psid = _extract_cookie_value(base_cookies, "__Secure-1PSID")
        base_psidts = _extract_cookie_value(base_cookies, "__Secure-1PSIDTS")
    else:
        base_psid = base_cookies.get("__Secure-1PSID")
        base_psidts = base_cookies.get("__Secure-1PSIDTS")

    gemini_cookie_path = os.getenv("GEMINI_COOKIE_PATH")
    if gemini_cookie_path:
        cache_dir = Path(gemini_cookie_path)
    else:
        cache_dir = Path(__file__).parent / "temp"

    if base_psid:
        filename = f".cached_cookies_{base_psid}.json"
        cache_file = cache_dir / filename

        if cache_file.is_file():
            content = cache_file.read_text().strip()
            if content:
                jar = Cookies(extra_cookies)
                if isinstance(base_cookies, dict):
                    for name, value in base_cookies.items():
                        jar.set(name, value, domain=".google.com", path="/")
                else:
                    jar.update(base_cookies)
                try:
                    cookies_data = json.loads(content)
                    for cookie in cookies_data:
                        # Skip expired cookies
                        expires = cookie.get("expires")
                        if expires and expires < time.time():
                            continue

                        jar.set(
                            cookie["name"],
                            cookie["value"],
                            domain=cookie.get("domain", ".google.com"),
                            path=cookie.get("path", "/"),
                        )
                    cookie_jars_to_test.append((jar, "Cache"))
                    tried_psid_ts.add(
                        (
                            base_psid,
                            _extract_cookie_value(jar, "__Secure-1PSIDTS") or "",
                        )
                    )
                except Exception as e:
                    logger.warning(f"Failed to parse cached cookies as JSON: {e}")
            elif verbose:
                logger.debug("Skipping loading cached cookies. Cache file is empty.")
        elif verbose:
            logger.debug("Skipping loading cached cookies. Cache file not found.")

    if not base_psid:
        cache_files = list(cache_dir.glob(".cached_cookies_*.json"))
        if cache_files:
            # Only use the most recently modified cache file as the default
            cache_file = max(cache_files, key=lambda p: p.stat().st_mtime)
            psid = cache_file.stem[16:]
            content = cache_file.read_text().strip()
            if content:
                jar = Cookies(extra_cookies)
                try:
                    cookies_data = json.loads(content)
                    for cookie in cookies_data:
                        # Skip expired cookies
                        expires = cookie.get("expires")
                        if expires and expires < time.time():
                            continue

                        jar.set(
                            cookie["name"],
                            cookie["value"],
                            domain=cookie.get("domain", ".google.com"),
                            path=cookie.get("path", "/"),
                        )
                    cookie_jars_to_test.append((jar, "Cache (Latest)"))
                    tried_psid_ts.add(
                        (psid, _extract_cookie_value(jar, "__Secure-1PSIDTS") or "")
                    )
                except Exception as e:
                    logger.warning(f"Failed to parse cached cookies as JSON: {e}")

    # Phase 2: Base Cookies
    if base_psid and base_psidts:
        if (base_psid, base_psidts) not in tried_psid_ts:
            jar = Cookies(extra_cookies)
            if isinstance(base_cookies, dict):
                for name, value in base_cookies.items():
                    jar.set(name, value, domain=".google.com", path="/")
            else:
                for cookie in base_cookies.jar:
                    if not cookie.is_expired():
                        jar.set(
                            cookie.name,
                            cookie.value,
                            domain=cookie.domain or ".google.com",
                            path=cookie.path or "/",
                        )
            cookie_jars_to_test.append((jar, "Base Cookies"))
            tried_psid_ts.add((base_psid, base_psidts))
        elif verbose:
            logger.debug("Skipping base cookies as they match cached cookies.")
    elif verbose and not cookie_jars_to_test:
        logger.debug(
            "Skipping loading base cookies. Either __Secure-1PSID or __Secure-1PSIDTS is not provided."
        )

    # Phase 3: Browser Cookies
    try:
        browser_cookies = load_browser_cookies(
            domain_name="google.com", verbose=verbose
        )
        if browser_cookies:
            for browser, cookie_list in browser_cookies.items():
                # Extract identifiers for matching and deduplication
                temp_cookies = {c["name"]: c["value"] for c in cookie_list}
                secure_1psid = temp_cookies.get("__Secure-1PSID")
                secure_1psidts = temp_cookies.get("__Secure-1PSIDTS")

                if secure_1psid:
                    if base_psid and base_psid != secure_1psid:
                        if verbose:
                            logger.debug(
                                f"Skipping loading local browser cookies from {browser}. "
                                "__Secure-1PSID does not match the one provided."
                            )
                        continue

                    if (secure_1psid, secure_1psidts or "") in tried_psid_ts:
                        continue

                    jar = Cookies(extra_cookies)
                    for cookie in cookie_list:
                        jar.set(
                            cookie["name"],
                            cookie["value"],
                            domain=cookie["domain"],
                            path=cookie["path"],
                        )

                    cookie_jars_to_test.append((jar, f"Browser ({browser})"))
                    tried_psid_ts.add((secure_1psid, secure_1psidts or ""))
                    if verbose:
                        logger.debug(
                            f"Prepared local browser cookies from {browser} ({len(cookie_list)} cookies)"
                        )

        if (
            HAS_BC3
            and not any(group.startswith("Browser") for _, group in cookie_jars_to_test)
            and verbose
        ):
            logger.debug(
                "Skipping loading local browser cookies. Login to gemini.google.com in your browser first."
            )
    except Exception:
        if verbose:
            logger.debug(
                "Skipping loading local browser cookies (Not available or no permission)."
            )

    current_attempt = 0
    for jar, group_name in cookie_jars_to_test:
        current_attempt += 1
        try:
            res = await send_request(client, jar, verbose=verbose)
            snlm0e = re.search(r'"SNlM0e":\s*"(.*?)"', res.text)
            cfb2h = re.search(r'"cfb2h":\s*"(.*?)"', res.text)
            fdrfje = re.search(r'"FdrFJe":\s*"(.*?)"', res.text)
            if snlm0e or cfb2h or fdrfje:
                if verbose:
                    logger.debug(
                        f"Init attempt ({current_attempt}) from {group_name} succeeded."
                    )
                return (
                    snlm0e.group(1) if snlm0e else None,
                    cfb2h.group(1) if cfb2h else None,
                    fdrfje.group(1) if fdrfje else None,
                    client,
                )
        except Exception:
            if verbose:
                logger.debug(
                    f"Init attempt ({current_attempt}) from {group_name} failed."
                )

    await client.close()
    raise AuthError(
        f"Failed to initialize client after {current_attempt} attempts. SECURE_1PSIDTS could get expired frequently, please make sure cookie values are up to date."
    )
