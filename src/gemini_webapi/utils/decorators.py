import asyncio
import errno
import functools
import inspect
import re
from collections.abc import Callable, Coroutine
from typing import Any, TypeVar

from curl_cffi.curl import CurlError
from curl_cffi.requests.exceptions import (
    ConnectionError as CurlConnectionError,
)
from curl_cffi.requests.exceptions import (
    DNSError,
    HTTPError,
    ProxyError,
)
from curl_cffi.requests.exceptions import (
    Timeout as CurlTimeout,
)

from gemini_webapi.exceptions import APIError, ImageGenerationError

from .logger import logger

_DELAY_FACTOR = 5

T = TypeVar("T")

_TRANSIENT_CURL_CODES = {
    5,  # CURLE_COULDNT_RESOLVE_PROXY
    6,  # CURLE_COULDNT_RESOLVE_HOST
    7,  # CURLE_COULDNT_CONNECT
    16,  # CURLE_HTTP2
    18,  # CURLE_PARTIAL_FILE
    35,  # CURLE_SSL_CONNECT_ERROR
    52,  # CURLE_GOT_NOTHING
    55,  # CURLE_SEND_ERROR
    56,  # CURLE_RECV_ERROR
    92,  # CURLE_HTTP2_STREAM
}

_TRANSIENT_ERRNOS = {
    getattr(errno, name, None)
    for name in (
        "ECONNRESET",
        "ECONNREFUSED",
        "ETIMEDOUT",
        "ENETUNREACH",
        "EHOSTUNREACH",
        "EPIPE",
        "ENETDOWN",
        "ENETRESET",
        "ECONNABORTED",
    )
} - {None}
_TRANSIENT_ERRNOS.update(
    {
        10050,  # WSAENETDOWN
        10051,  # WSAENETUNREACH
        10052,  # WSAENETRESET
        10053,  # WSAECONNABORTED
        10054,  # WSAECONNRESET
        10058,  # WSAESHUTDOWN
        10060,  # WSAETIMEDOUT
        10061,  # WSAECONNREFUSED
        10064,  # WSAEHOSTDOWN
        10065,  # WSAEHOSTUNREACH
        11001,  # WSAHOST_NOT_FOUND
        11002,  # WSATRY_AGAIN
        11003,  # WSANO_RECOVERY
        11004,  # WSANO_DATA
        32,  # EPIPE (POSIX)
        101,  # ENETUNREACH (POSIX)
        104,  # ECONNRESET (POSIX)
        110,  # ETIMEDOUT (POSIX)
        111,  # ECONNREFUSED (POSIX)
        113,  # EHOSTUNREACH (POSIX)
    }
)


def _extract_status_code(exc: Exception) -> int | None:
    """Extract numeric HTTP status code from an exception or its associated response.

    Avoids fragile regex matching on error strings which can fail if strings are
    localized, reformatted, or changed across library versions.
    """
    code = getattr(exc, "status_code", None)
    if isinstance(code, int):
        return code

    resp = getattr(exc, "response", None)
    if resp is not None:
        resp_code = getattr(resp, "status_code", None)
        if isinstance(resp_code, int):
            return resp_code

    return None


def is_transient_network_error(exc: Exception) -> bool:
    """Check if an exception is a transient network or DNS issue safe to retry.

    Relies strictly on exception types, libcurl error codes, and OS socket errnos
    rather than searching error message text.
    """
    # HTTP errors (4xx, 5xx) subclass CurlError in curl_cffi; they are HTTP-level, not transient network errors.
    if isinstance(exc, HTTPError):
        return False
    # Timeouts are governed by the caller's timeout budget and handled separately.
    if isinstance(exc, (CurlTimeout, TimeoutError)):
        return False
    # Typed connection, DNS, and proxy exceptions
    if isinstance(exc, (DNSError, ProxyError, CurlConnectionError)):
        return True
    # Libcurl numeric error codes
    code = getattr(exc, "code", None)
    if isinstance(code, int) and code in _TRANSIENT_CURL_CODES:
        return True
    # Python built-in connection exception types
    if isinstance(exc, (ConnectionResetError, ConnectionRefusedError, ConnectionAbortedError)):
        return True
    # POSIX and Windows socket numeric error numbers
    if isinstance(exc, OSError):
        err = getattr(exc, "errno", None)
        win_err = getattr(exc, "winerror", None)
        if (isinstance(err, int) and err in _TRANSIENT_ERRNOS) or (
            isinstance(win_err, int) and win_err in _TRANSIENT_ERRNOS
        ):
            return True
    return False


