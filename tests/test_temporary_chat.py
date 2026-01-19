import os
import unittest
import logging

from gemini_webapi import GeminiClient, TemporaryChatNotSupported, set_log_level, logger
from gemini_webapi.constants import TEMPORARY_CHAT_FLAG_INDEX
from gemini_webapi.exceptions import AuthError

logging.getLogger("asyncio").setLevel(logging.ERROR)
set_log_level("DEBUG")


class TestTemporaryChat(unittest.IsolatedAsyncioTestCase):
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
    async def test_temporary_single_request(self):
        response = await self.geminiclient.generate_content(
            "Tell me a quick fun fact about today.",
            temporary=True,
        )
        self.assertTrue(response.text)
        logger.debug(response.text)

    async def test_temporary_request_flag(self):
        payload = await self.geminiclient._build_generate_payload(
            prompt="Hello",
            files=None,
            chat=None,
            gem_id=None,
            temporary=True,
        )
        # Server may still return metadata, but the request must be marked as temporary.
        self.assertGreaterEqual(len(payload), TEMPORARY_CHAT_FLAG_INDEX + 1)
        self.assertEqual(payload[TEMPORARY_CHAT_FLAG_INDEX], 1)

    @logger.catch(reraise=True)
    async def test_temporary_rejects_chat_multi_turn(self):
        chat = self.geminiclient.start_chat()

        with self.assertRaises(TemporaryChatNotSupported):
            await chat.send_message("Hello", temporary=True)


if __name__ == "__main__":
    unittest.main()
