#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from gemini_webapi import GeminiClient, logger, set_log_level  # noqa: E402
from gemini_webapi.constants import Model  # noqa: E402
from gemini_webapi.exceptions import AuthError  # noqa: E402
from gemini_webapi.types.image import GeneratedImage, WebImage  # noqa: E402
from gemini_webapi.utils import rotate_1psidts  # noqa: E402

INIT_MAX_RETRIES = 3


# ---------------------------------------------------------------------------
# Cookie helpers
# ---------------------------------------------------------------------------

def _parse_expiry(value):
    if value is None:
        return None

    if isinstance(value, (int, float)):
        return int(value)

    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None

        try:
            return int(float(raw))
        except ValueError:
            pass

        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return int(dt.timestamp())
        except ValueError:
            pass

        try:
            dt = parsedate_to_datetime(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp())
        except Exception:
            return None

    return None


def _load_cookies_with_meta(path: str | Path) -> tuple[dict[str, str], dict[str, dict]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))

    cookies: dict[str, str] = {}
    meta: dict[str, dict] = {}

    def _upsert(name, value, expires_raw=None):
        if not isinstance(name, str) or not name:
            return
        if not isinstance(value, str) or not value:
            return
        cookies[name] = value
        exp_epoch = _parse_expiry(expires_raw)
        m = {
            "expires_raw": expires_raw,
            "expires_epoch": exp_epoch,
            "expires_iso": (
                datetime.fromtimestamp(exp_epoch, tz=timezone.utc).isoformat().replace("+00:00", "Z")
                if exp_epoch is not None
                else None
            ),
        }
        meta[name] = m

    def _handle_cookie_obj(item: dict):
        name = item.get("name")
        value = item.get("value")
        expires_raw = (
            item.get("expirationDate")
            if "expirationDate" in item
            else item.get("expires")
            if "expires" in item
            else item.get("expiry")
            if "expiry" in item
            else item.get("expiresDate")
        )
        _upsert(name, value, expires_raw=expires_raw)

    # Flat object {name: value}
    if isinstance(data, dict) and all(
        isinstance(k, str) and isinstance(v, str) for k, v in data.items()
    ):
        for k, v in data.items():
            _upsert(k, v)
        return cookies, meta

    # {"cookies": {name: value, ...}}
    if isinstance(data, dict) and isinstance(data.get("cookies"), dict):
        inner = data["cookies"]
        if all(isinstance(k, str) and isinstance(v, str) for k, v in inner.items()):
            for k, v in inner.items():
                _upsert(k, v)
            return cookies, meta

    # {"cookies": [{name, value, ...}, ...]}
    if isinstance(data, dict) and isinstance(data.get("cookies"), list):
        for item in data["cookies"]:
            if isinstance(item, dict):
                _handle_cookie_obj(item)
        if cookies:
            return cookies, meta

    # [{name, value, ...}, ...]
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                _handle_cookie_obj(item)
        if cookies:
            return cookies, meta

    raise SystemExit(
        "--cookies-json unsupported format. Expected {name:value}, {'cookies':[...]} or [...]."
    )


