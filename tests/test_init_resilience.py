"""Automated resilience tests for GeminiClient initialization and deadlock prevention.

@purpose Verify deterministic deadlock prevention, fast failure propagation, and cache protection during client initialization.
@rationale Previous implementation suffered from recursive deadlock where retry decorators invoked init() while self._lock was held; these tests ensure zero-deadlock guarantees and transaction safety.
@preconditions Python 3.11+ environment with pytest and unittest support.
@param None
@returns None
@throws AssertionError If deadlock occurs or cache invariants are breached.
@invariants All tests execute strictly offline without external network or credential dependencies.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from curl_cffi.requests import AsyncSession, Cookies, Response

from gemini_webapi import GeminiClient
from gemini_webapi.exceptions import APIError
from gemini_webapi.utils.get_access_token import InitSession


@pytest.mark.asyncio
async def test_init_rpc_failure_does_not_deadlock(tmp_path):
    """Verify that an RPC error during init() raises APIError in < 5 seconds without deadlocking.

    @purpose Guarantee that non-200 RPC responses during init do not hang waiting on self._lock.
    @rationale The @running decorator must pass-through execution when _initializing is True.
    @preconditions Mocked network returning HTTP 503 or 400.
    @param tmp_path Pytest temporary directory fixture.
    @returns None
    @throws AssertionError If execution times out or unexpected exception is raised.
    @invariants O(1) computational complexity; deterministic timeout boundary.
    """
    mock_session = MagicMock(spec=AsyncSession)
    mock_session.cookies = Cookies()
    mock_session.close = AsyncMock()

    mock_init_session = InitSession(
        access_token="fake_token",
        build_label="fake_build",
        session_id="fake_session",
        language="en",
        push_id="fake_push",
        client=mock_session,
        cookie_source="Base Cookies",
    )

    client = GeminiClient(secure_1psid="test_psid")

    with (
        patch("gemini_webapi.client.get_access_token", AsyncMock(return_value=mock_init_session)),
        patch.object(
            client,
            "_batch_execute",
            AsyncMock(side_effect=APIError("Simulated RPC 503 error", status_code=503)),
        ),
        patch("gemini_webapi.utils.rotate_1psidts.get_cookie_cache_dir", return_value=tmp_path),
    ):
        with pytest.raises(APIError) as exc_info:
            await asyncio.wait_for(client.init(auto_refresh=False), timeout=4.0)

        assert exc_info.value.status_code == 503
        assert client._running is False
        assert client._initializing is False


@pytest.mark.asyncio
async def test_init_failure_does_not_write_cache(tmp_path):
    """Verify that a failed initialization never writes or pollutes the disk cache.

    @purpose Prevent writing unauthenticated or partial cookies into disk cache on failure.
    @rationale was_running must be False during init failures so close() skips cache persistence.
    @preconditions Mocked failing init.
    @param tmp_path Pytest temporary directory fixture.
    @returns None
    @throws AssertionError If cache files are generated on failure.
    @invariants Zero filesystem contamination on failed operations.
    """
    mock_session = MagicMock(spec=AsyncSession)
    mock_session.cookies = Cookies()
    mock_session.close = AsyncMock()

    mock_init_session = InitSession(
        access_token="fake_token",
        build_label="fake_build",
        session_id="fake_session",
        language="en",
        push_id="fake_push",
        client=mock_session,
        cookie_source="Base Cookies",
    )

    client = GeminiClient(secure_1psid="test_psid")

    with (
        patch("gemini_webapi.client.get_access_token", AsyncMock(return_value=mock_init_session)),
        patch.object(
            client,
            "_batch_execute",
            AsyncMock(side_effect=APIError("Simulated 400 Bad Request", status_code=400)),
        ),
        patch("gemini_webapi.utils.rotate_1psidts.get_cookie_cache_dir", return_value=tmp_path),
    ):
        with pytest.raises(APIError):
            await asyncio.wait_for(client.init(auto_refresh=False), timeout=4.0)

        cache_files = list(tmp_path.glob("*.json"))
        assert len(cache_files) == 0, f"Cache was written despite failed init: {cache_files}"
