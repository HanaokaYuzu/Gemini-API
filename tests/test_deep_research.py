import os
import unittest
import logging

from gemini_webapi import GeminiClient, set_log_level, logger
from gemini_webapi.exceptions import AuthError, GeminiError

logging.getLogger("asyncio").setLevel(logging.ERROR)
set_log_level("DEBUG")


class TestResearchMixin(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.geminiclient = GeminiClient(
            os.getenv("SECURE_1PSID"), os.getenv("SECURE_1PSIDTS"), verify=False
        )

        try:
            await self.geminiclient.init(auto_refresh=False)
        except AuthError as e:
            self.skipTest(e)

    async def asyncTearDown(self):
        await self.geminiclient.close()

    @logger.catch(reraise=True)
    async def test_feature_availability(self):
        snapshot = await self.geminiclient.inspect_account_status()
        logger.debug(f"Account status snapshot: {snapshot}")

        summary = snapshot.get("summary", {})
        self.assertTrue(summary["deep_research_feature_present"])

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
        prompt = "Compare the top 3 most popular language models providers and their exclusive features."
        result = await self.geminiclient.deep_research(prompt)
        logger.debug(f"Deep research statuses: {result.statuses}")
        logger.debug(f"Deep research result: {result.text}")


if __name__ == "__main__":
    unittest.main()
