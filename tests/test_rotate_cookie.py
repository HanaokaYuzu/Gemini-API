import os
import asyncio

from loguru import logger

from gemini_webapi import GeminiClient, set_log_level

set_log_level("DEBUG")


@logger.catch()
async def main():
    client = GeminiClient(os.getenv("SECURE_1PSID"), os.getenv("SECURE_1PSIDTS"))
    await client.init(close_delay=30, refresh_interval=60)

    while True:
        try:
            response = await client.generate_content("Hello world")
            logger.info(response)
        except Exception as e:
            logger.error(e)
        await asyncio.sleep(60)


if __name__ == "__main__":
    asyncio.run(main())