def _is_running_retryable(exc: Exception) -> bool:
    """Determine if an exception caught by @running is transient and safe to retry."""
    # 1. Transient network, DNS, proxy, or socket drops (strictly typed & numeric checks)
    if is_transient_network_error(exc):
        return True

    # 2. Check structured numeric HTTP status code (typed check, immune to localized strings)
    status_code = _extract_status_code(exc)
    if status_code is not None:
        # Permanent 4xx HTTP client errors (400, 401, 403, 404, 429, etc.) must fail fast
        if 400 <= status_code < 500:
            return False
        # Server errors (5xx: 500, 502, 503, 504) are transient and retryable
        if 500 <= status_code < 600:
            return True

    # 3. HTTPError from curl_cffi where status_code was not on response
    if isinstance(exc, HTTPError):
        return False

    # 4. Inspect APIError
    if isinstance(exc, APIError):
        # Client contract/usage errors should fail fast
        if isinstance(exc, ImageGenerationError):
            return False
        msg = str(exc)
        if msg.startswith("Invalid "):
            return False
        # Fallback string pattern in case status_code was not attached by third-party caller
        return not bool(
            re.search(r"\b(?:status(?:\s*code)?|http)[\s:]*4\d\d\b", msg, re.IGNORECASE)
        )

    return False


def calculate_backoff(
    attempt: int,
    factor: float = 5.0,
    max_delay: float | None = 60.0,
) -> float:
    """Calculate backoff delay in seconds for a given retry attempt.

    Parameters
    ----------
    attempt: `int`
        The zero-based attempt index (0 for first retry, 1 for second, etc.).
    factor: `float`, optional
        Linear scaling factor for the delay, default 5.0.
    max_delay: `float | None`, optional
        Maximum delay cap in seconds. Defaults to 60.0.

    Returns
    -------
    `float`
        Backoff duration in seconds.
    """
    delay = (attempt + 1) * factor
    if max_delay is not None:
        delay = min(delay, max_delay)
    return delay


async def execute_with_retry(
    func: Callable[[], Coroutine[Any, Any, T]],
    max_retries: int = 3,
    factor: float = 1.5,
    max_delay: float | None = 30.0,
    is_transient: Callable[[Exception], bool] | None = None,
    on_retry: Callable[[Exception, int, float], Any] | None = None,
) -> T:
    """Execute an async operation with backoff retries for transient errors.

    Parameters
    ----------
    func: `Callable[[], Coroutine[Any, Any, T]]`
        Zero-argument async callable returning a coroutine to execute.
    max_retries: `int`, optional
        Maximum number of attempts (including initial try). Default 3.
    factor: `float`, optional
        Linear backoff factor for `calculate_backoff`. Default 1.5.
    max_delay: `float | None`, optional
        Max backoff delay cap in seconds. Default 30.0.
    is_transient: `Callable[[Exception], bool] | None`, optional
        Predicate returning True if the exception should trigger a retry.
    on_retry: `Callable[[Exception, int, float], Any] | None`, optional
        Callback invoked before sleeping: (exception, retry_attempt_1_based, backoff_seconds).

    Returns
    -------
    `T`
        The result of `await func()`.
    """
    for retry in range(max_retries):
        try:
            return await func()
        except Exception as e:
            if is_transient and is_transient(e) and retry < max_retries - 1:
                backoff = calculate_backoff(retry, factor=factor, max_delay=max_delay)
                if on_retry:
                    res = on_retry(e, retry + 1, backoff)
                    if inspect.isawaitable(res):
                        await res
                await asyncio.sleep(backoff)
                continue
            raise
    raise RuntimeError("execute_with_retry reached unreachable state")


