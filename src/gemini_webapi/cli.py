#!/usr/bin/env python3
"""CLI for gemini-webapi."""

import argparse
import asyncio
import contextlib
import json
import os
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlparse

from curl_cffi import CurlFollow, CurlHttpVersion

from gemini_webapi import GeminiClient, logger, set_log_level
from gemini_webapi.constants import BROWSER_TYPE
from gemini_webapi.exceptions import AuthError
from gemini_webapi.types.image import GeneratedImage, WebImage

# ---------------------------------------------------------------------------
# region - Cookie helpers
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
        with contextlib.suppress(ValueError):
            return int(float(raw))
        with contextlib.suppress(ValueError):
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return int(dt.timestamp())
        try:
            dt = parsedate_to_datetime(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return int(dt.timestamp())
        except Exception:
            return None
    return None


def _load_cookies_with_meta(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    cookies, meta = {}, {}

    def _upsert(name, value, expires_raw=None):
        if not isinstance(name, str) or not name:
            return
        if not isinstance(value, str) or not value:
            return
        cookies[name] = value
        exp = _parse_expiry(expires_raw)
        meta[name] = {
            "expires_raw": expires_raw,
            "expires_epoch": exp,
            "expires_iso": (
                datetime.fromtimestamp(exp, tz=UTC).isoformat().replace("+00:00", "Z")
                if exp is not None
                else None
            ),
        }

    def _handle_obj(item):
        name = item.get("name")
        value = item.get("value")
        expires_raw = (
            item.get("expirationDate")
            or item.get("expires")
            or item.get("expiry")
            or item.get("expiresDate")
        )
        _upsert(name, value, expires_raw=expires_raw)

    # Flat {name: value}
    if isinstance(data, dict) and all(
        isinstance(k, str) and isinstance(v, str) for k, v in data.items()
    ):
        for k, v in data.items():
            _upsert(k, v)
        return cookies, meta
    # {"cookies": {name: value}}
    if isinstance(data, dict) and isinstance(data.get("cookies"), dict):
        inner = data["cookies"]
        if all(isinstance(v, str) for v in inner.values()):
            for k, v in inner.items():
                _upsert(k, v)
            return cookies, meta
    # {"cookies": [{name, value}, ...]}
    if isinstance(data, dict) and isinstance(data.get("cookies"), list):
        for item in data["cookies"]:
            if isinstance(item, dict):
                _handle_obj(item)
        if cookies:
            return cookies, meta
    # [{name, value}, ...]
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                _handle_obj(item)
        if cookies:
            return cookies, meta

    raise SystemExit("--cookies-json unsupported format.")


def _persist_cookies(cookies_json_path, original, client_cookies, verbose=False):
    merged = dict(original)
    with contextlib.suppress(Exception):
        for cookie in client_cookies.jar:
            name = getattr(cookie, "name", None)
            value = getattr(cookie, "value", None)
            if isinstance(name, str) and isinstance(value, str) and value:
                merged[name] = value
    if merged == original:
        return
    payload = {
        "updated_at": datetime.now(tz=UTC).isoformat().replace("+00:00", "Z"),
        "cookies": dict(sorted(merged.items())),
    }
    Path(cookies_json_path).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if verbose:
        changed = [k for k in merged if merged[k] != original.get(k)]
        logger.debug(f"Persisted cookies ({', '.join(changed)})")


# ---------------------------------------------------------------------------
# region - Client init / teardown
# ---------------------------------------------------------------------------


def _build_client(args):
    json_cookies = {}
    if args.cookies_json:
        json_cookies, _ = _load_cookies_with_meta(args.cookies_json)

    psid = json_cookies.get("__Secure-1PSID") or os.getenv("GEMINI_SECURE_1PSID")
    psidts = json_cookies.get("__Secure-1PSIDTS") or os.getenv("GEMINI_SECURE_1PSIDTS")

    if not psid:
        raise SystemExit("Missing __Secure-1PSID. Export from browser via --cookies-json.")
    if not psidts:
        logger.warning("__Secure-1PSIDTS not found.")

    extra = {
        k: v for k, v in json_cookies.items() if k not in {"__Secure-1PSID", "__Secure-1PSIDTS"}
    }

    client = GeminiClient(
        secure_1psid=psid,
        secure_1psidts=psidts or "",
        cookies=extra or None,
        proxy=args.proxy,
        account_index=args.account_index,
        verify=not args.skip_verify,
    )
    return client, json_cookies


async def _init_client(args):
    if args.verbose:
        set_log_level("DEBUG")
    else:
        set_log_level("WARNING")
    client, json_cookies = _build_client(args)
    timeout = getattr(args, "request_timeout", 300)

    try:
        await client.init(
            timeout=timeout,
            auto_refresh=False,
            verbose=args.verbose,
        )
        return client, json_cookies
    except AuthError as e:
        raise SystemExit(
            f"Authentication failed: {e}\nPlease re-export cookies from your browser."
        ) from e


async def _cleanup(client, args, json_cookies):
    if args.cookies_json and not args.no_persist:
        _persist_cookies(
            args.cookies_json,
            json_cookies,
            client.cookies,
            verbose=args.verbose,
        )
    await client.close()


# ---------------------------------------------------------------------------
# region - Output helpers
# ---------------------------------------------------------------------------


def _print_images(output):
    if not output or not output.images:
        return
    web = [i for i in output.images if isinstance(i, WebImage)]
    gen = [i for i in output.images if isinstance(i, GeneratedImage)]
    if web:
        print("\n---\nImages:")
        for img in web:
            print(f"  {img.url}  {img.title or ''}")
    if gen:
        print("\n---\nGenerated images:")
        for img in gen:
            print(f"  {img.url}")


def _print_chat_id(output):
    if output and output.metadata:
        cid = output.metadata[0] if output.metadata else None
        if cid:
            print(f"\n---\nChat ID: {cid}")


# ---------------------------------------------------------------------------
# region - Subcommand implementations
# ---------------------------------------------------------------------------


async def cmd_ask(args):
    client, json_cookies = await _init_client(args)
    try:
        files = [args.image] if getattr(args, "image", None) else None
        model = args.model
        if args.no_stream:
            output = await client.generate_content(
                args.prompt,
                files=files,
                model=model,
            )
            print(output.text)
            _print_images(output)
            _print_chat_id(output)
        else:
            output = None
            async for output in client.generate_content_stream(
                args.prompt,
                files=files,
                model=model,
            ):
                if output.text_delta:
                    print(output.text_delta, end="", flush=True)
            if output:
                print()
                _print_images(output)
                _print_chat_id(output)
        return 0
    finally:
        await _cleanup(client, args, json_cookies)


async def cmd_reply(args):
    client, json_cookies = await _init_client(args)
    try:
        latest = await client.fetch_latest_chat_response(args.chat_id)
        if latest:
            chat = client.start_chat(
                metadata=list(latest.metadata),
                cid=args.chat_id,
                rcid=latest.rcid,
                model=args.model,
            )
        else:
            chat = client.start_chat(
                cid=args.chat_id,
                model=args.model,
            )

        if args.no_stream:
            output = await chat.send_message(args.prompt)
            print(output.text)
            _print_images(output)
        else:
            output = None
            async for output in chat.send_message_stream(args.prompt):
                if output.text_delta:
                    print(output.text_delta, end="", flush=True)
            if output:
                print()
                _print_images(output)

        print(f"\n---\nChat ID: {args.chat_id}")
        return 0
    finally:
        await _cleanup(client, args, json_cookies)


async def cmd_research_send(args):
    client, json_cookies = await _init_client(args)
    try:
        # The plan and its confirmation are two turns of one conversation. They must share a
        # session, or the confirmation turn is sent without the model the plan was made with
        # and Gemini rejects it as inconsistent with the history.
        chat = client.start_chat(model=args.model)

        plan = await client.create_deep_research_plan(prompt=args.prompt, chat=chat)
        if not plan.cid:
            raise SystemExit("Deep research failed: no chat ID.")

        await client.start_deep_research(plan=plan, chat=chat)

        print("Deep Research task submitted\n")
        if plan.title:
            print(f"  Title:   {plan.title}")
        if plan.eta_text:
            print(f"  ETA:     {plan.eta_text}")
        if plan.steps:
            print("  Steps:")
            for step in plan.steps:
                print(f"    - {step}")
        print(f"\n  Chat ID: {plan.cid}")
        print(f"\n  Use 'research check {plan.cid}' to check")
        print(f"  Use 'research get {plan.cid}' to fetch result")
        return 0
    finally:
        await _cleanup(client, args, json_cookies)


async def cmd_research_check(args):
    cid = args.chat_id
    client, json_cookies = await _init_client(args)
    try:
        # A ready report is the only completion signal - Gemini creates no task entity to
        # ask for a progress state. Several turns are scanned because the plan and
        # confirmation replies are model turns too, and the report can attach behind them.
        history = await client.read_chat(cid, limit=10)
        if not history or not history.turns:
            print("  Status: in progress (no response yet)")
            return 0

        for turn in history.turns:
            document = turn.model_output.deep_research_document if turn.model_output else None
            if document and document.ready:
                print("  Status: completed")
                print(f"  Title:  {document.title}")
                print(f"  Report: {len(document.content)} chars, {len(document.sources)} sources")
                print(f"\n  Use 'research get {cid}' for the full report.")
                return 0

        print("  Status: in progress (the report has not been attached yet)")
        return 0
    finally:
        await _cleanup(client, args, json_cookies)


async def cmd_research_get(args):
    cid = args.chat_id
    client, json_cookies = await _init_client(args)
    try:
        latest = await client.fetch_latest_chat_response(cid)
        if not latest:
            raise SystemExit(f"No response for chat {cid}. Research may still run.")
        text = latest.text or ""
        output_file = getattr(args, "output", None)
        if output_file:
            p = Path(output_file)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
            print(f"Saved research result to {output_file}")
        else:
            print(text)
        return 0
    finally:
        await _cleanup(client, args, json_cookies)


async def cmd_models(args):
    """List the models this account discovered at initialization."""
    client, json_cookies = await _init_client(args)
    try:
        items = client.list_models()
        if not items:
            print("No models found.")
            return 0

        name_w = max(len("Name"), max(len(m.model_name) for m in items))
        disp_w = max(len("Display"), max(len(m.display_name) for m in items))
        print(f"{'Name':<{name_w}}  {'Display':<{disp_w}}  ID")
        print("-" * (name_w + disp_w + 22))
        for m in items:
            mark = "" if m.is_available else "  (unavailable)"
            print(f"{m.model_name:<{name_w}}  {m.display_name:<{disp_w}}  {m.model_id}{mark}")
        return 0
    finally:
        await _cleanup(client, args, json_cookies)


async def cmd_list(args):
    client, json_cookies = await _init_client(args)
    try:
        items = client.list_chats()
        if not items:
            print("No chats found.")
            return 0

        id_w = max(len("ID"), max(len(c.cid) for c in items))
        ti_w = max(len("Title"), max(len(c.title[:50]) for c in items))
        print(f"{'ID':<{id_w}}  {'Title':<{ti_w}}  Updated")
        print("-" * (id_w + ti_w + 12))
        for c in items:
            ts = datetime.fromtimestamp(c.timestamp).strftime("%Y-%m-%d %H:%M")
            print(f"{c.cid:<{id_w}}  {c.title[:50]:<{ti_w}}  {ts}")
        return 0
    finally:
        await _cleanup(client, args, json_cookies)


async def cmd_read(args):
    client, json_cookies = await _init_client(args)
    try:
        history = await client.read_chat(
            args.chat_id,
            limit=args.max_turns,
        )
        if not history or not history.turns:
            print(f"No turns for chat {args.chat_id}")
            return 1
        lines = []
        for i, turn in enumerate(history.turns, 1):
            role = turn.role.upper()
            lines.extend((f"--- message {i} ---", f"[{role}] {turn.text}", ""))
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


async def cmd_download(args):
    """Download a generated image using authenticated curl_cffi session."""
    json_cookies = {}
    if args.cookies_json:
        json_cookies, _ = _load_cookies_with_meta(args.cookies_json)

    from curl_cffi.requests import AsyncSession

    url = args.url
    # Append =s2048 for full-size if not already specified for googleusercontent.com images
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if host == "googleusercontent.com" or host.endswith(".googleusercontent.com"):
        last_segment = parsed.path.rsplit("/", 1)[-1]
        if "=" not in last_segment:
            url += "=s2048"

    output = args.output
    if not output:
        from hashlib import md5

        url_hash = md5(args.url.encode()).hexdigest()[:8]
        output = f"gemini-{url_hash}.png"

    async with AsyncSession(
        impersonate=BROWSER_TYPE,
        cookies=json_cookies,
        proxy=args.proxy,
        allow_redirects=CurlFollow.SAFE,
        http_version=CurlHttpVersion.NONE,
    ) as session:
        resp = await session.get(url)
        if resp.status_code != 200:
            raise SystemExit(f"Download failed: HTTP {resp.status_code}")
        ct = resp.headers.get("content-type", "")
        if "image" not in ct and "octet" not in ct:
            raise SystemExit(f"Unexpected content-type: {ct}")
        p = Path(output)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(resp.content)
        size_kb = len(resp.content) / 1024
        print(f"Saved to {output} ({size_kb:.1f} KB)")

    return 0


async def cmd_inspect(args):
    """Report the account state the client already gathered during init()."""
    client, json_cookies = await _init_client(args)
    try:
        status = client.account_status
        print("=== Account Diagnostics ===\n")
        print(f"  Status:  {status.name} ({status.value})")
        print(f"           {status.description}")

        abuse = client.abuse_status
        if abuse is None:
            print("\n  Abuse status:  (not reported)")
        elif abuse.get("is_clean"):
            print("\n  Abuse status:  clean")
        else:
            print(
                f"\n  Abuse status:  FLAGGED code={abuse.get('status_code')} "
                f"signal={abuse.get('signal')}"
            )

        if usage := client.usage_info:
            tier = usage.get("tier", {})
            print(f"\n  Plan tier:  {tier.get('label') or '?'} ({tier.get('id')})")
            for key in ("current_5h", "weekly"):
                if metric := usage.get(key):
                    reset_at = metric.get("reset_at")
                    resets = f" (resets {reset_at})" if reset_at else ""
                    print(
                        f"    {metric['window']:<8} {metric.get('usage_percentage')}% used, "
                        f"{metric.get('remaining_credits')} credits left{resets}"
                    )
            if (credits := usage.get("ai_credits_remaining")) is not None:
                print(f"    {'credits':<8} {credits} AI credits remaining")

        print("\n  Quotas:")
        for quota_id, quota in client.quotas.items():
            if quota_id in ("extra", "usage_info"):
                continue
            print(
                f"    {quota.get('label', quota_id):<28} "
                f"{quota.get('remaining')}/{quota.get('total')} remaining "
                f"({quota.get('usage_percentage')}% used)"
            )
        if extra := client.quotas.get("extra", {}).get("default", {}):
            state = "BLOCKED" if extra.get("is_blocked") else "ok"
            print(f"    {'extra features':<28} {state} ({extra.get('usage_percentage')}% used)")

        models = client.list_models() or []
        print(f"\n  Models discovered:  {len(models)}")
        for m in models:
            print(f"    {'*' if m.is_available else '-'} {m.model_name}")

        print()
        return 0
    finally:
        await _cleanup(client, args, json_cookies)


# ---------------------------------------------------------------------------
# region - Argparse
# ---------------------------------------------------------------------------


def build_parser():
    parser = argparse.ArgumentParser(
        description="CLI for gemini-webapi",
    )
    parser.add_argument(
        "--cookies-json",
        default=None,
        help="Path to JSON cookie file",
    )
    parser.add_argument(
        "--proxy",
        default=(
            os.getenv("HTTPS_PROXY")
            or os.getenv("https_proxy")
            or os.getenv("HTTP_PROXY")
            or os.getenv("http_proxy")
        ),
    )
    parser.add_argument(
        "--account-index",
        type=int,
        default=None,
        help="Google account index",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Model name, alias or id (see the 'models' command). Defaults to the account's default",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )
    parser.add_argument(
        "--no-persist",
        action="store_true",
        help="Do not write updated cookies back",
    )
    parser.add_argument(
        "--request-timeout",
        type=float,
        default=300,
        help="Per-request HTTP timeout in seconds",
    )
    parser.add_argument(
        "--skip-verify",
        action="store_true",
        help="Skip SSL certificate verification",
    )

    sub = parser.add_subparsers(dest="command")

    # ask
    p_ask = sub.add_parser("ask", help="Single-turn question")
    p_ask.add_argument("prompt", help="Prompt text")
    p_ask.add_argument("--no-stream", action="store_true")
    p_ask.add_argument("--image", default=None)

    # reply
    p_reply = sub.add_parser("reply", help="Continue chat")
    p_reply.add_argument("chat_id", help="Chat ID (c_...)")
    p_reply.add_argument("prompt", help="Prompt text")
    p_reply.add_argument("--no-stream", action="store_true")

    # research
    p_res = sub.add_parser("research", help="Deep research")
    res_sub = p_res.add_subparsers(dest="research_command")
    p_rs = res_sub.add_parser("send", help="Submit task")
    p_rs.add_argument("--prompt", required=True)
    p_rc = res_sub.add_parser("check", help="Check progress")
    p_rc.add_argument("chat_id")
    p_rg = res_sub.add_parser("get", help="Get result")
    p_rg.add_argument("chat_id")
    p_rg.add_argument("--output", default=None)

    # list
    sub.add_parser("list", help="List chats")

    # read
    p_read = sub.add_parser("read", help="Read chat")
    p_read.add_argument("chat_id")
    p_read.add_argument("--max-turns", type=int, default=30)
    p_read.add_argument("--output", default=None)

    # models
    sub.add_parser("models", help="List the models available to this account")

    # download
    p_dl = sub.add_parser("download", help="Download image")
    p_dl.add_argument("url", help="Image URL")
    p_dl.add_argument("--output", "-o", default=None)

    # inspect
    sub.add_parser("inspect", help="Account probe")

    return parser


# ---------------------------------------------------------------------------
# region - Dispatch
# ---------------------------------------------------------------------------


async def run(args):
    cmd = args.command
    if cmd == "ask":
        return await cmd_ask(args)
    if cmd == "download":
        return await cmd_download(args)
    if cmd == "inspect":
        return await cmd_inspect(args)
    if cmd == "list":
        return await cmd_list(args)
    if cmd == "models":
        return await cmd_models(args)
    if cmd == "read":
        return await cmd_read(args)
    if cmd == "reply":
        return await cmd_reply(args)
    if cmd == "research":
        rc = getattr(args, "research_command", None)
        if rc == "send":
            return await cmd_research_send(args)
        if rc == "check":
            return await cmd_research_check(args)
        if rc == "get":
            return await cmd_research_get(args)
        raise SystemExit("Usage: research {send|check|get}")
    raise SystemExit("Usage: cli.py {ask|reply|research|list|read|models|download|inspect}")


def main():
    parser = build_parser()
    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return 1
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
