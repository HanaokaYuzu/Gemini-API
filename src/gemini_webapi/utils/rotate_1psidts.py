import contextlib
import hashlib
import os
import tempfile
import time
from pathlib import Path

import orjson as json
from curl_cffi.requests import AsyncSession, Cookies

from gemini_webapi.constants import (
    COOKIE_1PSID,
    COOKIE_1PSIDTS,
    COOKIE_CACHE_EXTENSION,
    COOKIE_CACHE_PREFIX,
    Endpoint,
    Headers,
    format_http_version,
)
from gemini_webapi.exceptions import AuthError

from .logger import logger


def extract_cookie_value(cookies: Cookies, name: str) -> str | None:
    """Extract a cookie value from a curl_cffi Cookies jar."""
    return next((cookie.value for cookie in cookies.jar if cookie.name == name), None)


def _hash_psid(psid: str) -> str:
    """Generate a stable 32-character hex hash prefix for a PSID."""
    return hashlib.sha256(psid.strip().encode("utf-8")).hexdigest()[:32]


def get_cookie_cache_dir() -> Path:
    """Lazy helper to get the cookie cache directory."""
    _path = os.getenv("GEMINI_COOKIE_PATH")
    return Path(_path) if _path else Path(tempfile.gettempdir()) / "gemini_webapi"


def migrate_legacy_cache(
    legacy_path: Path,
    target_psid: str,
    verbose: bool = False,
) -> Path | None:
    """Migrate a legacy unhashed cache file to the new hashed format."""
    cache_dir = legacy_path.parent
    hashed_path = (
        cache_dir / f"{COOKIE_CACHE_PREFIX}{_hash_psid(target_psid)}{COOKIE_CACHE_EXTENSION}"
    )
    try:
        content = legacy_path.read_text(encoding="utf-8")
        if not content.strip():
            with contextlib.suppress(OSError):
                legacy_path.unlink()
            if verbose:
                logger.debug(f"Removed empty legacy cookie cache: {legacy_path.name}")
            return None

        data = json.loads(content)
        if isinstance(data, list):
            cache_data = {
                "alias": target_psid,
                "cookies": data,
            }
        elif isinstance(data, dict) and "cookies" in data:
            cache_data = data
            if "alias" not in cache_data:
                cache_data["alias"] = target_psid
        else:
            with contextlib.suppress(OSError):
                legacy_path.unlink()
            if verbose:
                logger.warning(f"Removed corrupt legacy cookie cache: {legacy_path.name}")
            return None

        hashed_path.parent.mkdir(parents=True, exist_ok=True)
        hashed_path.write_bytes(json.dumps(cache_data))
        with contextlib.suppress(OSError):
            hashed_path.chmod(0o600)
        with contextlib.suppress(OSError):
            legacy_path.unlink()

        if verbose:
            logger.debug(f"Migrated legacy cookie cache: {legacy_path.name} -> {hashed_path.name}")
        return hashed_path
    except Exception as e:
        with contextlib.suppress(OSError):
            legacy_path.unlink()
        if verbose:
            logger.warning(f"Failed to migrate legacy cookie cache at {legacy_path}: {e}")
        return None


def get_cookies_cache_path(
    cookies: Cookies | None = None,
    base_psid: str | None = None,
    verbose: bool = False,
) -> Path | None:
    """Helper to get and ensure the cache file path based on hashed __Secure-1PSID.

    Checks first for the hashed cache file (`.cached_cookies_{hash}.json`).
    If a legacy unhashed file (`.cached_cookies_{psid}.json`) exists,
    transparently migrates it to the hashed format and cleans up the legacy file.
    """
    target_psid = base_psid or (extract_cookie_value(cookies, COOKIE_1PSID) if cookies else None)
    if not target_psid:
        if verbose:
            logger.debug("Cookie cache path not applicable: __Secure-1PSID not found.")
        return None

    cache_dir = get_cookie_cache_dir()
    hashed_path = (
        cache_dir / f"{COOKIE_CACHE_PREFIX}{_hash_psid(target_psid)}{COOKIE_CACHE_EXTENSION}"
    )
    legacy_path = cache_dir / f"{COOKIE_CACHE_PREFIX}{target_psid}{COOKIE_CACHE_EXTENSION}"

    if hashed_path.is_file():
        if legacy_path.is_file() and legacy_path != hashed_path:
            with contextlib.suppress(OSError):
                legacy_path.unlink()
            if verbose:
                logger.debug(f"Removed legacy cookie cache: {legacy_path.name}")
        return hashed_path

    if legacy_path.is_file():
        if migrated := migrate_legacy_cache(legacy_path, target_psid, verbose=verbose):
            return migrated
        return legacy_path

    return hashed_path


