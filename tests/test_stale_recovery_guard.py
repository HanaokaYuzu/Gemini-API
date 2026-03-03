"""
Tests for the stale-recovery guard in continuation stream recovery.

Bug: When a CONTINUATION stream (where cid+rcid are already set) breaks
mid-stream and the recovery path polls read_chat(), the returned response
may have the SAME rcid as the previous turn -- meaning Gemini hasn't yet
persisted the new turn's response. The current code does not check for this,
so it silently yields stale data from the previous turn.

These tests define the expected behavior for the fix:
  1. Continuation recovery MUST compare the recovered response's rcid against
     the original_rcid that the chat had before the stream started.
  2. If the rcid matches (stale), the recovery should reject it and keep
     polling (or exhaust attempts and raise GeminiError).
  3. New-conversation recovery (original_cid was empty) should be unaffected.
  4. If the rcid differs (fresh), the recovery should accept it normally.

All three tests MUST FAIL against the current code because the stale-rcid
guard does not exist yet. This is the Red phase of TDD.
"""

import asyncio
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from gemini_webapi.client import GeminiClient, ChatSession
from gemini_webapi.types.modeloutput import ModelOutput
from gemini_webapi.types.candidate import Candidate
from gemini_webapi.exceptions import GeminiError, APIError


# ---------------------------------------------------------------------------
# Helpers (following patterns from test_retry_duplicate_conversations.py)
# ---------------------------------------------------------------------------

def _make_running_client() -> GeminiClient:
    """Create a minimal GeminiClient that appears initialized (running).

    The client is configured so the @running decorator sees _running=True
    and does not attempt real initialization.
    """
    client = GeminiClient.__new__(GeminiClient)
    client._running = True
    client.timeout = 30
    client.auto_close = False
    client.close_delay = 300
    client.auto_refresh = False
    client.refresh_interval = 540
    client.verbose = False
    client.watchdog_timeout = 60
    client._reqid = 10000
    client.access_token = "fake_token"
    client.build_label = None
    client.session_id = None
    client.cookies = MagicMock()
    client.client = AsyncMock()
    client.proxy = None
    client.kwargs = {}
    client._lock = asyncio.Lock()
    client.close_task = None
    client.refresh_task = None
    client.close = AsyncMock()
    return client


def _make_chat_session(
    client: GeminiClient,
    cid: str = "",
    rid: str = "",
    rcid: str = "",
) -> ChatSession:
    """Create a ChatSession with the given initial metadata."""
    chat = ChatSession.__new__(ChatSession)
    chat._ChatSession__metadata = [
        cid, rid, rcid, None, None, None, None, None, None, ""
    ]
    chat.geminiclient = client
    chat.last_output = None
    chat.model = "unspecified"
    chat.gem = None
    return chat


def _make_model_output(cid: str, rid: str, rcid: str, text: str) -> ModelOutput:
    """Build a ModelOutput with controlled metadata and rcid."""
    candidate = Candidate(rcid=rcid, text=text)
    return ModelOutput(
        metadata=[cid, rid, rcid],
        candidates=[candidate],
    )


