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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "CLI for gemini-webapi. Reads all cookies from --cookies-json "
            "and auto-persists response cookies (SIDCC etc.) back after each run. "
            "No manual cookie rotation needed."
        )
    )
    parser.add_argument("--prompt", required=False, help="Research prompt")
    parser.add_argument(
        "--output",
        required=False,
        help="Markdown file path to write the captured deep research result",
    )
    parser.add_argument(
        "--secure-1psid",
        default=None,
        help="Google __Secure-1PSID cookie (or set GEMINI_SECURE_1PSID)",
    )
    parser.add_argument(
        "--secure-1psidts",
        default=None,
        help="Google __Secure-1PSIDTS cookie (or set GEMINI_SECURE_1PSIDTS)",
    )
    parser.add_argument(
        "--cookie",
        action="append",
        default=[],
        help=(
            "Extra cookie in name=value format (can be provided multiple times). "
            "Only needed for debugging special cases; not required in normal flow."
        ),
    )
    parser.add_argument(
        "--cookies-json",
        default=None,
        help=(
            "Path to JSON cookie file. All cookies are loaded and used; "
            "response Set-Cookie values are persisted back automatically."
        ),
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
        "--model",
        default=Model.UNSPECIFIED.model_name,
        help="Model name, default: unspecified (auto by account)",
    )
    parser.add_argument(
        "--account-index",
        type=int,
        default=None,
        help="Google account index in multi-login session (e.g. 2 => /u/2)",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=15,
        help="Seconds between deep research status polls",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=1800,
        help="Overall wait timeout in seconds",
    )
    parser.add_argument(
        "--request-timeout",
        type=float,
        default=300,
        help="Per-request HTTP timeout in seconds",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )
    parser.add_argument(
        "--inspect-account",
        action="store_true",
        help="Only probe account capability RPCs and print JSON",
    )
    parser.add_argument(
        "--list-chats",
        action="store_true",
        help="List chat history summaries",
    )
    parser.add_argument(
        "--list-cursor",
        default=None,
        help="Pagination cursor for --list-chats",
    )
    parser.add_argument(
        "--chat-id",
        default=None,
        help="Read one chat by id (e.g. c_xxx)",
    )
    parser.add_argument(
        "--max-turns",
        type=int,
        default=30,
        help="Max turns to fetch for --chat-id",
    )
    parser.add_argument(
        "--raw",
        action="store_true",
        help="Include raw turn payload for --chat-id",
    )
    parser.add_argument(
        "--inspect-cookies",
        action="store_true",
        help="Print parsed cookie expiry metadata (from --cookies-json) and exit",
    )
    parser.add_argument(
        "--no-persist",
        action="store_true",
        help="Do not write updated cookies back to --cookies-json",
    )
    return parser


def _parse_expiry(value):
    if value is None:
        return None

    if isinstance(value, (int, float)):
        return int(value)

    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None

        # Numeric string epoch
        try:
            return int(float(raw))
        except ValueError:
            pass

        # ISO-8601 (e.g. 2027-03-12T21:16:56.548Z)
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return int(dt.timestamp())
        except ValueError:
            pass

        # HTTP-date style
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

    # {"cookies": {name: value, ...}} (flat dict, written by --persist)
    if isinstance(data, dict) and isinstance(data.get("cookies"), dict):
        inner = data["cookies"]
        if all(isinstance(k, str) and isinstance(v, str) for k, v in inner.items()):
            for k, v in inner.items():
                _upsert(k, v)
            return cookies, meta

    # {"cookies": [{name, value, expirationDate?...}, ...]}
    if isinstance(data, dict) and isinstance(data.get("cookies"), list):
        for item in data["cookies"]:
            if isinstance(item, dict):
                _handle_cookie_obj(item)
        if cookies:
            return cookies, meta

    # [{name, value, expirationDate?...}, ...]
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                _handle_cookie_obj(item)
        if cookies:
            return cookies, meta

    raise SystemExit(
        "--cookies-json unsupported format. Expected {name:value}, {'cookies':[...]} or [...]."
    )