async def _init_client(client: Any) -> None:
    """Initialize client if not running, dynamically binding matching attributes without hardcoded fallbacks."""
    if getattr(client, "_running", False):
        return

    init_func = getattr(client, "init", None)
    if not callable(init_func):
        return

    kwargs: dict[str, Any] = {}
    try:
        sig = inspect.signature(init_func)
        accepts_var_keyword = any(
            param.kind == inspect.Parameter.VAR_KEYWORD for param in sig.parameters.values()
        )
        for name, param in sig.parameters.items():
            if param.kind in (
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                inspect.Parameter.KEYWORD_ONLY,
            ) and hasattr(client, name):
                val = getattr(client, name)
                if val is not None:
                    kwargs[name] = val

        if accepts_var_keyword:
            for attr in (
                "timeout",
                "auto_close",
                "close_delay",
                "auto_refresh",
                "refresh_interval",
                "watchdog_timeout",
                "impersonate",
                "verbose",
            ):
                if attr not in kwargs and hasattr(client, attr):
                    val = getattr(client, attr)
                    if val is not None:
                        kwargs[attr] = val
    except (TypeError, ValueError):
        pass

    await client.init(**kwargs)


def running(retry: int = 0) -> Callable:
    """Decorator to check if GeminiClient is running before making a request.
    Supports both regular async functions and async generators.

    Parameters
    ----------
    retry: `int`, optional
        Max number of retries when transient network or API errors occur.

    """

    def decorator(func):
        if inspect.isasyncgenfunction(func):

            @functools.wraps(func)
            async def asyncgen_wrapper(client, *args, **kwargs):
                for attempt in range(retry + 1):
                    has_yielded = False
                    try:
                        await _init_client(client)

                        if not client._running:
                            raise APIError(
                                f"Invalid function call: GeminiClient.{func.__name__}. Client initialization failed."
                            )

                        async for item in func(client, *args, **kwargs):
                            has_yielded = True
                            yield item
                        return
                    except (APIError, CurlConnectionError, CurlError, OSError) as exc:
                        if not has_yielded and attempt < retry and _is_running_retryable(exc):
                            if client._running:
                                await client.close()
                            delay = calculate_backoff(attempt, factor=_DELAY_FACTOR)
                            if getattr(client, "verbose", False):
                                logger.warning(
                                    f"GeminiClient.{func.__name__} failed with {type(exc).__name__}: {exc}. "
                                    f"Retrying in {delay:.1f}s ({attempt + 1}/{retry})..."
                                )
                            await asyncio.sleep(delay)
                            continue

                        await client.close()
                        raise

            return asyncgen_wrapper

        @functools.wraps(func)
        async def async_wrapper(client, *args, **kwargs):
            for attempt in range(retry + 1):
                try:
                    await _init_client(client)

                    if not client._running:
                        raise APIError(
                            f"Invalid function call: GeminiClient.{func.__name__}. Client initialization failed."
                        )

                    return await func(client, *args, **kwargs)
                except (APIError, CurlConnectionError, CurlError, OSError) as exc:
                    if attempt < retry and _is_running_retryable(exc):
                        if client._running:
                            await client.close()
                        delay = calculate_backoff(attempt, factor=_DELAY_FACTOR)
                        if getattr(client, "verbose", False):
                            logger.warning(
                                f"GeminiClient.{func.__name__} failed with {type(exc).__name__}: {exc}. "
                                f"Retrying in {delay:.1f}s ({attempt + 1}/{retry})..."
                            )
                        await asyncio.sleep(delay)
                        continue

                    await client.close()
                    raise

            raise RuntimeError(f"GeminiClient.{func.__name__} retry loop terminated unexpectedly.")

        return async_wrapper

    return decorator
