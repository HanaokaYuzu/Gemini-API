import re
import time

from curl_cffi.requests import AsyncSession, Cookies, Response
import orjson as json

from .load_browser_cookies import HAS_BC3, load_browser_cookies
from .logger import logger
from .rotate_1psidts import (
    _extract_cookie_value,
    _get_cookies_cache_path,
    _get_cookie_cache_dir,
)
from ..constants import Endpoint, Headers
from ..exceptions import AuthError


async def _send_request(
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
) -> tuple[str | None, str | None, str | None, str | None, str | None, AsyncSession]:
    """
    Send a get request to gemini.google.com for each group of available cookies and return
    the value of "SNlM0e" as access token on the first successful request.

    Returns the **live** AsyncSession that succeeded so the caller can reuse
    the same TLS connection for subsequent requests.

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

    Returns
    -------
    `tuple[str | None, str | None, str | None, str | None, str | None, AsyncSession]`
        By order: access token; build label; session id; language; file push id; live AsyncSession of the successful request.

    Raises
    ------
    `gemini_webapi.AuthError`
        If all requests failed.
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
    tried_sessions: dict[str, set[str]] = {}

    if isinstance(base_cookies, Cookies):
        base_psid = _extract_cookie_value(base_cookies, "__Secure-1PSID")
        base_psidts = _extract_cookie_value(base_cookies, "__Secure-1PSIDTS")
    else:
        base_psid = base_cookies.get("__Secure-1PSID")
        base_psidts = base_cookies.get("__Secure-1PSIDTS")

    if base_psid:
        jar = Cookies()
        jar.set("__Secure-1PSID", base_psid, domain=".google.com")
        cache_file = _get_cookies_cache_path(jar)

        if cache_file and cache_file.is_file():
            content = cache_file.read_text().strip()
            if content:
                jar = Cookies()
                if isinstance(base_cookies, Cookies):
                    for cookie in base_cookies.jar:
                        if not cookie.is_expired():
                            jar.set(
                                str(cookie.name),
                                str(cookie.value),
                                domain=cookie.domain,
                                path=cookie.path,
                            )
                else:
                    for name, value in base_cookies.items():
                        if value:
                            jar.set(name, value, domain=".google.com", path="/")

                try:
                    cookies_data = json.loads(content)
                    for cookie in cookies_data:
                        expires = cookie.get("expires")
                        if expires and expires < time.time():
                            continue

                        jar.set(
                            cookie["name"],
                            cookie["value"],
                            domain=cookie.get("domain", ".google.com"),
                            path=cookie.get("path", "/"),
                        )

                    jar.update(extra_cookies)
                    cookie_jars_to_test.append((jar, "Cache"))
                    psidts = _extract_cookie_value(jar, "__Secure-1PSIDTS") or ""
                    tried_sessions.setdefault(base_psid, set()).add(psidts)
                except Exception as e:
                    logger.warning(f"Failed to parse cached cookies as JSON: {e}")
            elif verbose:
                logger.debug("Skipping loading cached cookies. Cache file is empty.")
        elif verbose:
            logger.debug("Skipping loading cached cookies. Cache file not found.")

    if not base_psid:
        cache_files = list(_get_cookie_cache_dir().glob(".cached_cookies_*.json"))
        if cache_files:
            cache_file = max(cache_files, key=lambda p: p.stat().st_mtime)
            psid = cache_file.stem[16:]
            content = cache_file.read_text().strip()
            if content:
                jar = Cookies()
                try:
                    cookies_data = json.loads(content)
                    for cookie in cookies_data:
                        expires = cookie.get("expires")
                        if expires and expires < time.time():
                            continue

                        jar.set(
                            cookie["name"],
                            cookie["value"],
                            domain=cookie.get("domain", ".google.com"),
                            path=cookie.get("path", "/"),
                        )

                    jar.update(extra_cookies)
                    cookie_jars_to_test.append((jar, "Cache (Latest)"))
                    psidts = _extract_cookie_value(jar, "__Secure-1PSIDTS") or ""
                    tried_sessions.setdefault(psid, set()).add(psidts)
                except Exception as e:
                    logger.warning(f"Failed to parse cached cookies as JSON: {e}")

    # Phase 2: Base Cookies
    if base_psid:
        psidts = base_psidts or ""
        if psidts not in tried_sessions.get(base_psid, set()):
            jar = Cookies()
            if isinstance(base_cookies, Cookies):
                for cookie in base_cookies.jar:
                    if not cookie.is_expired():
                        jar.set(
                            cookie.name,
                            cookie.value,
                            domain=cookie.domain,
                            path=cookie.path,
                        )
            else:
                for name, value in base_cookies.items():
                    if value:
                        jar.set(name, value, domain=".google.com", path="/")

            jar.update(extra_cookies)
            cookie_jars_to_test.append((jar, "Base Cookies"))
            tried_sessions.setdefault(base_psid, set()).add(psidts)
        elif verbose:
            logger.debug("Skipping base cookies as they match cached cookies.")
    elif verbose and not cookie_jars_to_test:
        logger.debug("Skipping loading base cookies. __Secure-1PSID is not provided.")

    # Phase 3: Browser Cookies
    try:
        browser_cookies = load_browser_cookies(
            domain_name="google.com", verbose=verbose
        )
        if browser_cookies:
            for browser, cookie_list in browser_cookies.items():
                temp_cookies = {c["name"]: c["value"] for c in cookie_list}
                secure_1psid = temp_cookies.get("__Secure-1PSID")
                secure_1psidts = temp_cookies.get("__Secure-1PSIDTS", "")

                if secure_1psid:
                    if base_psid and base_psid != secure_1psid:
                        if verbose:
                            logger.debug(
                                f"Skipping loading local browser cookies from {browser}. "
                                "__Secure-1PSID does not match the one provided."
                            )
                        continue

                    if secure_1psidts not in tried_sessions.get(secure_1psid, set()):
                        jar = Cookies()
                        for cookie in cookie_list:
                            name = cookie["name"]
                            # Load only __Secure-1PSID and __Secure-1PSIDTS to prevent HTTP 401 errors when rotating cookies.
                            if name not in ["__Secure-1PSID", "__Secure-1PSIDTS"]:
                                continue

                            jar.set(
                                cookie["name"],
                                cookie["value"],
                                domain=cookie["domain"],
                                path=cookie["path"],
                            )

                        jar.update(extra_cookies)
                        cookie_jars_to_test.append((jar, f"Browser ({browser})"))
                        tried_sessions.setdefault(secure_1psid, set()).add(
                            secure_1psidts
                        )
                        if verbose:
                            logger.debug(
                                f"Prepared essential browser cookies from {browser}."
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
            response = await _send_request(client, jar, verbose=verbose)
            access_token = re.search(r'"SNlM0e":\s*"(.*?)"', response.text)
            build_label = re.search(r'"cfb2h":\s*"(.*?)"', response.text)
            session_id = re.search(r'"FdrFJe":\s*"(.*?)"', response.text)
            language = re.search(r'"TuX5cc":\s*"(.*?)"', response.text)
            push_id = re.search(r'"qKIAYe":\s*"(.*?)"', response.text)
            if access_token or build_label or session_id or language or push_id:
                if verbose:
                    logger.debug(
                        f"Init attempt ({current_attempt}) from {group_name} succeeded."
                    )
                return (
                    access_token.group(1) if access_token else None,
                    build_label.group(1) if build_label else None,
                    session_id.group(1) if session_id else None,
                    language.group(1) if language else None,
                    push_id.group(1) if push_id else None,
                    client,
                )
        except Exception:
            if verbose:
                logger.debug(
                    f"Init attempt ({current_attempt}) from {group_name} failed."
                )

    await client.close()
    raise AuthError(
        f"Failed to initialize client after {current_attempt} attempts. SECURE_1PSIDTS "
        "could get expired frequently, please make sure cookie values are up to date."
    )