def _make_fail_stream(status_code=500, on_enter=None):
    """Return a callable that produces async context managers simulating a
    failed HTTP stream response.

    Parameters
    ----------
    status_code : int
        The HTTP status code the mock response will report.
    on_enter : callable or None
        Optional side-effect function called each time the stream context
        is entered (useful for mutating state mid-stream).
    """
    mock_response = AsyncMock()
    mock_response.status_code = status_code

    class _FailStreamCtx:
        async def __aenter__(self_ctx):
            if on_enter is not None:
                on_enter()
            return mock_response

        async def __aexit__(self_ctx, *args):
            pass

    def stream_factory(*args, **kwargs):
        return _FailStreamCtx()

    return stream_factory


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestContinuationRecoveryRejectsStaleRcid(unittest.IsolatedAsyncioTestCase):
    """
    When a continuation stream (chat already has cid+rcid) breaks and
    read_chat returns a response with the SAME rcid as the original,
    the recovery should NOT yield that stale response.

    The stale response is from the previous turn -- Gemini hasn't persisted
    the new turn's response yet. Yielding it would silently give the caller
    old data, which is a data-integrity bug.

    This test MUST FAIL against current code because the recovery block
    at client.py:659-704 does not check rcid at all -- it accepts any
    non-None response from read_chat.
    """

    async def test_continuation_recovery_rejects_stale_rcid(self):
        """
        Scenario:
          1. ChatSession starts with cid="c_existing", rcid="rc_old_turn"
             (a continuation -- prior conversation exists).
          2. First stream attempt: server starts processing (had_response_data
             becomes True), then stream breaks with HTTP 500.
          3. @running catches APIError and retries.
          4. On retry entry: recovery guard triggers (had_response_data=True,
             chat.cid is truthy).
          5. read_chat() returns a ModelOutput with rcid="rc_old_turn" -- the
             SAME as the original. This is stale data from the previous turn.
          6. The guard should reject this stale response and continue polling.
          7. All polling attempts return stale data -> GeminiError is raised.

        Expected: GeminiError is raised because every recovered response had
        the same rcid as the original, indicating stale data.
        """
        client = _make_running_client()
        chat = _make_chat_session(
            client, cid="c_existing", rid="r_existing", rcid="rc_old_turn"
        )

        session_state = {
            "last_texts": {},
            "last_thoughts": {},
            "last_progress_time": time.time(),
        }

        stream_call_count = 0

        def on_stream_enter():
            nonlocal stream_call_count
            stream_call_count += 1
            if stream_call_count == 1:
                # Simulate server started processing before stream broke.
                session_state["had_response_data"] = True

        client.client.stream = _make_fail_stream(
            status_code=500, on_enter=on_stream_enter
        )

        # read_chat always returns the STALE previous turn's response.
        # The rcid "rc_old_turn" matches what the chat already had before
        # the stream started.
        stale_output = _make_model_output(
            cid="c_existing",
            rid="r_existing",
            rcid="rc_old_turn",
            text="This is the OLD turn's response -- stale data.",
        )
        client.read_chat = AsyncMock(return_value=stale_output)

        collected_outputs = []
        with patch("gemini_webapi.utils.decorators.DELAY_FACTOR", 0), \
             patch("gemini_webapi.client.asyncio.sleep", new_callable=AsyncMock):
            with self.assertRaises((APIError, GeminiError)):
                async for output in client._generate(
                    prompt="continue the conversation",
                    chat=chat,
                    session_state=session_state,
                ):
                    collected_outputs.append(output)

        # The stale output should NOT have been yielded.
        self.assertEqual(
            len(collected_outputs), 0,
            "No outputs should be yielded when read_chat only returns stale "
            "responses with the same rcid as the original.",
        )

        # read_chat should have been called multiple times (all attempts
        # exhausted because every response was stale).
        self.assertGreaterEqual(
            client.read_chat.await_count, 2,
            "read_chat should be polled multiple times before giving up.",
        )

        # had_response_data should be reset so @running can safely retry
        self.assertFalse(
            session_state.get("had_response_data"),
            "had_response_data should be reset to False for safe retry.",
        )

        # rid/rcid should be stripped so retry doesn't send stale metadata
        self.assertEqual(
            chat.rid, "",
            "rid should be cleared so retry lets server determine append point.",
        )
        self.assertEqual(
            chat.rcid, "",
            "rcid should be cleared so retry doesn't send stale continuation.",
        )


class TestNewConversationRecoveryStillWorks(unittest.IsolatedAsyncioTestCase):
    """
    When a NEW conversation stream (original_cid was empty/None) breaks
    and read_chat returns a valid response, recovery should work normally
    and yield the response.

    This ensures the stale-rcid guard does not break the existing recovery
    path for new conversations, where there is no "previous turn" to
    compare against and any response from read_chat is valid.
    """

    async def test_new_conversation_recovery_still_works(self):
        """
        Scenario:
          1. ChatSession starts with cid="" (new conversation, no prior turns).
          2. First stream attempt: Gemini assigns cid="c_new_assigned"
             mid-stream, then stream breaks with HTTP 500.
          3. @running catches APIError and retries.
          4. On retry entry: recovery guard triggers (original_cid was "",
             chat.cid is now truthy).
          5. read_chat() returns a valid ModelOutput with rcid="rc_first_turn".
          6. Since this is a new conversation (no prior rcid to compare),
             the response should be accepted and yielded.

        Expected: The recovered ModelOutput is yielded successfully. No error.
        """
        client = _make_running_client()
        chat = _make_chat_session(client, cid="", rid="", rcid="")

        session_state = {
            "last_texts": {},
            "last_thoughts": {},
            "last_progress_time": time.time(),
        }

        stream_call_count = 0

        def on_stream_enter():
            nonlocal stream_call_count
            stream_call_count += 1
            if stream_call_count == 1:
                # Simulate Gemini assigning a cid mid-stream before break.
                chat.cid = "c_new_assigned"

        client.client.stream = _make_fail_stream(
            status_code=500, on_enter=on_stream_enter
        )

        # read_chat returns a valid first-turn response.
        recovered_output = _make_model_output(
            cid="c_new_assigned",
            rid="r_first",
            rcid="rc_first_turn",
            text="This is the first turn's response.",
        )
        client.read_chat = AsyncMock(return_value=recovered_output)

        collected_outputs = []
        with patch("gemini_webapi.utils.decorators.DELAY_FACTOR", 0), \
             patch("gemini_webapi.client.asyncio.sleep", new_callable=AsyncMock):
            # Should NOT raise -- recovery succeeds for new conversations.
            async for output in client._generate(
                prompt="start a new conversation",
                chat=chat,
                session_state=session_state,
            ):
                collected_outputs.append(output)

        # The recovered output should be among the yielded outputs.
        self.assertTrue(
            any(o is recovered_output for o in collected_outputs),
            "The recovered ModelOutput from read_chat() should be yielded "
            "for new conversations. The stale-rcid guard should not interfere "
            "when there is no prior rcid to compare against.",
        )

        # read_chat should have been called exactly once (first attempt
        # succeeds because the response is valid for new conversations).
        client.read_chat.assert_awaited_once_with("c_new_assigned")

        # The fix should track original_rcid in session_state. For new
        # conversations, the original rcid is empty/"", so any rcid from
        # read_chat is accepted (no stale check needed). Verify the
        # tracking mechanism exists.
        self.assertIn(
            "original_rcid", session_state,
            "session_state must track 'original_rcid' to support the stale "
            "recovery guard. For new conversations, this should be set to "
            "the chat's initial rcid (empty string). This fails because "
            "the tracking mechanism does not exist yet.",
        )


