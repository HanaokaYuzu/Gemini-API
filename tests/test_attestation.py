"""Offline checks of the attestation boundary and serialized generation requests."""

# Keep the existing unittest runner; pytest is not a project dependency.
# ruff: noqa: PT009, PT027

import asyncio
import unittest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, Mock, patch

import orjson as json

from gemini_webapi import Attestation, AttestationError, AttestationRequest, GeminiClient
from gemini_webapi.attestation import get_attestation
from gemini_webapi.exceptions import APIError, GeminiError


class RequestCapturedError(GeminiError):
    pass


class TestAttestation(unittest.IsolatedAsyncioTestCase):
    def make_client(self, provider=None, retry_once=False):
        client = GeminiClient(attestation_provider=provider)
        client._running = True
        captured = []

        @asynccontextmanager
        async def stream(*args, **kwargs):
            captured.append(json.loads(json.loads(kwargs["data"]["f.req"])[1]))
            if retry_once and len(captured) == 1:
                raise APIError("Retryable transport failure")
            raise RequestCapturedError
            yield  # pragma: no cover

        client.client = Mock(stream=stream)
        return client, captured

    async def generate(self, client, **kwargs):
        async for _ in client._generate(" exact prompt\nwith Unicode: 雨 ", **kwargs):
            pass

    async def test_exact_prompt_and_parent_ids_are_serialized(self):
        result = Attestation("!opaque-proof", "a" * 32)
        provider = AsyncMock(return_value=result)
        client, captured = self.make_client(provider)
        chat = client.start_chat(cid="c_parent", rid="r_parent", rcid="rc_parent")
        with self.assertRaises(RequestCapturedError):
            await self.generate(client, chat=chat)
        body = captured[0]
        provider.assert_awaited_once_with(AttestationRequest(body[0][0], *body[2][:3]))
        self.assertEqual(body[2][:3], ["c_parent", "r_parent", "rc_parent"])
        self.assertEqual(body[3:5], [result.proof, result.nonce])
        self.assertNotIn("attestation_provider", client.kwargs)

    async def test_metadata_changes_during_attestation_do_not_change_sent_ids(self):
        requests = []

        async def provider(request):
            requests.append(request)
            await asyncio.sleep(0)
            chat.metadata = ["c_changed", "r_changed", "rc_changed"]
            return Attestation("!bound-to-original-ids", "a" * 32)

        client, captured = self.make_client(provider)
        original_ids = ["c_parent", "r_parent", "rc_parent"]
        chat = client.start_chat(metadata=original_ids)
        with self.assertRaises(RequestCapturedError):
            await self.generate(client, chat=chat)
        self.assertEqual(captured[0][2][:3], original_ids)
        self.assertEqual(requests, [AttestationRequest(captured[0][0][0], *original_ids)])

    async def test_retry_gets_fresh_attestation(self):
        provider = AsyncMock(
            side_effect=[Attestation("!first", "a" * 32), Attestation("!second", "b" * 32)]
        )
        client, captured = self.make_client(provider, retry_once=True)
        with (
            patch("gemini_webapi.utils.decorators.asyncio.sleep", new_callable=AsyncMock),
            self.assertRaises(RequestCapturedError),
        ):
            await self.generate(client)
        self.assertEqual(provider.await_count, 2)
        self.assertEqual(captured[0][3:5], ["!first", "a" * 32])
        self.assertEqual(captured[1][3:5], ["!second", "b" * 32])
        self.assertEqual(provider.await_args.args[0].cid, "")

    async def test_default_request_is_unchanged(self):
        client, captured = self.make_client()
        with self.assertRaises(RequestCapturedError):
            await self.generate(client)
        self.assertEqual(captured[0][3:5], [None, None])

    async def test_deep_research_retains_existing_attestation(self):
        provider = AsyncMock()
        client, captured = self.make_client(provider)
        with self.assertRaises(RequestCapturedError):
            await self.generate(client, deep_research=True)
        provider.assert_not_awaited()
        self.assertTrue(captured[0][3].startswith("!"))
        self.assertEqual(len(captured[0][4]), 32)

    async def test_provider_failure_is_sanitized_and_not_retried(self):
        for error in (RuntimeError("private proof"), APIError("private proof")):
            with self.subTest(error=type(error).__name__):
                provider = AsyncMock(side_effect=error)
                client, captured = self.make_client(provider)
                with self.assertRaises(AttestationError) as raised:
                    await self.generate(client)
                self.assertNotIn("private proof", str(raised.exception))
                self.assertTrue(raised.exception.__suppress_context__)
                provider.assert_awaited_once()
                self.assertEqual(captured, [])

    async def test_invalid_results_abort_before_generation(self):
        for result in (
            None,
            ("!proof", "a" * 32),
            Attestation("", "a" * 32),
            Attestation("!", "a" * 32),
            Attestation("missing-prefix", "a" * 32),
            Attestation("!has whitespace", "a" * 32),
            Attestation("!proof", "A" * 32),
            Attestation("!proof", "a" * 31),
            Attestation("!proof", "z" * 32),
            Attestation(123, "a" * 32),
            Attestation("!proof", None),
        ):
            with self.subTest(result_type=type(result).__name__):
                provider = AsyncMock(return_value=result)
                client, captured = self.make_client(provider)
                with self.assertRaises(AttestationError):
                    await self.generate(client)
                provider.assert_awaited_once()
                self.assertEqual(captured, [])

    async def test_cancellation_propagates(self):
        provider = AsyncMock(side_effect=asyncio.CancelledError)
        with self.assertRaises(asyncio.CancelledError):
            await get_attestation(provider, AttestationRequest("prompt", "", "", ""))


if __name__ == "__main__":
    unittest.main()
