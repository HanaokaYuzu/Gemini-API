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
                f"Safe navigation stopped at index {i} (key '{key}') in path {path}. "
                f"Returning default. Context: {reprlib.repr(current)}"
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

    Uses regex to identify JSON strings and avoids modifying newlines used for
    formatting or structure outside of strings.
    """
    if "\n" not in text:
        return text

    def replacer(match):
        return match.group(0).replace("\n", "\\n")

    return _JSON_STRING_PATTERN.sub(replacer, text)


def _parse_with_length_markers(content: str) -> list | None:
    """Parse streaming responses using the length-marker format."""
    pos = 0
    total_len = len(content)
    collected_chunks = []

    while pos < total_len:
        while pos < total_len and content[pos].isspace():
            pos += 1

        if pos >= total_len:
            break

        match = _LENGTH_MARKER_PATTERN.match(content, pos=pos)
        if match:
            length = int(match.group(1))
            start_content = match.end()
            pos = start_content + length

            chunk = content[start_content:pos]
            sanitized = _sanitize_json_newlines(chunk)
            try:
                parsed = json.loads(sanitized)
                collected_chunks.extend(_maybe_unwrap(parsed))
                continue
            except json.JSONDecodeError:
                logger.warning(
                    f"Failed to parse chunk of length {length}. "
                    f"Snippet: {reprlib.repr(sanitized)}"
                )
                continue
        break

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