class TestContinuationRecoveryAcceptsNewRcid(unittest.IsolatedAsyncioTestCase):
    """
    When a continuation stream breaks and read_chat returns a response
    with a DIFFERENT rcid than the original, recovery should accept it.

    A different rcid means Gemini has persisted the NEW turn's response.
    This is the correct data to yield.

    This test MUST FAIL against current code because the code doesn't
    store original_rcid at all, so there is no mechanism to track that
    an rcid check was performed. The test verifies both (a) the output
    is yielded and (b) the chat metadata is updated from the recovered
    response.
    """

    async def test_continuation_recovery_accepts_new_rcid(self):
        """
        Scenario:
          1. ChatSession starts with cid="c_existing", rcid="rc_old_turn"
             (a continuation).
          2. First stream attempt: server starts processing (had_response_data
             becomes True), then stream breaks.
          3. Recovery triggers. read_chat() returns a ModelOutput with
             rcid="rc_new_turn" -- a DIFFERENT rcid than the original.
          4. The guard should accept this response (it's the new turn's data).

        Expected: The recovered ModelOutput is yielded. Chat metadata is
        updated to reflect the new turn.
        """
        client = _make_running_client()
        chat = _make_chat_session(
            client, cid="c_existing", rid="r_existing", rcid="rc_old_turn"
        )

        session_state = {
            "last_texts": {},
            "last_thoughts": {},
            "last_progress_time": time.time(),
        }

        stream_call_count = 0

        def on_stream_enter():
            nonlocal stream_call_count
            stream_call_count += 1
            if stream_call_count == 1:
                session_state["had_response_data"] = True

        client.client.stream = _make_fail_stream(
            status_code=500, on_enter=on_stream_enter
        )

        # read_chat returns a response with a NEW rcid (different from the
        # original "rc_old_turn"). This means Gemini has persisted the new
        # turn's response.
        fresh_output = _make_model_output(
            cid="c_existing",
            rid="r_new",
            rcid="rc_new_turn",
            text="This is the NEW turn's response -- fresh data.",
        )
        client.read_chat = AsyncMock(return_value=fresh_output)

        collected_outputs = []
        with patch("gemini_webapi.utils.decorators.DELAY_FACTOR", 0), \
             patch("gemini_webapi.client.asyncio.sleep", new_callable=AsyncMock):
            # Should NOT raise -- recovery succeeds with fresh rcid.
            async for output in client._generate(
                prompt="continue the conversation",
                chat=chat,
                session_state=session_state,
            ):
                collected_outputs.append(output)

        # The fresh output should be yielded.
        self.assertTrue(
            any(o is fresh_output for o in collected_outputs),
            "The recovered ModelOutput with a new rcid should be yielded. "
            "The guard should only reject responses with the SAME rcid as "
            "the original.",
        )

        # read_chat should have been called exactly once (first attempt
        # returns fresh data).
        client.read_chat.assert_awaited_once_with("c_existing")

        # Chat metadata should be updated from the recovered response.
        # The recovery block does: chat.metadata = recovered.metadata
        self.assertEqual(
            chat.rcid, "rc_new_turn",
            "ChatSession.rcid should be updated to the new turn's rcid "
            "after successful recovery.",
        )

        # Verify original_rcid tracking was used. The fix stores the chat's
        # rcid before the stream started, and the recovery block compares
        # the recovered rcid against it. For this test, original_rcid should
        # be "rc_old_turn" and the recovered rcid is "rc_new_turn" (different),
        # so the response is accepted.
        self.assertIn(
            "original_rcid", session_state,
            "session_state must track 'original_rcid' to detect stale "
            "responses. This fails because the tracking mechanism does "
            "not exist yet.",
        )
        self.assertEqual(
            session_state["original_rcid"], "rc_old_turn",
            "original_rcid should be the rcid the chat had before the "
            "stream started, so the guard can compare against it.",
        )


if __name__ == "__main__":
    unittest.main()