async def rotate_1psidts(
    client: AsyncSession,
    base_psid: str | None = None,
    verbose: bool = False,
) -> str | None:
    """Refresh the __Secure-1PSIDTS cookie and store the refreshed cookie value in cache file.

    Parameters
    ----------
    client : `curl_cffi.requests.AsyncSession`
        The shared async session to use for the request.
    base_psid : `str`, optional
        The original base __Secure-1PSID used to pin the cache file across rotations.
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
    path = get_cookies_cache_path(client.cookies, base_psid=base_psid, verbose=verbose)
    if not path:
        return None

    # Check if the cache file was modified in the last minute to avoid 429 Too Many Requests
    if path.is_file() and time.time() - path.stat().st_mtime <= 60:
        if verbose:
            logger.debug("Rotation skipped, cache is still fresh (< 60s).")
        return extract_cookie_value(client.cookies, COOKIE_1PSIDTS)

    response = await client.post(
        url=Endpoint.ROTATE_COOKIES,
        headers=Headers.ROTATE_COOKIES.value,
        data='[000,"-0000000000000000000"]',
    )
    if verbose:
        logger.debug(
            f"HTTP Request: POST {Endpoint.ROTATE_COOKIES} [{response.status_code}] (HTTP/{format_http_version(response.http_version)})"
        )
    if response.status_code == 401:
        clear_cookies_cache(client.cookies, base_psid=base_psid, verbose=verbose)
        raise AuthError
    response.raise_for_status()

    save_cookies(client.cookies, base_psid=base_psid, verbose=verbose)
    if new_1psidts := extract_cookie_value(client.cookies, COOKIE_1PSIDTS):
        return new_1psidts

    cookie_names = [c.name for c in client.cookies.jar]
    logger.debug(
        f"Rotation completed but __Secure-1PSIDTS not found. Response cookies: {cookie_names}"
    )
    return None


def clear_cookies_cache(
    cookies: Cookies | None = None,
    base_psid: str | None = None,
    verbose: bool = False,
) -> None:
    """Delete the cached cookies for a session.

    Parameters
    ----------
    cookies: `curl_cffi.requests.Cookies`, optional
        Cookies identifying the cache entry, by their `__Secure-1PSID`.
    base_psid: `str`, optional
        The base __Secure-1PSID used to pin the cache entry.
    verbose: `bool`, optional
        If `True`, will print more infomation in logs.

    """
    path = get_cookies_cache_path(cookies, base_psid=base_psid, verbose=verbose)
    if path and path.is_file():
        try:
            path.unlink()
            if verbose:
                logger.debug(f"Cleared cached cookies at {path}.")
        except OSError as e:
            if verbose:
                logger.warning(f"Failed to clear cached cookies at {path}: {e}")

    # If base_psid was specified and current rotated PSID differs, also clean up the alias file
    current_psid = extract_cookie_value(cookies, COOKIE_1PSID) if cookies else None
    if current_psid and base_psid and current_psid != base_psid:
        alias_path = (
            get_cookie_cache_dir()
            / f"{COOKIE_CACHE_PREFIX}{_hash_psid(current_psid)}{COOKIE_CACHE_EXTENSION}"
        )
        if alias_path.is_file() and alias_path != path:
            with contextlib.suppress(OSError):
                alias_path.unlink()
            if verbose:
                logger.debug(f"Cleared alias cached cookies at {alias_path}.")

    # Also clean up legacy unhashed file if it exists
    if target_psid := (base_psid or current_psid):
        legacy_path = (
            get_cookie_cache_dir() / f"{COOKIE_CACHE_PREFIX}{target_psid}{COOKIE_CACHE_EXTENSION}"
        )
        if legacy_path.is_file() and legacy_path != path:
            with contextlib.suppress(OSError):
                legacy_path.unlink()
            if verbose:
                logger.debug(f"Cleared legacy cached cookies at {legacy_path}.")


def save_cookies(
    cookies: Cookies,
    base_psid: str | None = None,
    verbose: bool = False,
) -> None:
    """Save persistent cookies to cache file with stable hash prefix and value alias."""
    current_psid = extract_cookie_value(cookies, COOKIE_1PSID)
    target_psid = base_psid or current_psid
    if not target_psid:
        if verbose:
            logger.debug("Skipping saving cookies: __Secure-1PSID not found.")
        return

    path = get_cookies_cache_path(cookies, base_psid=target_psid, verbose=verbose)
    if not path:
        return

    cookie_list = []
    for cookie in cookies.jar:
        is_auth_cookie = cookie.name in [COOKIE_1PSID, COOKIE_1PSIDTS]
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
        cache_data = {
            "alias": current_psid or target_psid,
            "cookies": cookie_list,
        }
        encoded = json.dumps(cache_data)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(encoded)
        with contextlib.suppress(OSError):
            path.chmod(0o600)  # Restrict cookie cache to owner read/write only

        # If current rotated PSID differs from base_psid, link or write the alias file
        if current_psid and base_psid and current_psid != base_psid:
            alias_path = (
                get_cookie_cache_dir()
                / f"{COOKIE_CACHE_PREFIX}{_hash_psid(current_psid)}{COOKIE_CACHE_EXTENSION}"
            )
            if alias_path != path:
                try:
                    if alias_path.is_file() or alias_path.is_symlink():
                        if not (
                            hasattr(os.path, "samefile") and os.path.samefile(alias_path, path)
                        ):
                            alias_path.unlink()
                            alias_path.hardlink_to(path)
                    else:
                        alias_path.hardlink_to(path)
                except (OSError, NotImplementedError):
                    alias_path.write_bytes(encoded)
                with contextlib.suppress(OSError):
                    alias_path.chmod(0o600)
                if verbose:
                    logger.debug(f"Saved alias cookies to cache: {alias_path.name}")

        if verbose:
            logger.debug(f"Saved cookies to cache successfully ({len(cookie_list)} cookies).")
