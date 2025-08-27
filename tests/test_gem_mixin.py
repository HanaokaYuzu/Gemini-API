import os
import random
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

        custom_gems = gems.filter(predefined=False)
        if custom_gems:
            logger.debug(f"Found {len(custom_gems)} custom gems:")
            for gem in custom_gems:
                logger.debug(gem)

    @logger.catch(reraise=True)
    async def test_create_gem(self):
        gem = await self.geminiclient.create_gem(
            name="Test Gem",
            prompt="Gemini API has launched creating gem functionality on Aug 1st, 2025",
            description="This gem is used for testing the functionality of Gemini API",
        )
        logger.debug(f"Gem created: {gem}")

    @logger.catch(reraise=True)
    async def test_update_gem(self):
        await self.geminiclient.fetch_gems()
        custom_gems = self.geminiclient.gems.filter(predefined=False)
        if not custom_gems:
            self.skipTest("No custom gems available to update.")

        last_created_gem = next(iter(custom_gems.values()))
        randint = random.randint(0, 100)
        updated_gem = await self.geminiclient.update_gem(
            last_created_gem.id,
            name="Updated Test Gem",
            prompt="Updated prompt for the gem.",
            description=f"{randint}",
        )
        logger.debug(f"Gem updated: {updated_gem}")

        await self.geminiclient.fetch_gems()
        custom_gems = self.geminiclient.gems.filter(predefined=False)
        last_created_gem = next(iter(custom_gems.values()))
        self.assertEqual(last_created_gem.description, updated_gem.description)

    @logger.catch(reraise=True)
    async def test_delete_gem(self):
        await self.geminiclient.fetch_gems()
        custom_gems = self.geminiclient.gems.filter(predefined=False)
        total_before_deletion = len(custom_gems)
        if total_before_deletion == 0:
            self.skipTest("No custom gems available to delete.")

        last_created_gem = next(iter(custom_gems.values()))
        await self.geminiclient.delete_gem(last_created_gem.id)
        logger.debug(f"Gem deleted: {last_created_gem}")

        await self.geminiclient.fetch_gems()
        custom_gems = self.geminiclient.gems.filter(predefined=False)
        total_after_deletion = len(custom_gems)
        self.assertEqual(total_after_deletion, total_before_deletion - 1)


if __name__ == "__main__":
    unittest.main()
