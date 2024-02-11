def running(func):
    """
    Decorator to check if client is running before making a request.
    """

    async def wrapper(self, *args, **kwargs):
        if not self.running:
            raise Exception(
                f"Invalid function call: GeminiClient.{func.__name__}. Client is not running. Re-initiate client to try again."
            )
        return await func(self, *args, **kwargs)

    return wrapper
