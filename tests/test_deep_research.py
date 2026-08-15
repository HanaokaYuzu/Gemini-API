import logging
import os
import unittest

from gemini_webapi import GeminiClient, logger, set_log_level
from gemini_webapi.constants import AccountStatus
from gemini_webapi.exceptions import AuthError, GeminiError

logging.getLogger("asyncio").setLevel(logging.ERROR)
set_log_level("DEBUG")


class TestResearchMixin(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.geminiclient = GeminiClient(
            os.getenv("SECURE_1PSID"), os.getenv("SECURE_1PSIDTS"), verify=False
        )

        try:
            await self.geminiclient.init(auto_refresh=False, verbose=True)
        except AuthError as e:
            self.skipTest(e)

        if self.geminiclient.account_status != AccountStatus.AVAILABLE:
            # Initialization no longer fails without usable cookies - it falls back to a guest
            # session, which has no history, no uploads and no model choice, so every test here
            # would fail for the wrong reason
            self.skipTest(
                f"No usable account: {self.geminiclient.account_status.name} - "
                f"{self.geminiclient.account_status.description}"
            )

    async def asyncTearDown(self):
        await self.geminiclient.close()

    @logger.catch(reraise=True)
    async def test_create_research_plan(self):
        prompt = "What are the latest advancements in quantum computing research?"
        try:
            output = await self.geminiclient.create_deep_research_plan(prompt)
        except GeminiError as e:
            self.skipTest(e)

        logger.debug(f"Deep research plan: {output}")

    @logger.catch(reraise=True)
    async def test_full_research_flow(self):
        prompt = (
            "Compare the top 3 most popular language models providers and their exclusive features."
        )
        result = await self.geminiclient.deep_research(prompt)
        assert result.done, "research did not complete"
        logger.debug(f"Deep research result: {result.text}")
        if document := result.document:
            logger.debug(f"Report: {len(document.content)} chars, {len(document.sources)} sources")


if __name__ == "__main__":
    unittest.main()
