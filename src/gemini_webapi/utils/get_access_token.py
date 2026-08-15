import re
import time
from pathlib import Path
from typing import NamedTuple

import orjson as json
from curl_cffi import CurlFollow, CurlHttpVersion
from curl_cffi.requests import AsyncSession, BrowserTypeLiteral, Cookies, Response

from gemini_webapi.constants import BROWSER_TYPE, Endpoint, Headers, format_http_version
from gemini_webapi.exceptions import AuthError

from .load_browser_cookies import HAS_BC3, load_browser_cookies
from .logger import logger
from .rotate_1psidts import (
    _extract_cookie_value,
    _get_cookie_cache_dir,
    _get_cookies_cache_path,
)


class InitSession(NamedTuple):
    """Everything a successful init attempt produced.

    Attributes
    ----------
    access_token: `str | None`
        The "SNlM0e" value. Guest sessions have none.
    build_label: `str | None`
        Frontend build label sent back as the `bl` request parameter.
    session_id: `str | None`
        Frontend session id sent back as the `f.sid` request parameter.
    language: `str | None`
        Account language.
    push_id: `str | None`
        File upload push id.
    client: `curl_cffi.requests.AsyncSession`
        The **live** session that succeeded, so the caller can reuse its TLS connection.
    cookie_source: `str`
        Name of the cookie group that produced this session - "Cache", "Base Cookies",
        "Browser (firefox)", "Guest". A session is accepted as soon as it yields an access
        token, which an unauthenticated one does too, so the caller needs to know which
        group to blame when the session turns out to be unusable.

    """

    access_token: str | None
    build_label: str | None
    session_id: str | None
    language: str | None
    push_id: str | None
    client: AsyncSession
    cookie_source: str


_DOMAIN_NAME = "google.com"
_COOKIE_DOMAIN = f".{_DOMAIN_NAME}"
_COOKIE_PATH = "/"

_ACCESS_TOKEN_RE = re.compile(r'"SNlM0e":\s*"(.*?)"')
_BUILD_LABEL_RE = re.compile(r'"cfb2h":\s*"(.*?)"')
_SESSION_ID_RE = re.compile(r'"FdrFJe":\s*"(.*?)"')
_LANGUAGE_RE = re.compile(r'"TuX5cc":\s*"(.*?)"')
_PUSH_ID_RE = re.compile(r'"qKIAYe":\s*"(.*?)"')


def _jar_signature(jar: Cookies) -> frozenset[tuple[str, str]]:
    """Build a hashable identity of a cookie jar to avoid sending duplicated requests."""
    return frozenset((str(c.name), str(c.value)) for c in jar.jar)


def _to_jar(base_cookies: dict | Cookies) -> Cookies:
    """Normalize user provided cookies into a `Cookies` jar, dropping expired/empty ones."""
    jar = Cookies()
    if isinstance(base_cookies, Cookies):
        for cookie in base_cookies.jar:
            if cookie.value and not cookie.is_expired():
                jar.set(
                    str(cookie.name),
                    str(cookie.value),
                    domain=cookie.domain,
                    path=cookie.path,
                    secure=cookie.secure,
                )
    else:
        for name, value in base_cookies.items():
            if value:
                jar.set(
                    name,
                    value,
                    domain=_COOKIE_DOMAIN,
                    path=_COOKIE_PATH,
                    secure=True,
                )

    return jar


def _load_cached_jar(
    cache_file: Path, jar: Cookies | None = None, verbose: bool = False
) -> Cookies | None:
    """Load non-expired cookies from a cache file, layered on top of `jar` if provided.

    Returns `None` if the cache file is unusable, so the caller can fall back to other sources.
    """
    try:
        content = cache_file.read_text().strip()
    except OSError as e:
        logger.warning(f"Failed to read cached cookies: {e}")
        return None

    if not content:
        if verbose:
            logger.debug("Skipping loading cached cookies. Cache file is empty.")
        return None

    try:
        cookies_data = json.loads(content)
    except Exception as e:
        logger.warning(f"Failed to parse cached cookies as JSON: {e}")
        return None

    if not isinstance(cookies_data, list):
        logger.warning("Failed to load cached cookies: unexpected cache file format.")
        return None

    result = Cookies(jar) if jar is not None else Cookies()
    for cookie in cookies_data:
        name, value = cookie.get("name"), cookie.get("value")
        if not name or not value:
            continue

        expires = cookie.get("expires")
        if expires and expires < time.time():
            continue

        result.set(
            name,
            value,
            domain=cookie.get("domain", _COOKIE_DOMAIN),
            path=cookie.get("path", _COOKIE_PATH),
            secure=True,
        )

    return result


