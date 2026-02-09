import asyncio
import functools
import inspect
from collections.abc import Callable

from ..exceptions import APIError


DELAY_FACTOR = 5


def running(retry: int = 0) -> Callable:
    """
    Decorator to check if GeminiClient is running before making a request.
    Supports both regular async functions and async generators.

    Parameters
    ----------
    retry: `int`, optional
        Max number of retries when `gemini_webapi.APIError` is raised.
    """

    def decorator(func):
        if inspect.isasyncgenfunction(func):

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
                            watchdog_timeout=client.watchdog_timeout,
                        )

                    if not client._running:
                        raise APIError(
                            f"Invalid function call: GeminiClient.{func.__name__}. Client initialization failed."
                        )

                    async for item in func(client, *args, **kwargs):
                        yield item
                except APIError:
                    if current_retry > 0:
                        delay = (retry - current_retry + 1) * DELAY_FACTOR
                        await asyncio.sleep(delay)
                        async for item in wrapper(
                            client, *args, current_retry=current_retry - 1, **kwargs
                        ):
                            yield item
                    else:
                        raise

            return wrapper
        else:

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
                            watchdog_timeout=client.watchdog_timeout,
                        )

                    if not client._running:
                        raise APIError(
                            f"Invalid function call: GeminiClient.{func.__name__}. Client initialization failed."
                        )

                    return await func(client, *args, **kwargs)
                except APIError:
                    if current_retry > 0:
                        delay = (retry - current_retry + 1) * DELAY_FACTOR
                        await asyncio.sleep(delay)

                        return await wrapper(
                            client, *args, current_retry=current_retry - 1, **kwargs
                        )

                    raise

            return wrapper

    return decorator