def _cookie_expiry_from_jar(cookie_jar, name: str) -> dict:
    candidates = []
    try:
        for c in cookie_jar.jar:
            if getattr(c, "name", None) == name:
                candidates.append(c)
    except Exception:
        return {"found": False, "expires_epoch": None, "expires_iso": None}

    if not candidates:
        return {"found": False, "expires_epoch": None, "expires_iso": None}

    expires_values = [getattr(c, "expires", None) for c in candidates]
    expires_values = [v for v in expires_values if isinstance(v, (int, float))]
    if not expires_values:
        return {"found": True, "expires_epoch": None, "expires_iso": None}

    exp = int(max(expires_values))
    return {
        "found": True,
        "expires_epoch": exp,
        "expires_iso": datetime.fromtimestamp(exp, tz=timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
    }



def _analyze_expiry_group(
    meta: dict[str, dict], names: list[str], present_names: set[str] | None = None
) -> dict:
    present_names = present_names or set()

    expires = {}
    for name in names:
        epoch = (meta.get(name) or {}).get("expires_epoch")
        if isinstance(epoch, (int, float)):
            expires[name] = int(epoch)

    present_without_expiry = [
        n for n in names if n in present_names and n not in expires
    ]

    if not expires:
        return {
            "names": names,
            "present_with_expiry": [],
            "present_without_expiry": present_without_expiry,
            "missing": [n for n in names if n not in present_names],
            "spread_seconds": None,
            "reference_expires_iso": None,
        }

    values = list(expires.values())
    ref = max(values)
    return {
        "names": names,
        "present_with_expiry": sorted(expires.keys()),
        "present_without_expiry": present_without_expiry,
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


def _cookie_expiry_diagnostics(
    meta: dict[str, dict], present_names: set[str] | None = None
) -> dict:
    ts_group_names = ["__Secure-1PSIDTS", "__Secure-3PSIDTS"]
    cc_group_names = ["SIDCC", "__Secure-1PSIDCC", "__Secure-3PSIDCC"]

    ts_group = _analyze_expiry_group(meta, ts_group_names, present_names=present_names)
    cc_group = _analyze_expiry_group(meta, cc_group_names, present_names=present_names)

    ts_ref = None
    cc_ref = None
    if ts_group.get("reference_expires_iso"):
        ts_ref = max(
            [
                int((meta.get(n) or {}).get("expires_epoch"))
                for n in ts_group_names
                if isinstance((meta.get(n) or {}).get("expires_epoch"), (int, float))
            ],
            default=None,
        )
    if cc_group.get("reference_expires_iso"):
        cc_ref = max(
            [
                int((meta.get(n) or {}).get("expires_epoch"))
                for n in cc_group_names
                if isinstance((meta.get(n) or {}).get("expires_epoch"), (int, float))
            ],
            default=None,
        )

    between = None
    if isinstance(ts_ref, int) and isinstance(cc_ref, int):
        between = cc_ref - ts_ref

    # Find cookies whose expiry is closest to __Secure-1PSIDTS.
    nearest = []
    one_ts = (meta.get("__Secure-1PSIDTS") or {}).get("expires_epoch")
    if isinstance(one_ts, (int, float)):
        one_ts = int(one_ts)
        pairs = []
        for name, m in meta.items():
            e = m.get("expires_epoch") if isinstance(m, dict) else None
            if not isinstance(e, (int, float)):
                continue
            if name == "__Secure-1PSIDTS":
                continue
            pairs.append((abs(int(e) - one_ts), name, int(e)))
        pairs.sort(key=lambda x: (x[0], x[1]))
        nearest = [
            {
                "name": name,
                "delta_seconds": delta,
                "expires_iso": datetime.fromtimestamp(epoch, tz=timezone.utc)
                .isoformat()
                .replace("+00:00", "Z"),
            }
            for delta, name, epoch in pairs[:8]
        ]

    return {
        "ts_group": ts_group,
        "cc_group": cc_group,
        "cc_minus_ts_seconds": between,
        "nearest_to_1psidts": nearest,
    }


def _serialize_model_output(output):
    if not output:
        return None
    return {
        "metadata": list(output.metadata),
        "rcid": output.rcid,
        "text": output.text,
        "candidate_count": len(output.candidates),
    }


def render_markdown(result) -> str:
    plan = result.plan
    lines = [
        "# Gemini Deep Research",
        "",
        f"- Research ID: `{plan.research_id}`",
        f"- Chat ID: `{plan.cid or ''}`",
        f"- Done: `{result.done}`",
        "",
        "## Plan",
        "",
    ]

    if plan.title:
        lines.extend([f"**Title**: {plan.title}", ""])
    if plan.eta_text:
        lines.extend([f"**ETA**: {plan.eta_text}", ""])
    if plan.response_text:
        lines.extend(["### Confirmation message", "", plan.response_text, ""])
    if plan.steps:
        lines.append("### Steps")
        lines.append("")
        for step in plan.steps:
            lines.append(f"- {step}")
        lines.append("")

    if result.start_output:
        lines.extend([
            "## Start response",
            "",
            result.start_output.text,
            "",
        ])

    if result.statuses:
        lines.extend(["## Status snapshots", ""])
        for i, status in enumerate(result.statuses, 1):
            lines.append(f"### {i}. {status.state}")
            lines.append("")
            if status.notes:
                for note in status.notes[:6]:
                    lines.append(f"- {note}")
            else:
                lines.append("- (no parsed notes)")
            lines.append("")

    lines.extend(["## Final response", ""])
    if result.final_output:
        lines.append(result.final_output.text)
    else:
        lines.append("(No final output captured)")
    lines.append("")
    return "\n".join(lines)


def _persist_cookies(
    cookies_json_path: str | Path,
    original_cookies: dict[str, str],
    client_cookies,
    verbose: bool = False,
) -> None:
    """Merge original cookies with any Set-Cookie updates from the client and write back."""
    merged = dict(original_cookies)

    # Apply updates from httpx cookie jar (response Set-Cookie values)
    try:
        for cookie in client_cookies.jar:
            name = getattr(cookie, "name", None)
            value = getattr(cookie, "value", None)
            if isinstance(name, str) and isinstance(value, str) and value:
                merged[name] = value
    except Exception:
        pass

    # Check if anything actually changed
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


async def run(args: argparse.Namespace) -> int:
    if args.verbose:
        set_log_level("DEBUG")

    if args.proxy:
        logger.info(f"Proxy enabled: {args.proxy}")
    else:
        logger.info("Proxy disabled")

    # --- Load cookies ---
    json_cookies: dict[str, str] = {}
    json_cookie_meta: dict[str, dict] = {}
    if args.cookies_json:
        json_cookies, json_cookie_meta = _load_cookies_with_meta(args.cookies_json)

    # CLI args and env vars override cookies.json values
    secure_1psid = (
        args.secure_1psid
        or json_cookies.get("__Secure-1PSID")
        or os.getenv("GEMINI_SECURE_1PSID")
    )
    secure_1psidts = (
        args.secure_1psidts
        or json_cookies.get("__Secure-1PSIDTS")
        or os.getenv("GEMINI_SECURE_1PSIDTS")
    )

    if args.verbose:
        logger.debug(f"cookie __Secure-1PSID: present={bool(secure_1psid)}")
        logger.debug(f"cookie __Secure-1PSIDTS: present={bool(secure_1psidts)}")
        if json_cookies:
            logger.debug(f"cookies-json keys: {sorted(json_cookies.keys())}")

    if args.inspect_cookies:
        report = {
            "cookies_json": str(args.cookies_json) if args.cookies_json else None,
            "required": {
                "__Secure-1PSID": {
                    "present": bool(secure_1psid),
                    **json_cookie_meta.get("__Secure-1PSID", {}),
                },
                "__Secure-1PSIDTS": {
                    "present": bool(secure_1psidts),
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

    if not secure_1psid:
        raise SystemExit(
            "Missing required cookie: __Secure-1PSID. "
            "Please export cookies from browser and provide via --cookies-json."
        )

    if not secure_1psidts:
        logger.warning(
            "__Secure-1PSIDTS not found. Session may still work with long-lived cookies."
        )

    # Build extra cookies: everything from cookies.json except 1PSID/1PSIDTS
    # (those are passed as named params to GeminiClient)
    extra_cookies: dict[str, str] = {}
    for k, v in json_cookies.items():
        if k not in {"__Secure-1PSID", "__Secure-1PSIDTS"}:
            extra_cookies[k] = v

    # --cookie overrides
    for item in args.cookie or []:
        if "=" not in item:
            raise SystemExit(f"Invalid --cookie value: {item!r}, expected name=value")
        name, value = item.split("=", 1)
        name = name.strip()
        if not name:
            raise SystemExit(f"Invalid --cookie name in: {item!r}")
        extra_cookies[name] = value

    # --- Create client with ALL cookies ---
    client = GeminiClient(
        secure_1psid=secure_1psid,
        secure_1psidts=secure_1psidts or "",
        cookies=extra_cookies or None,
        proxy=args.proxy,
        account_index=args.account_index,
    )

    await client.init(timeout=args.request_timeout, verbose=args.verbose)

    if args.verbose:
        for name in ("__Secure-1PSID", "__Secure-1PSIDTS"):
            info = _cookie_expiry_from_jar(client.cookies, name)
            if not info["found"]:
                logger.debug(f"post-init jar: {name} not found")
            elif info["expires_epoch"] is None:
                logger.debug(
                    f"post-init jar: {name} found but expires is unavailable"
                )
            else:
                left_days = (
                    info["expires_epoch"]
                    - int(datetime.now(tz=timezone.utc).timestamp())
                ) / 86400
                logger.debug(
                    f"post-init jar: {name} expires_at={info['expires_iso']} (in {left_days:.2f} days)"
                )

    try:
        if args.inspect_account:
            snapshot = await client.inspect_account_status()
            print(json.dumps(snapshot, ensure_ascii=False, indent=2))
            return 0

        if args.list_chats:
            listing = await client.list_chats(cursor=args.list_cursor)
            print(json.dumps(listing, ensure_ascii=False, indent=2))
            err = str(listing.get("error") or "")
            if "code=7" in err:
                raise SystemExit(
                    "LIST_CHATS rejected with code=7. Please refresh cookies from browser."
                )
            return 0

        if args.chat_id:
            latest = await client.fetch_latest_chat_response(args.chat_id)
            turns = await client.read_chat(args.chat_id, max_turns=args.max_turns)
            raw_turns = None
            if args.raw:
                raw_turns = await client.read_chat_raw(
                    args.chat_id,
                    max_turns=args.max_turns,
                )

            payload = {
                "cid": args.chat_id,
                "latest": _serialize_model_output(latest),
                "turns": [turn.model_dump(mode="json") for turn in turns],
            }
            if args.raw:
                payload["raw_turns"] = raw_turns

            data = json.dumps(payload, ensure_ascii=False, indent=2)
            if args.output:
                output_path = Path(args.output)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(data, encoding="utf-8")
                print(f"Saved chat snapshot to {output_path}")
            else:
                print(data)

            if not latest and not turns and raw_turns is None:
                raise SystemExit(
                    "READ_CHAT returned no data (likely reject_code=7). "
                    "Please refresh cookies from browser."
                )
            return 0

        snapshot = await client.inspect_account_status()

        # Fast permission gate before running deep research workflow
        rpc = snapshot.get("rpc", {})
        critical = ["activity", "model_state", "caps"]
        rejected = [
            name
            for name in critical
            if isinstance(rpc.get(name), dict) and rpc[name].get("reject_code") == 7
        ]
        if len(rejected) >= 2:
            raise SystemExit(
                "Deep research permission check failed (reject_code=7): "
                + ", ".join(rejected)
            )

        summary = snapshot.get("summary", {})
        if summary.get("deep_research_rate_limited"):
            raise SystemExit(
                "Deep research rate limit reached for current account/session. "
                "Please wait for reset time shown in Gemini UI."
            )

        if not args.prompt or not args.output:
            raise SystemExit(
                "--prompt and --output are required unless --inspect-account/--list-chats/--chat-id is used"
            )

        result = await client.deep_research(
            prompt=args.prompt,
            model=args.model,
            poll_interval=args.poll_interval,
            timeout=args.timeout,
        )
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(render_markdown(result), encoding="utf-8")
        print(f"Saved deep research result to {output_path}")
        return 0
    finally:
        # Auto-persist updated cookies (SIDCC etc. from response Set-Cookie)
        if args.cookies_json and not args.no_persist:
            _persist_cookies(
                args.cookies_json, json_cookies, client.cookies,
                verbose=args.verbose,
            )
        await client.close()


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
