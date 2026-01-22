import asyncio
import functools
from collections.abc import Callable

from ..exceptions import APIError


def running(retry: int = 0) -> Callable:
    """
    Decorator to check if GeminiClient is running before making a request.

    Parameters
    ----------
    retry: `int`, optional
        Max number of retries when `gemini_webapi.APIError` is raised.
    """

    def decorator(func):
        @functools.wraps(func)
        async def wrapper(client, *args, current_retry=None, **kwargs):
            if current_retry is None:
                current_retry = retry

            try:
                if not client._running:
                    await client.init(
                        timeout=client.timeout,
                        auto_close=client.auto_close,
                        close_delay=client.close_delay,
                        auto_refresh=client.auto_refresh,
                        refresh_interval=client.refresh_interval,
                        verbose=client.verbose,
                    )
                    if client._running:
                        return await func(client, *args, **kwargs)

                    # Should not reach here
                    raise APIError(
                        f"Invalid function call: GeminiClient.{func.__name__}. Client initialization failed."
                    )
                else:
                    return await func(client, *args, **kwargs)
            except APIError:
                if current_retry > 0:
                    # Aggressive increasing delay: 5s, 10s, 15s...
                    # High quality image generation and heavy data analysis need more time.
                    delay = (retry - current_retry + 1) * 5
                    await asyncio.sleep(delay)

                    return await wrapper(
                        client, *args, current_retry=current_retry - 1, **kwargs
                    )

                raise

        return wrapper

    return decorator
