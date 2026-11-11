import unittest
from types import SimpleNamespace
from unittest import mock

from gemini_webapi import GeminiClient
from gemini_webapi.exceptions import APIError
from gemini_webapi.types import Candidate, ModelOutput
from gemini_webapi.utils import decorators
from gemini_webapi.utils.decorators import running


def _metadata_only() -> ModelOutput:
    return ModelOutput(metadata=["c_test"], candidates=[Candidate(rcid="r_test", text="")])


def _with_text(text: str) -> ModelOutput:
    return ModelOutput(metadata=["c_test"], candidates=[Candidate(rcid="r_test", text=text)])


class FakeClient:
    _running = True
    verbose = False

    def __init__(self) -> None:
        self.close_calls = 0

    async def close(self) -> None:
        self.close_calls += 1


class StallThresholdTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = SimpleNamespace(timeout=600.0, watchdog_timeout=120.0)

    def threshold(self, *, is_thinking: bool, is_queueing: bool, has_output: bool) -> float:
        return GeminiClient._stall_threshold(
            self.client,
            is_thinking=is_thinking,
            is_queueing=is_queueing,
            has_output=has_output,
        )

    def test_before_first_output_uses_request_timeout(self) -> None:
        assert self.threshold(is_thinking=False, is_queueing=False, has_output=False) == 600.0

    def test_thinking_and_queueing_use_request_timeout(self) -> None:
        assert self.threshold(is_thinking=True, is_queueing=False, has_output=True) == 600.0
        assert self.threshold(is_thinking=False, is_queueing=True, has_output=True) == 600.0

    def test_after_output_uses_watchdog(self) -> None:
        assert self.threshold(is_thinking=False, is_queueing=False, has_output=True) == 120.0


class AsyncGeneratorRetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_retries_when_only_metadata_was_yielded(self) -> None:
        attempts = 0

        @running(retry=1)
        async def stream(client: FakeClient):
            nonlocal attempts
            attempts += 1
            yield _metadata_only()
            if attempts == 1:
                raise APIError("The original request may have been silently aborted by Google.")
            yield _with_text("done")

        client = FakeClient()
        with mock.patch.object(decorators.asyncio, "sleep", new=mock.AsyncMock()):
            items = [item async for item in stream(client)]

        assert attempts == 2
        assert items[-1].text == "done"

    async def test_does_not_retry_after_visible_output(self) -> None:
        attempts = 0

        @running(retry=1)
        async def stream(client: FakeClient):
            nonlocal attempts
            attempts += 1
            yield _with_text("partial")
            raise APIError("The original request may have been silently aborted by Google.")

        client = FakeClient()
        failed = False
        with mock.patch.object(decorators.asyncio, "sleep", new=mock.AsyncMock()):
            try:
                async for _ in stream(client):
                    pass
            except APIError:
                failed = True

        assert failed
        assert attempts == 1
