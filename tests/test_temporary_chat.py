import os
import unittest
import logging
from unittest.mock import patch

from gemini_webapi import GeminiClient, set_log_level, logger
from gemini_webapi.exceptions import AuthError
from gemini_webapi.types import Candidate, ModelOutput

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

    async def test_temporary_flag_is_forwarded_in_single_call(self):
        captured: dict[str, object] = {}

        async def fake_generate(_self, *args, **kwargs):
            captured["temporary"] = kwargs.get("temporary")
            captured["chat"] = kwargs.get("chat")
            yield ModelOutput(
                metadata=[],
                candidates=[Candidate(rcid="test-rcid", text="ok-single-call")],
            )

        with patch.object(GeminiClient, "_generate", new=fake_generate):
            response = await self.geminiclient.generate_content(
                "Forward temporary flag in single call.",
                temporary=True,
            )

        self.assertEqual(response.text, "ok-single-call")
        self.assertTrue(captured["temporary"])
        self.assertIsNone(captured["chat"])

    async def test_temporary_flag_is_forwarded_in_chat_call(self):
        captured: dict[str, object] = {}
        chat = self.geminiclient.start_chat()

        async def fake_generate(_self, *args, **kwargs):
            captured["temporary"] = kwargs.get("temporary")
            captured["chat"] = kwargs.get("chat")
            yield ModelOutput(
                metadata=[],
                candidates=[Candidate(rcid="test-rcid", text="ok-chat-call")],
            )

        with patch.object(GeminiClient, "_generate", new=fake_generate):
            response = await chat.send_message(
                "Forward temporary flag in chat call.",
                temporary=True,
            )

        self.assertEqual(response.text, "ok-chat-call")
        self.assertTrue(captured["temporary"])
        self.assertIs(captured["chat"], chat)

    @logger.catch(reraise=True)
    async def test_temporary_chat_multi_turn_toggle(self):
        chat = self.geminiclient.start_chat()
        await chat.send_message("Fine weather today", temporary=False)
        response = await chat.send_message("What's my last message?", temporary=True)
        self.assertTrue(response.text)


if __name__ == "__main__":
    unittest.main()
