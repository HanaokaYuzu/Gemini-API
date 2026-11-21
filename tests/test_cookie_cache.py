"""Automated verification for cookie cache resilience and non-destructive persistence.

@purpose Verify that session cookies, multi-domain bindings, and original file structures are preserved across cache cycles.
@rationale Discarding session cookies or flattening domains to .google.com breaks Google authentication and image downloading; these tests prevent regression.
@preconditions Python 3.11+ environment with pytest.
@param None
@returns None
@throws AssertionError If cookies are dropped, corrupted, or domains flattened.
@invariants All tests run strictly locally without network access.
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch

if (_root := str(Path(__file__).resolve().parent.parent)) not in sys.path:
    sys.path.insert(0, _root)

from curl_cffi.requests import Cookies

from cli import _load_cookies_data, _persist_cookies
from gemini_webapi.utils.get_access_token import _load_cached_jar
from gemini_webapi.utils.rotate_1psidts import (
    extract_cookie_value,
    get_cookies_cache_path,
    save_cookies,
)


def test_save_and_load_session_cookies_with_domains(tmp_path):
    """Verify that session cookies without expiration dates and domain specifics are fully cached.

    @purpose Test round-trip persistence of session cookies (expires=None) and specific domains (.gemini.google.com).
    @rationale Google requires OSID on gemini.google.com and SID/HSID session cookies for valid session continuation.
    @preconditions Isolated temporary directory for cache storage.
    @param tmp_path Pytest temporary directory fixture.
    @returns None
    @throws AssertionError If session cookies or domains are lost during round-trip.
    @invariants O(n) round-trip serialization; zero data loss.
    """
    with patch("gemini_webapi.utils.rotate_1psidts.get_cookie_cache_dir", return_value=tmp_path):
        jar = Cookies()
        # Auth cookies
        jar.set("__Secure-1PSID", "psid_val_123", domain=".google.com", secure=True)
        jar.set("__Secure-1PSIDTS", "psidts_val_456", domain=".google.com", secure=True)
        # Session cookies (expires is None)
        jar.set("OSID", "osid_gemini_val", domain=".gemini.google.com", secure=True)
        jar.set("SID", "sid_google_val", domain=".google.com", secure=True)
        jar.set("COMPASS", "compass_val", domain=".gemini.google.com", secure=True)

        save_cookies(jar, base_psid="psid_val_123", verbose=True)

        cache_path = get_cookies_cache_path(jar, base_psid="psid_val_123")
        assert cache_path is not None
        assert cache_path.is_file()

        # Load back from cache file
        loaded_jar = _load_cached_jar(cache_path, verbose=True)
        assert loaded_jar is not None

        # Verify values
        assert extract_cookie_value(loaded_jar, "__Secure-1PSID") == "psid_val_123"
        assert extract_cookie_value(loaded_jar, "__Secure-1PSIDTS") == "psidts_val_456"
        assert extract_cookie_value(loaded_jar, "OSID") == "osid_gemini_val"
        assert extract_cookie_value(loaded_jar, "SID") == "sid_google_val"
        assert extract_cookie_value(loaded_jar, "COMPASS") == "compass_val"

        # Verify domains
        cookie_domains = {c.name: c.domain for c in loaded_jar.jar}
        assert cookie_domains["OSID"] == ".gemini.google.com"
        assert cookie_domains["COMPASS"] == ".gemini.google.com"
        assert cookie_domains["SID"] == ".google.com"


def test_cli_persist_cookies_preserves_array_of_objects(tmp_path):
    """Verify that _persist_cookies preserves the browser-exported array-of-objects structure.

    @purpose Guarantee that original file format, metadata fields (hostOnly, expirationDate), and domains are not overwritten by flat dicts.
    @rationale Progressive degradation occurs when a list of objects is converted into a flat key-value dict.
    @preconditions Temporary JSON file with 24 cookie items from a browser extension.
    @param tmp_path Pytest temporary directory fixture.
    @returns None
    @throws AssertionError If array structure is flattened or domains are lost.
    @invariants Structural invariance across arbitrary persistence cycles.
    """
    cookie_file = tmp_path / "browser_cookies.json"
    original_data = [
        {
            "domain": ".gemini.google.com",
            "expirationDate": 1800000000,
            "hostOnly": False,
            "httpOnly": True,
            "name": "OSID",
            "path": "/",
            "sameSite": "no_restriction",
            "secure": True,
            "session": False,
            "storeId": "0",
            "value": "initial_osid",
        },
        {
            "domain": ".google.com",
            "expirationDate": 1800000000,
            "hostOnly": False,
            "httpOnly": True,
            "name": "__Secure-1PSIDTS",
            "path": "/",
            "sameSite": "no_restriction",
            "secure": True,
            "session": False,
            "storeId": "0",
            "value": "initial_psidts",
        },
        {
            "domain": ".google.com",
            "expirationDate": 1800000000,
            "hostOnly": False,
            "httpOnly": True,
            "name": "__Secure-1PSID",
            "path": "/",
            "sameSite": "no_restriction",
            "secure": True,
            "session": False,
            "storeId": "0",
            "value": "initial_psid",
        },
    ]
    cookie_file.write_text(json.dumps(original_data, indent=2), encoding="utf-8")

    # Load data via _load_cookies_data
    raw_data, jar = _load_cookies_data(cookie_file)
    assert isinstance(raw_data, list)
    assert len(raw_data) == 3

    # Simulate client cookie rotation (PSIDTS updated)
    client_cookies = Cookies()
    for c in jar.jar:
        client_cookies.set(c.name, c.value, domain=c.domain, path=c.path, secure=c.secure)
    client_cookies.set(
        "__Secure-1PSIDTS", "rotated_psidts_999", domain=".google.com", path="/", secure=True
    )

    _persist_cookies(cookie_file, raw_data, client_cookies, verbose=True)

    # Read back and verify
    reloaded = json.loads(cookie_file.read_text(encoding="utf-8"))
    assert isinstance(reloaded, list), "Format was altered from array-of-objects to something else!"
    assert len(reloaded) == 3

    item_map = {item["name"]: item for item in reloaded}
    assert item_map["__Secure-1PSIDTS"]["value"] == "rotated_psidts_999"
    assert item_map["OSID"]["value"] == "initial_osid"
    assert item_map["OSID"]["domain"] == ".gemini.google.com"
    assert item_map["OSID"]["hostOnly"] is False
    assert item_map["OSID"]["httpOnly"] is True
    assert item_map["OSID"]["expirationDate"] == 1800000000
