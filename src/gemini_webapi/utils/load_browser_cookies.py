from concurrent.futures import ThreadPoolExecutor, as_completed
from http.cookiejar import CookieJar

from .logger import logger

try:
    import browser_cookie3 as bc3

    HAS_BC3 = True
except ImportError:
    bc3 = None
    HAS_BC3 = False


def load_browser_cookies(domain_name: str = "", verbose: bool = False) -> dict:
    """
    Try to load cookies from all supported browsers and return combined cookiejar.
    Optionally pass in a domain name to only load cookies from the specified domain.

    Parameters
    ----------
    domain_name : str, optional
        Domain name to filter cookies by, by default will load all cookies without filtering.
    verbose : bool, optional
        If `True`, will print more infomation in logs.

    Returns
    -------
    `dict[str, list[dict]]`
        Dictionary with browser as keys and their cookies for the specified domain as values.
        Each cookie is a dictionary: `{"name": str, "value": str, "domain": str, "path": str, "expires": int}`.
        Only browsers that have cookies for the specified domain will be included.
    """

    if not HAS_BC3 or bc3 is None:
        if verbose:
            logger.debug(
                "Optional dependency 'browser-cookie3' not found. Skipping browser cookie loading."
            )
        return {}

    browser_fns = [
        bc3.chrome,
        bc3.chromium,
        bc3.opera,
        bc3.opera_gx,
        bc3.brave,
        bc3.edge,
        bc3.vivaldi,
        bc3.firefox,
        bc3.librewolf,
        bc3.safari,
    ]

    cookies = {}

    def fetch_cookies(cookie_fn):
        try:
            jar: CookieJar = cookie_fn(domain_name=domain_name)
            if jar:
                cookie_list = []
                for cookie in jar:
                    if not cookie.is_expired():
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
                    return cookie_fn.__name__, cookie_list
        except bc3.BrowserCookieError:
            pass
        except PermissionError:
            if verbose:
                logger.warning(
                    f"Permission denied while trying to load cookies from {cookie_fn.__name__}."
                )
        except Exception:
            if verbose:
                logger.debug(
                    f"Failed to load cookies from {cookie_fn.__name__} (may not be installed)."
                )
        return None

    with ThreadPoolExecutor(max_workers=len(browser_fns)) as executor:
        futures = [executor.submit(fetch_cookies, fn) for fn in browser_fns]
        for future in as_completed(futures):
            result = future.result()
            if result:
                browser_name, cookie_dict = result
                cookies[browser_name] = cookie_dict

    return cookies
