import re
import reprlib
from typing import Any

import orjson as json

from .logger import logger

_LENGTH_MARKER_PATTERN = re.compile(r"(\d+)\n")


def get_nested_value(
    data: Any, path: list[int | str], default: Any = None, verbose: bool = False
) -> Any:
    """
    Safely navigate through a nested structure (list or dict) using a sequence of keys/indices.

    Args:
        data: The nested structure to traverse.
        path: A list of indices or keys representing the path.
        default: Value to return if the path is invalid.
        verbose: If True, log debug information when the path cannot be fully traversed.
    """
    current = data

    for i, key in enumerate(path):
        found = False
        if isinstance(key, int):
            if isinstance(current, list) and 0 <= key < len(current):
                current = current[key]
                found = True
        elif isinstance(key, str):
            if isinstance(current, dict) and key in current:
                current = current[key]
                found = True

        if not found:
            if verbose:
                logger.debug(
                    f"Safe navigation: path {path} ended at index {i} (key '{key}'), "
                    f"returning default. Context: {reprlib.repr(current)}"
                )
            return default

    return current if current is not None else default


def _parse_with_length_markers(content: str) -> list | None:
    """
    Parse streaming responses using length markers as hints.
    Google's format: [length]\n[json_payload]\n
    The length value includes the newline after the number and the newline after the JSON.
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

        length_val = match.group(1)
        length = int(length_val)

        # Content starts immediately after the digits
        start_content = match.start() + len(length_val)
        end_hint = start_content + length
        pos = end_hint

        if end_hint > total_len:
            logger.debug(
                f"Chunk at pos {start_content} is truncated. Expected {length} chars."
            )
            break

        chunk = content[start_content:end_hint].strip()
        if not chunk:
            continue

        try:
            parsed = json.loads(chunk)
            if isinstance(parsed, list):
                collected_chunks.extend(parsed)
            else:
                collected_chunks.append(parsed)
        except json.JSONDecodeError:
            logger.warning(
                f"Failed to parse chunk at pos {start_content} with length {length}. "
                f"Snippet: {reprlib.repr(chunk)}"
            )

    return collected_chunks if collected_chunks else None


def extract_json_from_response(text: str) -> list:
    """Extract and normalize JSON content from a Google API response."""
    if not isinstance(text, str):
        raise TypeError(
            f"Input text is expected to be a string, got {type(text).__name__} instead."
        )

    content = text.strip()
    if content.startswith(")]}'"):
        content = content[4:].lstrip()

    result = _parse_with_length_markers(content)
    if result is not None:
        return result

    try:
        parsed = json.loads(content)
        return parsed if isinstance(parsed, list) else [parsed]
    except json.JSONDecodeError:
        pass

    collected_lines = []
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue

        if isinstance(parsed, list):
            collected_lines.extend(parsed)
        elif isinstance(parsed, dict):
            collected_lines.append(parsed)

    if collected_lines:
        return collected_lines

    raise ValueError("Could not find a valid JSON object or array in the response.")
