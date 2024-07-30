from .logger import logger


def load_browser_cookies(domain_name: str = "", verbose=True) -> dict:
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
    `dict`
        Dictionary with cookie name as key and cookie value as value.
    """

    import browser_cookie3 as bc3

    cookies = {}
    for cookie_fn in [
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
    ]:
        try:
            for cookie in cookie_fn(domain_name=domain_name):
                cookies[cookie.name] = cookie.value
        except bc3.BrowserCookieError:
            pass
        except PermissionError as e:
            if verbose:
                logger.warning(
                    f"Permission denied while trying to load cookies from {cookie_fn.__name__}. {e}"
                )
        except Exception as e:
            if verbose:
                logger.error(
                    f"Error happened while trying to load cookies from {cookie_fn.__name__}. {e}"
                )

    return cookies
