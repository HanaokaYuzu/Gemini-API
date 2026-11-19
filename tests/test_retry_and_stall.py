import unittest
from types import SimpleNamespace
from unittest import mock

import orjson as json

from gemini_webapi import GeminiClient
from gemini_webapi.client import ChatSession
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


def _make_stream_chunk(
    cid: str = "c_test",
    rid: str = "r_test",
    rcid: str = "rc_test",
    text: str = "",
    completed: bool = False,
) -> bytes:
    candidate = [
        rcid,
        [text] if text else None,
        None,
        None,
        None,
        None,
        None,
        None,
        [2 if completed else 1],
    ]
    inner = [None, [cid, rid], None, None, [candidate]]
    part = ["wrb.fr", None, json.dumps(inner).decode("utf-8")]
    payload = json.dumps([part]).decode("utf-8")
    return f"{len(payload) + 1}\n{payload}\n".encode()


class _AsyncChunkIterator:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = list(chunks)

    def __aiter__(self) -> "_AsyncChunkIterator":
        return self

    async def __anext__(self) -> bytes:
        if not self._chunks:
            raise StopAsyncIteration
        return self._chunks.pop(0)


class _StreamContext:
    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks

    async def __aenter__(self) -> mock.MagicMock:
        resp = mock.MagicMock()
        resp.status_code = 200
        resp.http_version = 2
        resp.aiter_content.return_value = _AsyncChunkIterator(self.chunks)
        return resp

    async def __aexit__(self, *args: object) -> None:
        pass


class GenerateRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_candidate_stall_retries_and_restores_chat(self) -> None:
        client = GeminiClient()
        client._running = True
        client.init = mock.AsyncMock(side_effect=lambda **kw: setattr(client, "_running", True))
        client.close = mock.AsyncMock()
        client._fetch_usage_info = mock.AsyncMock()
        client._check_account_status = mock.MagicMock(return_value=False)

        chat = ChatSession(
            client, cid="c_orig", rid="r_orig", rcid="rc_orig", metadata=["orig_meta"]
        )

        stream_calls = 0
        sent_metadatas = []

        def fake_stream(
            method: str, url: str, data: dict | None = None, **kwargs: object
        ) -> _StreamContext:
            nonlocal stream_calls
            stream_calls += 1
            assert data is not None
            req_json = json.loads(data["f.req"])
            inner_req = json.loads(req_json[1])
            sent_metadatas.append(inner_req[2])
            if stream_calls == 1:
                return _StreamContext(
                    [
                        _make_stream_chunk(
                            cid="c_new", rid="r_new", rcid="rc_new", text="", completed=False
                        )
                    ]
                )
            return _StreamContext(
                [
                    _make_stream_chunk(
                        cid="c_orig",
                        rid="r_orig",
                        rcid="rc_final",
                        text="recovered!",
                        completed=True,
                    )
                ]
            )

        mock_http = mock.MagicMock()
        mock_http.stream.side_effect = fake_stream
        client.client = mock_http

        with mock.patch.object(decorators.asyncio, "sleep", new=mock.AsyncMock()):
            items = [item async for item in client._generate("hi", chat=chat)]

        assert stream_calls == 2
        assert sent_metadatas[0][0:3] == ["c_orig", "r_orig", "rc_orig"]
        assert sent_metadatas[1][0:3] == ["c_orig", "r_orig", "rc_orig"]
        assert items[-1].text == "recovered!"
        assert chat.rcid == "rc_final"

    async def test_empty_candidate_maintains_request_timeout_threshold(self) -> None:
        client = GeminiClient()
        client.timeout = 600.0
        client.watchdog_timeout = 120.0
        client._running = True
        client.init = mock.AsyncMock(side_effect=lambda **kw: setattr(client, "_running", True))
        client.close = mock.AsyncMock()
        client._fetch_usage_info = mock.AsyncMock()
        client._check_account_status = mock.MagicMock(return_value=False)

        threshold_args = []
        orig_stall_threshold = client._stall_threshold

        def tracked_stall_threshold(
            *, is_thinking: bool, is_queueing: bool, has_output: bool
        ) -> float:
            threshold_args.append(
                {"is_thinking": is_thinking, "is_queueing": is_queueing, "has_output": has_output}
            )
            return orig_stall_threshold(
                is_thinking=is_thinking, is_queueing=is_queueing, has_output=has_output
            )

        client._stall_threshold = tracked_stall_threshold

        chunks = [
            _make_stream_chunk(text="", completed=False),
            _make_stream_chunk(text="first text", completed=True),
        ]
        mock_http = mock.MagicMock()
        mock_http.stream.return_value = _StreamContext(chunks)
        client.client = mock_http

        items = [item async for item in client._generate("hi")]
        assert len(items) == 2
        assert not threshold_args[1]["has_output"]
        assert orig_stall_threshold(**threshold_args[1]) == 600.0

    async def test_recovery_timeout_raises_retryable_api_error_on_empty_candidate(self) -> None:
        client = GeminiClient()
        client.timeout = 600.0
        client.watchdog_timeout = 120.0
        client._running = True
        client.init = mock.AsyncMock(side_effect=lambda **kw: setattr(client, "_running", True))
        client.close = mock.AsyncMock()
        client._fetch_usage_info = mock.AsyncMock()
        client._check_account_status = mock.MagicMock(return_value=True)
        client._sync_activity = mock.AsyncMock()
        client.read_chat = mock.AsyncMock(return_value=None)

        stream_calls = 0

        def fake_stream(
            method: str, url: str, data: dict | None = None, **kwargs: object
        ) -> _StreamContext:
            nonlocal stream_calls
            stream_calls += 1
            if stream_calls == 1:
                return _StreamContext([_make_stream_chunk(cid="c_poll", text="", completed=False)])
            return _StreamContext(
                [_make_stream_chunk(cid="c_poll", text="recovered!", completed=True)]
            )

        mock_http = mock.MagicMock()
        mock_http.stream.side_effect = fake_stream
        client.client = mock_http

        time_values = [0.0, 0.0, 0.0, 1000.0]

        def fake_time() -> float:
            if time_values:
                return time_values.pop(0)
            return 2000.0

        with (
            mock.patch.object(decorators.asyncio, "sleep", new=mock.AsyncMock()),
            mock.patch("gemini_webapi.client.time.time", side_effect=fake_time),
        ):
            items = [item async for item in client._generate("hi")]

        assert stream_calls == 2
        assert items[-1].text == "recovered!"

    async def test_does_not_retry_or_rollback_after_visible_output(self) -> None:
        client = GeminiClient()
        client._running = True
        client.init = mock.AsyncMock(side_effect=lambda **kw: setattr(client, "_running", True))
        client.close = mock.AsyncMock()
        client._fetch_usage_info = mock.AsyncMock()
        client._check_account_status = mock.MagicMock(return_value=False)

        chat = ChatSession(
            client, cid="c_orig", rid="r_orig", rcid="rc_orig", metadata=["orig_meta"]
        )
        stream_calls = 0

        def fake_stream(
            method: str, url: str, data: dict | None = None, **kwargs: object
        ) -> _StreamContext:
            nonlocal stream_calls
            stream_calls += 1
            return _StreamContext(
                [
                    _make_stream_chunk(
                        cid="c_new",
                        rid="r_new",
                        rcid="rc_new",
                        text="partial text",
                        completed=False,
                    )
                ]
            )

        mock_http = mock.MagicMock()
        mock_http.stream.side_effect = fake_stream
        client.client = mock_http

        failed = False
        with mock.patch.object(decorators.asyncio, "sleep", new=mock.AsyncMock()):
            try:
                async for _ in client._generate("hi", chat=chat):
                    pass
            except APIError:
                failed = True

        assert failed
        assert stream_calls == 1
        assert chat.rcid == "rc_new"
