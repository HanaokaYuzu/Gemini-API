"""Automated verification for sign-in redirect detection and access token guards.

@purpose Verify that Google sign-in page redirects (accounts.google.com) are rejected as valid authenticated sessions and Guest session failures yield actionable AuthErrors.
@rationale Google login pages contain SNlM0e tokens in their initial markup; failing to check response.url causes false-positive initialization that later fails on all RPC endpoints with HTTP 400.
@preconditions Python 3.11+ environment with pytest and unittest.mock.
@param None
@returns None
@throws AssertionError If sign-in page is accepted or Guest APIError is unhandled.
@invariants Invariant URL hostname check for gemini.google.com.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from curl_cffi.requests import AsyncSession, Cookies, Response

from gemini_webapi import GeminiClient
from gemini_webapi.exceptions import APIError, AuthError
from gemini_webapi.utils.get_access_token import InitSession, get_access_token


@pytest.mark.asyncio
async def test_signin_redirect_is_rejected():
    """Verify that a redirect to accounts.google.com is rejected as an init candidate."""
    mock_client = MagicMock(spec=AsyncSession)
    mock_client.cookies = Cookies()
    mock_client.close = AsyncMock()

    # Simulate response from accounts.google.com with SNlM0e token present
    mock_response = MagicMock(spec=Response)
    mock_response.url = "https://accounts.google.com/signin/v2/identifier?flowName=GlifWebSignIn"
    mock_response.status_code = 200
    mock_response.text = '"SNlM0e": "fake_signin_page_token"'
    mock_response.http_version = 2
    mock_response.raise_for_status = MagicMock()

    mock_client.get = AsyncMock(return_value=mock_response)

    test_cookies = Cookies()
    test_cookies.set("__Secure-1PSID", "test_psid", domain=".google.com", secure=True)

    with (
        patch("gemini_webapi.utils.get_access_token.AsyncSession", return_value=mock_client),
        patch("gemini_webapi.utils.get_access_token.get_cookies_cache_path", return_value=None),
        patch("gemini_webapi.utils.get_access_token.load_browser_cookies", return_value=None),
    ):
        with pytest.raises(AuthError) as exc_info:
            await get_access_token(base_cookies=test_cookies, verbose=True)

        assert "Failed to initialize client" in str(exc_info.value)


@pytest.mark.asyncio
async def test_guest_session_failure_raises_actionable_auth_error(tmp_path):
    """Verify that an APIError on Guest session init is wrapped into an actionable AuthError."""
    mock_session = MagicMock(spec=AsyncSession)
    mock_session.cookies = Cookies()
    mock_session.close = AsyncMock()

    mock_init_session = InitSession(
        access_token=None,
        build_label="fake_build",
        session_id="fake_session",
        language="en",
        push_id="fake_push",
        client=mock_session,
        cookie_source="Guest",
    )

    client = GeminiClient(secure_1psid="incomplete_cookie")

    with (
        patch("gemini_webapi.client.get_access_token", AsyncMock(return_value=mock_init_session)),
        patch.object(
            client,
            "_batch_execute",
            AsyncMock(side_effect=APIError("Batch execution failed with status code 400", status_code=400)),
        ),
        patch("gemini_webapi.utils.rotate_1psidts.get_cookie_cache_dir", return_value=tmp_path),
    ):
        with pytest.raises(AuthError) as exc_info:
            await client.init(auto_refresh=False)

        assert "cookie set is incomplete or invalid" in str(exc_info.value)
