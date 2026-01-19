import sys
import unittest
from pathlib import Path

# Ensure tests import local src instead of installed package.
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if SRC.is_dir():
    sys.path.insert(0, str(SRC))

from gemini_webapi import ChatSession, GeminiClient, TemporaryChatNotSupported
from gemini_webapi.constants import TEMPORARY_CHAT_FLAG_INDEX


class DummyAsyncClient:
    async def post(self, *args, **kwargs):
        raise AssertionError("post should not be called in these tests")


class TestTemporaryChat(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = GeminiClient()

    async def test_build_payload_default(self):
        payload = await self.client._build_generate_payload(
            prompt="Hello",
            files=None,
            chat=None,
            gem_id=None,
            temporary=False,
        )
        self.assertEqual(payload, [["Hello"], None, None])

    async def test_temporary_flag_injection(self):
        payload = await self.client._build_generate_payload(
            prompt="Hello",
            files=None,
            chat=None,
            gem_id=None,
            temporary=True,
        )
        self.assertGreaterEqual(len(payload), TEMPORARY_CHAT_FLAG_INDEX + 1)
        self.assertEqual(payload[TEMPORARY_CHAT_FLAG_INDEX], 1)

    async def test_generate_content_rejects_temporary_with_chat(self):
        self.client._running = True
        self.client.client = DummyAsyncClient()
        chat = ChatSession(geminiclient=self.client)

        with self.assertRaises(TemporaryChatNotSupported):
            await self.client.generate_content(
                "Hello",
                chat=chat,
                temporary=True,
            )

    async def test_chat_session_rejects_temporary(self):
        chat = ChatSession(geminiclient=self.client)

        with self.assertRaises(TemporaryChatNotSupported):
            await chat.send_message("Hello", temporary=True)

    async def test_default_payload_has_no_temporary_flag(self):
        payload = await self.client._build_generate_payload(
            prompt="Hello",
            files=None,
            chat=None,
            gem_id=None,
            temporary=False,
        )
        if len(payload) > TEMPORARY_CHAT_FLAG_INDEX:
            self.assertIsNone(payload[TEMPORARY_CHAT_FLAG_INDEX])


if __name__ == "__main__":
    unittest.main()