def _persist_cookies(
    cookies_json_path: str | Path,
    original_cookies: dict[str, str],
    client_cookies,
    verbose: bool = False,
) -> None:
    merged = dict(original_cookies)

    try:
        for cookie in client_cookies.jar:
            name = getattr(cookie, "name", None)
            value = getattr(cookie, "value", None)
            if isinstance(name, str) and isinstance(value, str) and value:
                merged[name] = value
    except Exception:
        pass

    if merged == original_cookies:
        if verbose:
            logger.debug("No cookie changes to persist")
        return

    changed = [k for k in merged if merged[k] != original_cookies.get(k)]

    payload = {
        "updated_at": datetime.now(tz=timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
        "cookies": {k: v for k, v in sorted(merged.items())},
    }
    Path(cookies_json_path).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if verbose:
        logger.debug(f"Persisted cookies to {cookies_json_path} (updated: {', '.join(changed)})")


def _cookie_expiry_diagnostics(
    meta: dict[str, dict], present_names: set[str] | None = None
) -> dict:
    present_names = present_names or set()

    def _analyze_group(names):
        expires = {}
        for name in names:
            epoch = (meta.get(name) or {}).get("expires_epoch")
            if isinstance(epoch, (int, float)):
                expires[name] = int(epoch)
        present_without = [n for n in names if n in present_names and n not in expires]
        if not expires:
            return {
                "names": names,
                "present_with_expiry": [],
                "present_without_expiry": present_without,
                "missing": [n for n in names if n not in present_names],
                "spread_seconds": None,
                "reference_expires_iso": None,
            }
        values = list(expires.values())
        ref = max(values)
        return {
            "names": names,
            "present_with_expiry": sorted(expires.keys()),
            "present_without_expiry": present_without,
            "missing": [n for n in names if n not in present_names],
            "spread_seconds": max(values) - min(values),
            "reference_expires_iso": datetime.fromtimestamp(ref, tz=timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
            "expires_by_name": {
                n: datetime.fromtimestamp(v, tz=timezone.utc)
                .isoformat()
                .replace("+00:00", "Z")
                for n, v in expires.items()
            },
        }

    ts_names = ["__Secure-1PSIDTS", "__Secure-3PSIDTS"]
    cc_names = ["SIDCC", "__Secure-1PSIDCC", "__Secure-3PSIDCC"]
    ts_group = _analyze_group(ts_names)
    cc_group = _analyze_group(cc_names)

    return {"ts_group": ts_group, "cc_group": cc_group}


# ---------------------------------------------------------------------------
# Client init / teardown helpers
# ---------------------------------------------------------------------------

def _build_client_and_cookies(args) -> tuple[GeminiClient, dict[str, str]]:
    """Build GeminiClient instance (not yet initialized) and return json_cookies."""
    json_cookies: dict[str, str] = {}
    if args.cookies_json:
        json_cookies, _ = _load_cookies_with_meta(args.cookies_json)

    secure_1psid = json_cookies.get("__Secure-1PSID") or os.getenv("GEMINI_SECURE_1PSID")
    secure_1psidts = json_cookies.get("__Secure-1PSIDTS") or os.getenv("GEMINI_SECURE_1PSIDTS")

    if not secure_1psid:
        raise SystemExit(
            "Missing required cookie: __Secure-1PSID. "
            "Please export cookies from browser and provide via --cookies-json."
        )
    if not secure_1psidts:
        logger.warning("__Secure-1PSIDTS not found. Session may still work with long-lived cookies.")

    extra_cookies: dict[str, str] = {}
    for k, v in json_cookies.items():
        if k not in {"__Secure-1PSID", "__Secure-1PSIDTS"}:
            extra_cookies[k] = v

    client = GeminiClient(
        secure_1psid=secure_1psid,
        secure_1psidts=secure_1psidts or "",
        cookies=extra_cookies or None,
        proxy=args.proxy,
        account_index=args.account_index,
    )
    client.auto_refresh = False
    return client, json_cookies


async def _init_client(args) -> tuple[GeminiClient, dict[str, str]]:
    """Load cookies, create and init GeminiClient with auto-retry on AuthError."""
    if args.verbose:
        set_log_level("DEBUG")

    if args.proxy:
        from urllib.parse import urlparse
        parsed = urlparse(args.proxy)
        if parsed.username:
            redacted = parsed._replace(netloc=f"***:***@{parsed.hostname}" + (f":{parsed.port}" if parsed.port else ""))
            logger.info(f"Proxy enabled: {redacted.geturl()}")
        else:
            logger.info(f"Proxy enabled: {args.proxy}")

    client, json_cookies = _build_client_and_cookies(args)
    timeout = getattr(args, "request_timeout", 300)

    last_error: AuthError | None = None
    for attempt in range(1, INIT_MAX_RETRIES + 1):
        try:
            await client.init(timeout=timeout, verbose=args.verbose)
            return client, json_cookies
        except AuthError as e:
            last_error = e
            if attempt >= INIT_MAX_RETRIES:
                break
            logger.warning(f"Init attempt {attempt}/{INIT_MAX_RETRIES} failed: {e}")
            logger.info("Rotating 1PSIDTS cookie and retrying...")
            try:
                new_1psidts, rotated_cookies = await rotate_1psidts(client.cookies, client.proxy)
                if rotated_cookies:
                    client.cookies.update(rotated_cookies)
                    # Also update json_cookies so persist picks it up
                    if new_1psidts:
                        json_cookies["__Secure-1PSIDTS"] = new_1psidts
                    try:
                        for c in rotated_cookies.jar:
                            name = getattr(c, "name", None)
                            value = getattr(c, "value", None)
                            if isinstance(name, str) and isinstance(value, str) and value:
                                json_cookies[name] = value
                    except Exception:
                        pass
                    # Persist rotated cookies immediately so next run picks them up
                    if args.cookies_json and not args.no_persist:
                        _persist_cookies(args.cookies_json, json_cookies, client.cookies, verbose=args.verbose)
                    # Reset client internal state for re-init
                    client._running = False
                else:
                    logger.warning("Cookie rotation returned no update")
            except Exception as re:
                logger.warning(f"Cookie rotation failed: {re}")

    raise SystemExit(
        f"Failed to initialize after {INIT_MAX_RETRIES} attempts. "
        f"Last error: {last_error}\n"
        "Please refresh cookies from browser."
    )


async def _cleanup(client: GeminiClient, args, json_cookies: dict[str, str]):
    """Persist cookies and close client."""
    if args.cookies_json and not args.no_persist:
        _persist_cookies(args.cookies_json, json_cookies, client.cookies, verbose=args.verbose)
    await client.close()


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def _print_images(output):
    """Print image info from a ModelOutput if any."""
    if not output or not output.images:
        return
    web = [img for img in output.images if isinstance(img, WebImage)]
    gen = [img for img in output.images if isinstance(img, GeneratedImage)]
    if web:
        print("\n---\nImages:")
        for img in web:
            print(f"  {img.url}  {img.title or ''}")
    if gen:
        print("\n---\nGenerated images:")
        for img in gen:
            print(f"  {img.url}")


def _print_chat_id(output):
    """Print the chat ID from a ModelOutput."""
    if output and output.metadata:
        cid = output.metadata[0] if output.metadata else None
        if cid:
            print(f"\n---\nChat ID: {cid}")


def _extract_grounding_sources(raw_turns: list) -> list[dict]:
    """Extract grounding sources (search citations) from raw turns.

    Sources live at cand[2][1] in the newest assistant turn:
      each entry[2] = [[url, title, ...], ...]
    """
    from gemini_webapi.utils import get_nested_value

    if not raw_turns:
        return []

    seen = set()
    sources = []

    for turn in raw_turns:
        cand = get_nested_value(turn, [3, 0, 0])
        if not cand or not isinstance(cand, list):
            continue

        grounding = get_nested_value(cand, [2, 1])
        if not grounding or not isinstance(grounding, list):
            continue

        for entry in grounding:
            src_list = get_nested_value(entry, [2])
            if not src_list or not isinstance(src_list, list):
                continue
            for src in src_list:
                if not isinstance(src, list) or len(src) < 2:
                    continue
                url = src[0] if isinstance(src[0], str) else None
                title = src[1] if len(src) > 1 and isinstance(src[1], str) else ""
                if url and url not in seen:
                    seen.add(url)
                    clean_url = url.split("#")[0] if "#:~:text=" in url else url
                    sources.append({"url": clean_url, "title": title})
        break  # Only need the newest turn

    return sources


async def _print_sources(client, output):
    """Fetch and print grounding sources (search citations) if any."""
    if not output or not output.metadata:
        return
    cid = output.metadata[0] if output.metadata else None
    if not cid:
        return
    try:
        raw = await client.read_chat_raw(cid, max_turns=3)
        sources = _extract_grounding_sources(raw)
        if sources:
            print("\n---\nSources:")
            for s in sources:
                print(f"  {s['title']}")
                print(f"  {s['url']}")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Subcommand implementations
# ---------------------------------------------------------------------------

async def cmd_ask(args) -> int:
    client, json_cookies = await _init_client(args)
    try:
        files = [args.image] if getattr(args, "image", None) else None
        model = args.model

        if args.no_stream:
            output = await client.generate_content(args.prompt, files=files, model=model)
            print(output.text)
            _print_images(output)
            await _print_sources(client, output)
            _print_chat_id(output)
        else:
            output = None
            async for output in client.generate_content_stream(args.prompt, files=files, model=model):
                delta = output.text_delta
                if delta:
                    print(delta, end="", flush=True)
            if output:
                print()  # final newline
                _print_images(output)
                await _print_sources(client, output)
                _print_chat_id(output)
        return 0
    finally:
        await _cleanup(client, args, json_cookies)


async def cmd_reply(args) -> int:
    client, json_cookies = await _init_client(args)
    try:
        # Fetch latest turn to get rid/rcid for proper conversation continuation
        latest = await client.fetch_latest_chat_response(args.chat_id)
        if latest:
            rcid = latest.rcid
            metadata = list(latest.metadata)
            chat = client.start_chat(metadata=metadata, cid=args.chat_id, rcid=rcid, model=args.model)
        else:
            chat = client.start_chat(cid=args.chat_id, model=args.model)

        if args.no_stream:
            output = await chat.send_message(args.prompt)
            print(output.text)
            _print_images(output)
            await _print_sources(client, output)
        else:
            output = None
            async for output in chat.send_message_stream(args.prompt):
                delta = output.text_delta
                if delta:
                    print(delta, end="", flush=True)
            if output:
                print()
                _print_images(output)
                await _print_sources(client, output)

        print(f"\n---\nChat ID: {args.chat_id}")
        return 0
    finally:
        await _cleanup(client, args, json_cookies)


async def cmd_research_send(args) -> int:
    client, json_cookies = await _init_client(args)
    try:
        plan = await client.create_deep_research_plan(
            prompt=args.prompt,
            model=args.model,
        )
        await client.start_deep_research(plan=plan)

        if not plan.cid:
            raise SystemExit("Deep research failed: no chat ID returned.")

        # Human-friendly output
        print("Deep Research task submitted\n")
        if plan.title:
            print(f"  Title:  {plan.title}")
        if plan.eta_text:
            print(f"  ETA:    {plan.eta_text}")
        if plan.steps:
            print("  Steps:")
            for step in plan.steps:
                print(f"    - {step}")
        print(f"\n  Chat ID: {plan.cid}")
        print(f"\n  Use 'research check {plan.cid}' to check progress")
        print(f"  Use 'research get {plan.cid}' to fetch result")
        return 0
    finally:
        await _cleanup(client, args, json_cookies)


async def cmd_research_check(args) -> int:
    cid = args.chat_id
    client, json_cookies = await _init_client(args)
    try:
        latest = await client.fetch_latest_chat_response(cid)
        if latest:
            text = latest.text or ""
            lower = text.lower()
            has_completion_phrase = (
                "我已经完成了研究" in text
                or "研究完成" in text
                or "i have completed the research" in lower
                or "i've completed the research" in lower
                or "research is complete" in lower
            )
            looks_like_report = len(text) > 2000 and (text.lstrip().startswith("#") or "\n## " in text)
            done = has_completion_phrase or looks_like_report
            print(f"  Status: {'done' if done else 'in progress'}")
            print(f"  Response length: {len(text)} chars")
            if done:
                print(f"\n  Use 'research get {cid}' to retrieve the full result.")
        else:
            print("  Status: waiting (no response yet)")
        return 0
    finally:
        await _cleanup(client, args, json_cookies)


def _extract_research_result_from_raw(raw_turns: list) -> tuple[str, dict[int, dict]]:
    """Extract the deep research report text and numbered sources from raw turns.

    The deep research result lives at cand[30][0] in the newest turn:
      [30][0][4] = report text
      [30][0][5][0]["44"] = citation groups

    Returns (text, sources_dict) where sources_dict maps ref_number -> {url, title}.
    """
    from gemini_webapi.utils import get_nested_value

    text = ""
    sources: dict[int, dict] = {}

    for turn in raw_turns:
        cand = get_nested_value(turn, [3, 0, 0])
        if not cand or not isinstance(cand, list):
            continue

        # Check for deep research result at cand[30]
        dr_data = get_nested_value(cand, [30, 0])
        if not dr_data or not isinstance(dr_data, list) or len(dr_data) < 5:
            continue

        candidate_text = get_nested_value(dr_data, [4])
        if not isinstance(candidate_text, str) or len(candidate_text) < 200:
            continue

        text = candidate_text

        # Extract sources from [30][0][5][0]["44"]
        citations_container = get_nested_value(dr_data, [5, 0])
        if not isinstance(citations_container, dict):
            break
        citation_groups = citations_container.get("44", [])
        if not isinstance(citation_groups, list):
            break

        for group in citation_groups:
            if not isinstance(group, list) or len(group) < 2:
                continue
            for source_entries in group[1:]:
                if not isinstance(source_entries, list):
                    continue
                for item in source_entries:
                    if not isinstance(item, list) or len(item) < 4:
                        continue
                    inner = get_nested_value(item, [3])
                    if not isinstance(inner, list) or len(inner) < 2:
                        continue
                    detail = inner[0]
                    ref_num = inner[1] if len(inner) > 1 else None
                    if isinstance(detail, list) and len(detail) >= 3 and isinstance(ref_num, int):
                        url = detail[1]
                        title = detail[2]
                        if isinstance(url, str) and url.startswith("http"):
                            sources[ref_num] = {"url": url, "title": title or ""}
        break  # Only need the first matching turn

    return text, sources


def _format_sources_block(sources: dict[int, dict]) -> str:
    """Format sources as a markdown references block."""
    if not sources:
        return ""
    lines = ["\n\n---\n\n## References\n"]
    for num in sorted(sources.keys()):
        s = sources[num]
        lines.append(f"[{num}] [{s['title']}]({s['url']})")
    return "\n".join(lines) + "\n"


async def cmd_research_get(args) -> int:
    cid = args.chat_id

    client, json_cookies = await _init_client(args)
    try:
        # Try raw turns first to get both text and sources
        raw = await client.read_chat_raw(cid, max_turns=5)
        text = ""
        sources: dict[int, dict] = {}

        if raw:
            text, sources = _extract_research_result_from_raw(raw)

        # Fallback to fetch_latest_chat_response if raw extraction failed
        if not text:
            latest = await client.fetch_latest_chat_response(cid)
            if not latest:
                raise SystemExit(f"No response found for chat {cid}. Research may still be running.")
            text = latest.text or ""

        result = text + _format_sources_block(sources)

        output_file = getattr(args, "output", None)
        if output_file:
            p = Path(output_file)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(result, encoding="utf-8")
            print(f"Saved research result to {output_file} ({len(sources)} sources)")
        else:
            print(result)
        return 0
    finally:
        await _cleanup(client, args, json_cookies)


async def cmd_list(args) -> int:
    client, json_cookies = await _init_client(args)
    try:
        listing = await client.list_chats(cursor=args.cursor)

        err = str(listing.get("error") or "")
        if "code=7" in err:
            raise SystemExit("LIST_CHATS rejected with code=7. Please refresh cookies from browser.")

        items = listing.get("items", [])
        if not items:
            print("No chats found.")
            return 0

        # Table output
        id_w = max(len("ID"), max(len(it.get("cid", "")) for it in items))
        title_w = max(len("Title"), max(len((it.get("title") or "")[:50]) for it in items))
        upd_w = len("Updated")

        header = f"{'ID':<{id_w}}  {'Title':<{title_w}}  {'Updated':<{upd_w}}"
        print(header)
        print("-" * len(header))

        for it in items:
            cid = it.get("cid", "")
            title = (it.get("title") or "")[:50]
            updated = (it.get("updated_at") or "")[:16]
            print(f"{cid:<{id_w}}  {title:<{title_w}}  {updated}")

        cursor = listing.get("cursor")
        if cursor:
            print(f"\n(next page: --cursor {cursor})")
        return 0
    finally:
        await _cleanup(client, args, json_cookies)


async def cmd_read(args) -> int:
    client, json_cookies = await _init_client(args)
    try:
        turns = await client.read_chat(args.chat_id, max_turns=args.max_turns)

        if not turns:
            print(f"No turns found for chat {args.chat_id}")
            return 1

        lines = []
        for i, turn in enumerate(turns, 1):
            lines.append(f"--- message {i} ---")
            if turn.user_prompt:
                lines.append(f"[User] {turn.user_prompt}")
            if turn.assistant_response:
                lines.append(f"[Gemini] {turn.assistant_response}")
            lines.append("")

        text = "\n".join(lines)
        output_file = getattr(args, "output", None)
        if output_file:
            p = Path(output_file)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
            print(f"Saved chat to {output_file}")
        else:
            print(text)
        return 0
    finally:
        await _cleanup(client, args, json_cookies)


def _print_inspect_summary(snapshot: dict) -> None:
    """Print a human-readable diagnostic summary before the raw JSON."""
    summary = snapshot.get("summary", {})
    rpc = snapshot.get("rpc", {})

    print("=== Account Diagnostics ===\n")
    print(f"  Source path:   {snapshot.get('source_path', '?')}")
    print(f"  Account path:  {snapshot.get('account_path') or '(none — no multi-login detected)'}")

    # RPC status table
    print("\n  RPC Probes:")
    for name, probe in rpc.items():
        if not isinstance(probe, dict):
            continue
        if not probe.get("ok", False):
            status = f"ERROR: {probe.get('error', '?')}"
        elif probe.get("reject_code") is not None:
            status = f"REJECTED (code={probe['reject_code']})"
        elif probe.get("parsed"):
            status = "OK"
        else:
            status = "OK (empty)"
        print(f"    {name:<15} {status}")

    # Rejected probes explanation
    rejected = summary.get("rejected_probes", [])
    if rejected:
        print(f"\n  Rejected probes: {', '.join(rejected)}")
        print("  → reject_code=7 typically means:")
        print("    - Cookies are stale or incomplete (try re-exporting from browser)")
        print("    - Exit IP is in a restricted region (try a different proxy)")
        print("    - Account index mismatch (try --account-index 0, 1, 2...)")
    else:
        print("\n  All probes passed.")

    # Deep research
    dr = summary.get("deep_research_feature_present", False)
    rl = summary.get("deep_research_rate_limited", False)
    print(f"\n  Deep Research:")
    print(f"    Feature detected:  {'yes' if dr else 'no'}")
    print(f"    Rate limited:      {'YES' if rl else 'no'}")

    quota = summary.get("quota_rows", [])
    if quota:
        print(f"    Quota:")
        for row in quota:
            print(f"      {row.get('key', '?')}: {row.get('remaining', '?')}/{row.get('limit', '?')}")

    print()


async def cmd_download(args) -> int:
    url = args.url

    # Load cookies for authenticated download
    json_cookies: dict[str, str] = {}
    if args.cookies_json:
        json_cookies, _ = _load_cookies_with_meta(args.cookies_json)

    from httpx import AsyncClient, Cookies

    jar = Cookies()
    for k, v in json_cookies.items():
        jar.set(k, v, domain=".google.com")

    # Determine output filename
    output = args.output
    if not output:
        # Auto-generate from URL hash + timestamp
        from hashlib import md5
        url_hash = md5(url.encode()).hexdigest()[:8]
        output = f"gemini-{url_hash}.png"

    # Append =s2048 for full-size if not already specified
    dl_url = url
    if "googleusercontent.com" in url and "=" not in url.split("/")[-1]:
        dl_url = url + "=s2048"

    async with AsyncClient(
        http2=True,
        follow_redirects=True,
        cookies=jar,
        proxy=args.proxy,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        },
    ) as client:
        resp = await client.get(dl_url)
        if resp.status_code != 200:
            raise SystemExit(f"Download failed: HTTP {resp.status_code}")

        content_type = resp.headers.get("content-type", "")
        if "image" not in content_type and "octet" not in content_type:
            raise SystemExit(f"Unexpected content-type: {content_type}")

        p = Path(output)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(resp.content)
        size_kb = len(resp.content) / 1024
        print(f"Saved to {output} ({size_kb:.1f} KB)")
    return 0


async def cmd_inspect(args) -> int:
    if getattr(args, "cookies_only", False):
        # Cookie diagnostics only — no client init needed
        if not args.cookies_json:
            raise SystemExit("--cookies-json is required for --cookies-only")
        json_cookies, json_cookie_meta = _load_cookies_with_meta(args.cookies_json)
        report = {
            "cookies_json": str(args.cookies_json),
            "required": {
                "__Secure-1PSID": {
                    "present": "__Secure-1PSID" in json_cookies,
                    **json_cookie_meta.get("__Secure-1PSID", {}),
                },
                "__Secure-1PSIDTS": {
                    "present": "__Secure-1PSIDTS" in json_cookies,
                    **json_cookie_meta.get("__Secure-1PSIDTS", {}),
                },
            },
            "expiry_diagnostics": _cookie_expiry_diagnostics(
                json_cookie_meta, present_names=set(json_cookies.keys())
            ),
            "all_cookie_keys_in_json": sorted(json_cookies.keys()),
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    client, json_cookies = await _init_client(args)
    try:
        snapshot = await client.inspect_account_status()

        _print_inspect_summary(snapshot)
        return 0
    finally:
        await _cleanup(client, args, json_cookies)


# ---------------------------------------------------------------------------
# Argparse setup
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="CLI for gemini-webapi",
    )

    # Global arguments
    parser.add_argument("--cookies-json", default=None, help="Path to JSON cookie file")
    parser.add_argument(
        "--proxy",
        default=(
            os.getenv("HTTPS_PROXY")
            or os.getenv("https_proxy")
            or os.getenv("HTTP_PROXY")
            or os.getenv("http_proxy")
        ),
    )
    parser.add_argument("--account-index", type=int, default=None, help="Google account index (e.g. 2 => /u/2)")
    parser.add_argument("--model", default=Model.UNSPECIFIED.model_name, help="Model name")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    parser.add_argument("--no-persist", action="store_true", help="Do not write updated cookies back")
    parser.add_argument("--request-timeout", type=float, default=300, help="Per-request HTTP timeout in seconds")

    sub = parser.add_subparsers(dest="command")

    # --- ask ---
    p_ask = sub.add_parser("ask", help="Single-turn question")
    p_ask.add_argument("prompt", help="Prompt text")
    p_ask.add_argument("--no-stream", action="store_true", help="Wait for complete response")
    p_ask.add_argument("--image", default=None, help="Attach an image/file")

    # --- reply ---
    p_reply = sub.add_parser("reply", help="Continue an existing chat")
    p_reply.add_argument("chat_id", help="Chat ID (c_...)")
    p_reply.add_argument("prompt", help="Prompt text")
    p_reply.add_argument("--no-stream", action="store_true", help="Wait for complete response")

    # --- research (nested) ---
    p_research = sub.add_parser("research", help="Deep research workflow")
    research_sub = p_research.add_subparsers(dest="research_command")

    p_rs = research_sub.add_parser("send", help="Submit a deep research task")
    p_rs.add_argument("--prompt", required=True, help="Research prompt")

    p_rc = research_sub.add_parser("check", help="Check deep research progress")
    p_rc.add_argument("chat_id", help="Chat ID from 'research send'")

    p_rg = research_sub.add_parser("get", help="Get deep research result")
    p_rg.add_argument("chat_id", help="Chat ID from 'research send'")
    p_rg.add_argument("--output", default=None, help="Write result to file instead of stdout")

    # --- list ---
    p_list = sub.add_parser("list", help="List chat history")
    p_list.add_argument("--cursor", default=None, help="Pagination cursor")

    # --- read ---
    p_read = sub.add_parser("read", help="Read a chat conversation")
    p_read.add_argument("chat_id", help="Chat ID (c_...)")
    p_read.add_argument("--max-turns", type=int, default=30, help="Max turns to fetch")
    p_read.add_argument("--output", default=None, help="Write to file instead of stdout")

    # --- download ---
    p_dl = sub.add_parser("download", help="Download a generated image (requires cookies)")
    p_dl.add_argument("url", help="Image URL (googleusercontent.com)")
    p_dl.add_argument("--output", "-o", default=None, help="Output file path (default: auto from URL)")

    # --- models ---
    sub.add_parser("models", help="List available models")

    # --- inspect ---
    p_inspect = sub.add_parser("inspect", help="Account capability probe")
    p_inspect.add_argument("--cookies-only", action="store_true", help="Cookie expiry diagnostics only")

    return parser


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

async def run(args: argparse.Namespace) -> int:
    cmd = args.command

    if cmd == "ask":
        return await cmd_ask(args)
    elif cmd == "reply":
        return await cmd_reply(args)
    elif cmd == "research":
        rc = getattr(args, "research_command", None)
        if rc == "send":
            return await cmd_research_send(args)
        elif rc == "check":
            return await cmd_research_check(args)
        elif rc == "get":
            return await cmd_research_get(args)
        else:
            raise SystemExit("Usage: cli.py research {send|check|get}")
    elif cmd == "list":
        return await cmd_list(args)
    elif cmd == "read":
        return await cmd_read(args)
    elif cmd == "download":
        return await cmd_download(args)
    elif cmd == "models":
        print("Available models for --model:\n")
        for m in Model:
            default = " (default)" if m == Model.UNSPECIFIED else ""
            adv = " [advanced]" if m.advanced_only else ""
            print(f"  {m.model_name}{default}{adv}")
        print("\nNote: these map to specific request headers in the library.")
        print("Use 'unspecified' to let Gemini auto-select.")
        return 0
    elif cmd == "inspect":
        return await cmd_inspect(args)
    else:
        raise SystemExit("Usage: cli.py {ask|reply|research|list|read|models|inspect} ...")


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return 1
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
