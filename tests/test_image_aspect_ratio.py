# ruff: noqa: PT009, PT027
"""Offline checks for image selection without credentials or generation requests."""

import json
import unittest
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from gemini_webapi import GeminiClient
from gemini_webapi.types import AvailableModel


class RequestCaptured(BaseException):
    pass


class TestImageAspectRatio(unittest.IsolatedAsyncioTestCase):
    async def capture(self, *, aspect_ratio=None, session=False, streaming=False):
        client = GeminiClient()
        client._running = True
        client.auto_close = False
        captured = {}

        @asynccontextmanager
        async def stream(method, url, **kwargs):
            captured.update(kwargs)
            captured["body"] = json.loads(json.loads(kwargs["data"]["f.req"])[1])
            raise RequestCaptured
            yield  # pragma: no cover

        client.client = SimpleNamespace(stream=stream)
        model = AvailableModel(
            model_id="test",
            model_name="test",
            display_name="test",
            description="",
            capacity=1,
            model_number=17,
        )
        target = client.start_chat(model=model) if session else client
        name = ("send_message" if session else "generate_content") + (
            "_stream" if streaming else ""
        )
        kwargs = {"aspect_ratio": aspect_ratio}
        if not session:
            kwargs["model"] = model
        with (
            patch.object(GeminiClient, "_sync_activity", new=AsyncMock()),
            patch.object(GeminiClient, "_check_account_status", return_value=True),
            self.assertRaises(RequestCaptured),
        ):
            result = getattr(target, name)("Draw a cat", **kwargs)
            if streaming:
                async for _ in result:
                    pass
            else:
                await result
        return captured

    async def test_ratio_across_public_entry_points(self):
        for session in (False, True):
            for streaming in (False, True):
                with self.subTest(session=session, streaming=streaming):
                    request = await self.capture(
                        aspect_ratio="16:9", session=session, streaming=streaming
                    )
                    body = request["body"]
                    self.assertEqual(body[0][9][6][1], [None, "16:9"])
                    self.assertEqual((body[32], body[49], body[72]), (None, 14, None))
                    self.assertEqual(body[79], 17)
                    self.assertEqual(body[0][0], "Draw a cat")
                    self.assertNotIn("aspect_ratio", request)
                    self.assertFalse(
                        any(
                            isinstance(v, str) and v.startswith(("c_", "r_", "rc_"))
                            for v in body[2]
                        )
                    )

    async def test_default_keeps_existing_request_shape(self):
        request = await self.capture()
        body = request["body"]
        self.assertEqual(len(body[0]), 7)
        self.assertEqual((body[32], body[49], body[72]), (None, None, None))
        self.assertEqual(body[79], 17)

    async def test_rejects_conflicting_tools(self):
        client = GeminiClient()
        for streaming in (False, True):
            with self.subTest(streaming=streaming), self.assertRaises(ValueError):
                if streaming:
                    async for _ in client.generate_content_stream(
                        "cat", aspect_ratio="16:9", deep_research=True
                    ):
                        pass
                else:
                    await client.generate_content("cat", aspect_ratio="16:9", deep_research=True)

    async def test_all_supported_ratios(self):
        for ratio in ("1:1", "9:16", "16:9", "3:4", "4:3", "2:3", "21:9", "1:8", "8:1"):
            with self.subTest(ratio=ratio):
                request = await self.capture(aspect_ratio=ratio)
                self.assertEqual(request["body"][0][9][6][1], [None, ratio])

    async def test_invalid_ratio_before_network(self):
        client = GeminiClient()
        for ratio in (
            "",
            "auto",
            "7:13",
            "2:1",
            "3:2",
            "4:5",
            "5:4",
            "1:4",
            "4:1",
            "16/9",
            "16:9 ",
        ):
            for streaming in (False, True):
                with self.subTest(ratio=ratio, streaming=streaming), self.assertRaises(ValueError):
                    if streaming:
                        async for _ in client.generate_content_stream("cat", aspect_ratio=ratio):
                            pass
                    else:
                        await client.generate_content("cat", aspect_ratio=ratio)
