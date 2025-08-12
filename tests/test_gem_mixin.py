import os
import unittest
import logging

from gemini_webapi import GeminiClient, set_log_level, logger
from gemini_webapi.exceptions import AuthError

logging.getLogger("asyncio").setLevel(logging.ERROR)
set_log_level("DEBUG")


class TestGemMixin(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.geminiclient = GeminiClient(
            os.getenv("SECURE_1PSID"), os.getenv("SECURE_1PSIDTS"), verify=False
        )

        try:
            await self.geminiclient.init(timeout=60, auto_refresh=False)
        except AuthError as e:
            self.skipTest(e)

    @logger.catch(reraise=True)
    async def test_fetch_gems(self):
        await self.geminiclient.fetch_gems(include_hidden=True)
        gems = self.geminiclient.gems
        self.assertTrue(len(gems.filter(predefined=True)) > 0)
        for gem in gems:
            logger.debug(gem.name)


if __name__ == "__main__":
    unittest.main()
