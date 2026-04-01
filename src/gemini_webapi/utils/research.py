import re
from typing import Any

from .parsing import get_nested_value

_RESEARCH_ID_RE = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)
_CHAT_ID_RE = re.compile(r"\bc_[A-Za-z0-9_]+\b")
_URL_RE = re.compile(r"^https?://")


def _iter_nested(data: Any):
    yield data
    if isinstance(data, list):
        for item in data:
            yield from _iter_nested(item)
    elif isinstance(data, dict):
        for item in data.values():
            yield from _iter_nested(item)


def _find_first_match(data: Any, pattern: re.Pattern[str]) -> str | None:
    for item in _iter_nested(data):
        if isinstance(item, str):
            match = pattern.search(item)
            if match:
                return match.group(0)
    return None


def _find_first_string(data: Any, *, exclude: set[str] | None = None) -> str | None:
    exclude = exclude or set()
    for item in _iter_nested(data):
        if isinstance(item, str) and item and item not in exclude:
            return item
    return None


def _extract_research_id(data: Any) -> str | None:
    return _find_first_match(data, _RESEARCH_ID_RE)


def _extract_chat_id(data: Any) -> str | None:
    return _find_first_match(data, _CHAT_ID_RE)


def _collect_research_notes(data: Any, *, exclude: set[str] | None = None) -> list[str]:
    exclude = exclude or set()
    notes: list[str] = []
    seen: set[str] = set()

    for item in _iter_nested(data):
        if not isinstance(item, str):
            continue
        text = item.strip()
        if (
            not text
            or text in exclude
            or text in seen
            or _URL_RE.match(text)
            or len(text) < 12
        ):
            continue
        seen.add(text)
        notes.append(text)
        if len(notes) >= 12:
            break

    return notes


def _find_first_dict_key(data: Any, key: str) -> dict[str, Any] | None:
    for item in _iter_nested(data):
        if isinstance(item, dict) and key in item:
            return item
    return None


def extract_deep_research_plan(
    candidate_data: list, fallback_text: str = ""
) -> dict[str, Any] | None:
    meta_dict = None
    payload = None

    for key in ("56", "57"):
        meta_dict = _find_first_dict_key(candidate_data, key)
        if meta_dict and isinstance(meta_dict.get(key), list):
            payload = meta_dict[key]
            break

    if meta_dict is None or payload is None:
        return None

    research_id = _extract_research_id(candidate_data)

    title = get_nested_value(payload, [0])
    steps_payload = get_nested_value(payload, [1], [])
    steps: list[str] = []
    if isinstance(steps_payload, list):
        for step in steps_payload:
            if isinstance(step, list):
                label = step[1] if len(step) > 1 and isinstance(step[1], str) else None
                body = step[2] if len(step) > 2 and isinstance(step[2], str) else None
                if label and body:
                    steps.append(f"{label}: {body}")
                elif body:
                    steps.append(body)
                elif label:
                    steps.append(label)

    modify_payload = get_nested_value(payload, [5])
    modify_prompt = None
    if isinstance(modify_payload, list):
        modify_prompt = _find_first_string(modify_payload)

    query = (
        get_nested_value(payload, [1, 0, 2])
        if isinstance(get_nested_value(payload, [1, 0, 2]), str)
        else None
    )
    eta_text = (
        get_nested_value(payload, [2])
        if isinstance(get_nested_value(payload, [2]), str)
        else None
    )
    confirm_prompt = (
        get_nested_value(payload, [3, 0])
        if isinstance(get_nested_value(payload, [3, 0]), str)
        else None
    )
    confirmation_url = (
        get_nested_value(payload, [4, 0])
        if isinstance(get_nested_value(payload, [4, 0]), str)
        else None
    )
    raw_state = meta_dict.get("70") if isinstance(meta_dict.get("70"), int) else None

    if not any(
        [
            title if isinstance(title, str) else None,
            query,
            steps,
            eta_text,
            confirm_prompt,
            confirmation_url,
            modify_prompt,
        ]
    ):
        return None

    return {
        "research_id": research_id,
        "title": title if isinstance(title, str) else None,
        "query": query,
        "steps": steps,
        "eta_text": eta_text,
        "confirm_prompt": confirm_prompt,
        "confirmation_url": confirmation_url,
        "modify_prompt": modify_prompt,
        "raw_state": raw_state,
        "response_text": fallback_text or None,
    }


def extract_deep_research_status_payload(
    payload: list | dict | str,
) -> dict[str, Any] | None:
    data = (
        payload[0]
        if isinstance(payload, list) and payload and isinstance(payload[0], list)
        else payload
    )
    research_id = _extract_research_id(data)
    if not research_id:
        return None

    title = get_nested_value(data, [1, 4, 0])
    query = get_nested_value(data, [1, 4, 1])
    cid = get_nested_value(data, [1, 3, 0]) or _extract_chat_id(data)
    raw_state = None
    meta_dict = _find_first_dict_key(data, "70")
    if meta_dict and isinstance(meta_dict.get("70"), int):
        raw_state = meta_dict["70"]

    marker_strings = [
        item for item in _iter_nested(data) if isinstance(item, str) and item
    ]
    done = any("immersive_entry_chip" in item for item in marker_strings)
    awaiting_confirmation = any(
        "deep_research_confirmation_content" in item for item in marker_strings
    )

    state = (
        "completed"
        if done
        else "awaiting_confirmation" if awaiting_confirmation else "running"
    )
    exclude = {s for s in [title, query, research_id, cid] if isinstance(s, str)}
    notes = _collect_research_notes(data, exclude=exclude)

    return {
        "research_id": research_id,
        "state": state,
        "title": title if isinstance(title, str) else None,
        "query": query if isinstance(query, str) else None,
        "cid": cid if isinstance(cid, str) else None,
        "notes": notes,
        "done": done,
        "raw_state": raw_state,
        "raw": payload,
    }