def _fill_missing(jar: Cookies, extra: Cookies) -> Cookies:
    """Complete `jar` with cookies from `extra` that it doesn't already carry.

    Values already present in `jar` always win, so cached or user provided cookies
    never get overwritten by freshly issued anonymous ones.
    """
    merged = Cookies(jar)
    known = {str(c.name) for c in jar.jar}
    for cookie in extra.jar:
        if str(cookie.name) not in known:
            merged.set(
                str(cookie.name),
                str(cookie.value),
                domain=cookie.domain,
                path=cookie.path,
                secure=cookie.secure,
            )

    return merged


async def _send_request(
    client: AsyncSession, cookies: dict | Cookies, verbose: bool = False
) -> Response:
    """Send http request with provided cookies using a shared session."""
    client.cookies.clear()
    if isinstance(cookies, Cookies):
        client.cookies.update(cookies)
    else:
        for k, v in cookies.items():
            client.cookies.set(k, v, domain=_COOKIE_DOMAIN, secure=True)

    response = await client.get(Endpoint.INIT, headers=Headers.GEMINI.value)
    if verbose:
        logger.debug(
            f"HTTP Request: GET {Endpoint.INIT} [{response.status_code}] (HTTP/{format_http_version(response.http_version)})"
        )
    response.raise_for_status()
    return response


def _extract_payload(
    response: Response,
) -> tuple[str | None, str | None, str | None, str | None, str | None] | None:
    """Extract init values from an init response, or `None` if the page carries none of them."""
    access_token = _ACCESS_TOKEN_RE.search(response.text)
    build_label = _BUILD_LABEL_RE.search(response.text)
    session_id = _SESSION_ID_RE.search(response.text)
    language = _LANGUAGE_RE.search(response.text)
    push_id = _PUSH_ID_RE.search(response.text)
    if not (access_token or build_label or session_id or language or push_id):
        return None

    return (
        access_token.group(1) if access_token else None,
        build_label.group(1) if build_label else None,
        session_id.group(1) if session_id else None,
        language.group(1) if language else None,
        push_id.group(1) if push_id else None,
    )


