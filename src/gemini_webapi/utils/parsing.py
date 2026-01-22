import re
import reprlib
from typing import Any

import orjson as json

from .logger import logger

_JSON_STRING_PATTERN = re.compile(r'("(?:[^"\\]|\\.)*")')
_LENGTH_MARKER_PATTERN = re.compile(r"(\d+)\n")


def get_nested_value(data: Any, path: list[int | str], default: Any = None) -> Any:
    """
    Safely navigate through a nested structure (list or dict) using a sequence of keys/indices.

    Args:
        data: The nested structure to traverse.
        path: A list of indices or keys representing the path.
        default: Value to return if the path is invalid.
    """
    current = data

    for i, key in enumerate(path):
        try:
            current = current[key]
        except (IndexError, TypeError, KeyError):
            logger.debug(
                f"Safe navigation: path {path} ended at index {i} (key '{key}'), "
                f"returning default. Context: {reprlib.repr(current)}"
            )
            return default

    return current if current is not None else default


def _maybe_unwrap(parsed: Any) -> list:
    """Ensure the output is a list and unwrap single-element nested lists."""
    if isinstance(parsed, list):
        if len(parsed) == 1 and isinstance(parsed[0], list):
            return parsed[0]
        return parsed
    return [parsed]


def _sanitize_json_newlines(text: str) -> str:
    """
    Escape raw newlines inside JSON string tokens to prevent parsing errors.
    Uses fast regex substitution.
    """
    if "\n" not in text:
        return text

    def replacer(match):
        return match.group(0).replace("\n", "\\n")

    return _JSON_STRING_PATTERN.sub(replacer, text)


def _parse_with_length_markers(content: str) -> list | None:
    """
    Optimized streaming parser using length markers as hints with smart fast recovery.
    """
    pos = 0
    total_len = len(content)
    collected_chunks = []

    while pos < total_len:
        while pos < total_len and content[pos].isspace():
            pos += 1

        if pos >= total_len:
            break

        match = _LENGTH_MARKER_PATTERN.match(content, pos=pos)
        if not match:
            break

        length = int(match.group(1))
        start_content = match.end()
        end_hint = start_content + length

        opener = None
        for i in range(start_content, min(start_content + 10, total_len)):
            if not content[i].isspace():
                opener = content[i]
                break

        closer = "]" if opener == "[" else "}" if opener == "{" else None

        chunk = content[start_content:end_hint]
        try:
            parsed = json.loads(_sanitize_json_newlines(chunk))
            collected_chunks.extend(_maybe_unwrap(parsed))
            pos = end_hint
            continue
        except json.JSONDecodeError:
            pass

        if not closer:
            pos = start_content
            continue

        last_idx = chunk.rfind(closer)
        if last_idx != -1:
            sub_chunk = chunk[: last_idx + 1]
            try:
                parsed = json.loads(_sanitize_json_newlines(sub_chunk))
                collected_chunks.extend(_maybe_unwrap(parsed))
                pos = start_content + last_idx + 1
                continue
            except json.JSONDecodeError:
                pass

        search_limit = 1000
        search_area = content[end_hint : end_hint + search_limit]
        found_undershoot = False

        current_search_pos = 0
        while True:
            idx = search_area.find(closer, current_search_pos)
            if idx == -1:
                break

            test_end = end_hint + idx + 1
            test_chunk = content[start_content:test_end]
            try:
                parsed = json.loads(_sanitize_json_newlines(test_chunk))
                collected_chunks.extend(_maybe_unwrap(parsed))
                pos = test_end
                found_undershoot = True
                break
            except json.JSONDecodeError:
                current_search_pos = idx + 1

        if found_undershoot:
            continue

        logger.warning(
            f"Failed to parse chunk at pos {pos} with length {length}. "
            f"Snippet: {reprlib.repr(chunk)}"
        )
        pos = start_content

    return collected_chunks if collected_chunks else None


def extract_json_from_response(text: str) -> list:
    """
    Extract and normalize JSON content from a Google API response.

    Supports XSSI headers, length-marker streaming formats, and NDJSON fallbacks.
    """
    if not isinstance(text, str):
        raise TypeError(
            f"Input text is expected to be a string, got {type(text).__name__} instead."
        )

    content = text.strip()
    if content.startswith(")]}'"):
        content = content[4:].lstrip()

    # 1. Try length-marker parsing (Stream format)
    result = _parse_with_length_markers(content)
    if result is not None:
        return result

    # 2. Try parsing the whole body (Standard JSON)
    try:
        sanitized = _sanitize_json_newlines(content)
        parsed = json.loads(sanitized)
        return _maybe_unwrap(parsed)
    except json.JSONDecodeError:
        pass

    # 3. Fallback to line-by-line (NDJSON)
    collected_lines = []
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            try:
                parsed = json.loads(_sanitize_json_newlines(line))
            except json.JSONDecodeError:
                continue

        if isinstance(parsed, (dict, list)):
            collected_lines.extend(_maybe_unwrap(parsed))

    if collected_lines:
        return collected_lines

    raise ValueError("Could not find a valid JSON object or array in the response.")