async def get_access_token(
    base_cookies: dict | Cookies,
    proxy: str | None = None,
    verbose: bool = False,
    impersonate: BrowserTypeLiteral = BROWSER_TYPE,
    verify: bool = True,
) -> InitSession:
    """Send a get request to gemini.google.com for each group of available cookies and return
    the value of "SNlM0e" as access token on the first successful request.

    Cookie groups are tried offline first, in order of freshness: cached cookies, then user
    provided cookies, then local browser cookies. Only if all of them fail does the client
    fall back to a preflight request against google.com to pick up consent/anonymous cookies,
    which are then used to complete the previous groups (without ever overwriting their
    values) and, as a last resort, to attempt a guest session.

    Returns the **live** AsyncSession that succeeded so the caller can reuse the same TLS
    connection for subsequent requests, along with the name of the cookie group it came
    from.

    Parameters
    ----------
    base_cookies: `dict | curl_cffi.requests.Cookies`
        Initial cookies to try. Can be a dictionary or a Cookies object.
    proxy: `str`, optional
        Proxy URL.
    verbose: `bool`, optional
        If True, log more details.
    impersonate: `BrowserTypeLiteral`, optional
        Allow to customize client, default to BROWSER_TYPE.
    verify: `bool`, optional
        Whether to verify SSL certificates.

    Returns
    -------
    :class:`InitSession`
        Named tuple of the access token, build label, session id, language, file push id,
        the live `AsyncSession`, and the name of the cookie group that produced it.

    Raises
    ------
    `gemini_webapi.AuthError`
        If all requests failed.

    """
    client = AsyncSession(
        impersonate=impersonate,
        proxy=proxy,
        allow_redirects=CurlFollow.SAFE,
        http_version=CurlHttpVersion.NONE,
        verify=verify,
    )

    try:
        # Phase 1: Collect candidate cookie groups offline, no network access involved
        cookie_jars_to_test: list[tuple[Cookies, str]] = []
        tried_sessions: dict[str, set[str]] = {}

        base_jar = _to_jar(base_cookies)
        base_psid = _extract_cookie_value(base_jar, "__Secure-1PSID")
        base_psidts = _extract_cookie_value(base_jar, "__Secure-1PSIDTS")

        def register(jar: Cookies, group_name: str, psid: str | None) -> None:
            cookie_jars_to_test.append((jar, group_name))
            if psid:
                psidts = _extract_cookie_value(jar, "__Secure-1PSIDTS") or ""
                tried_sessions.setdefault(psid, set()).add(psidts)

        # Cached cookies come first: they hold the most recently rotated __Secure-1PSIDTS
        if base_psid:
            probe = Cookies()
            probe.set("__Secure-1PSID", base_psid, domain=_COOKIE_DOMAIN, secure=True)
            cache_file = _get_cookies_cache_path(probe)

            if cache_file and cache_file.is_file():
                if (jar := _load_cached_jar(cache_file, base_jar, verbose)) is not None:
                    register(jar, "Cache", base_psid)
            elif verbose:
                logger.debug("Skipping loading cached cookies. Cache file not found.")
        elif cache_files := list(_get_cookie_cache_dir().glob(".cached_cookies_*.json")):
            cache_file = max(cache_files, key=lambda p: p.stat().st_mtime)
            if (jar := _load_cached_jar(cache_file, verbose=verbose)) is not None:
                register(jar, "Cache (Latest)", cache_file.stem[16:])

        # User provided cookies, skipped if the cache already covers the same session
        if base_psid:
            if (base_psidts or "") not in tried_sessions.get(base_psid, set()):
                register(Cookies(base_jar), "Base Cookies", base_psid)
            elif verbose:
                logger.debug("Skipping base cookies as they match cached cookies.")
        elif verbose and not cookie_jars_to_test:
            logger.debug("Skipping loading base cookies. __Secure-1PSID is not provided.")

        # Local browser cookies as the last authenticated source
        try:
            if browser_cookies := load_browser_cookies(domain_name=_DOMAIN_NAME, verbose=verbose):
                for browser, cookie_list in browser_cookies.items():
                    temp_cookies = {c["name"]: c["value"] for c in cookie_list}
                    secure_1psid = temp_cookies.get("__Secure-1PSID")
                    secure_1psidts = temp_cookies.get("__Secure-1PSIDTS", "")

                    if not secure_1psid:
                        continue

                    if base_psid and base_psid != secure_1psid:
                        if verbose:
                            logger.debug(
                                f"Skipping loading local browser cookies from {browser}. "
                                "__Secure-1PSID does not match the one provided."
                            )
                        continue

                    if secure_1psidts in tried_sessions.get(secure_1psid, set()):
                        continue

                    jar = Cookies()
                    for cookie in cookie_list:
                        # Load only __Secure-1PSID and __Secure-1PSIDTS to prevent HTTP 401 errors when rotating cookies.
                        if cookie["name"] not in [
                            "__Secure-1PSID",
                            "__Secure-1PSIDTS",
                        ]:
                            continue

                        jar.set(
                            cookie["name"],
                            cookie["value"],
                            domain=cookie["domain"],
                            path=cookie["path"],
                            secure=True,
                        )

                    register(jar, f"Browser ({browser})", secure_1psid)
                    if verbose:
                        logger.debug(f"Prepared essential browser cookies from {browser}.")

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

        # Phase 2: Try every candidate group as-is, without contacting google.com first
        attempts = 0
        tried_jars: set[frozenset[tuple[str, str]]] = set()

        async def try_jars(jars: list[tuple[Cookies, str]]):
            nonlocal attempts
            for jar, group_name in jars:
                signature = _jar_signature(jar)
                if not signature or signature in tried_jars:
                    continue
                tried_jars.add(signature)

                attempts += 1
                try:
                    response = await _send_request(client, jar, verbose=verbose)
                    if payload := _extract_payload(response):
                        if verbose:
                            logger.debug(f"Init attempt ({attempts}) from {group_name} succeeded.")
                        return payload, group_name
                    if verbose:
                        logger.debug(
                            f"Init attempt ({attempts}) from {group_name} returned no init values."
                        )
                except Exception:
                    if verbose:
                        logger.debug(f"Init attempt ({attempts}) from {group_name} failed.")

            return None

        if result := await try_jars(cookie_jars_to_test):
            payload, group_name = result
            return InitSession(*payload, client=client, cookie_source=group_name)

        # Phase 3: Fall back to a preflight request for consent/anonymous cookies, then
        # retry the same groups completed with the missing cookies, and finally guest mode
        try:
            # Start from a clean jar, otherwise cookies left over from the failed
            # attempts above would leak into the preflight and guest sessions
            client.cookies.clear()
            response = await client.get(Endpoint.GOOGLE)
            if verbose:
                logger.debug(
                    f"HTTP Request: GET {Endpoint.GOOGLE} [{response.status_code}] (HTTP/{format_http_version(response.http_version)})"
                )
            preflight_cookies = (
                Cookies(client.cookies) if response.status_code == 200 else Cookies()
            )
        except Exception:
            if not cookie_jars_to_test:
                # Nothing else to fall back on, surface the underlying network error
                raise

            logger.warning("Preflight request to google.com failed.")
            preflight_cookies = Cookies()

        if _jar_signature(preflight_cookies):
            retries = [
                (_fill_missing(jar, preflight_cookies), f"{group_name} + Preflight")
                for jar, group_name in cookie_jars_to_test
            ]
            retries.append((Cookies(preflight_cookies), "Guest"))
            if result := await try_jars(retries):
                payload, group_name = result
                return InitSession(*payload, client=client, cookie_source=group_name)

        raise AuthError(
            f"Failed to initialize client after {attempts} attempts. SECURE_1PSIDTS "
            "could get expired frequently, please make sure cookie values are up to date."
        )
    except BaseException:
        await client.close()
        raise
