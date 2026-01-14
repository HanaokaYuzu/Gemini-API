from typing import Any

import orjson as json

from .logger import logger


def get_nested_value(data: list, path: list[int], default: Any = None) -> Any:
    """
    Safely get a value from a nested list by a sequence of indices.

    Parameters
    ----------
    data: `list`
        The nested list to traverse.
    path: `list[int]`
        A list of indices representing the path to the desired value.
    default: `Any`, optional
        The default value to return if the path is not found.
    """

    current = data

    for i, key in enumerate(path):
        try:
            current = current[key]
        except (IndexError, TypeError, KeyError):
            current_repr = repr(current)
            if len(current_repr) > 200:
                current_repr = f"{current_repr[:197]}..."

            logger.debug(
                f"Safe navigation: path {path} ended at index {i} (key '{key}'), "
                f"returning default. Context: {current_repr}"
            )

            return default

    if current is None and default is not None:
        return default

    return current


def _maybe_unwrap(parsed: list) -> list:
    """Unwrap if it's a list with a single list element."""
    if isinstance(parsed, list) and len(parsed) == 1 and isinstance(parsed[0], list):
        return parsed[0]
    return parsed


def _sanitize_json_newlines(text: str) -> str:
    """Sanitize newlines inside JSON strings.

    This function handles two cases:
    1. Raw newlines inside strings are replaced with \\n escape sequence
    2. \\n escape sequences inside strings are converted to \\\\n to preserve
       them as literal backslash+n (for compatibility with some data formats)

    JSON strings cannot contain raw newlines - they must be escaped.
    """
    result = []
    in_string = False
    i = 0

    while i < len(text):
        char = text[i]

        # Check for quote (need to count preceding backslashes to know if escaped)
        if char == '"':
            num_backslashes = 0
            j = len(result) - 1
            while j >= 0 and result[j] == '\\':
                num_backslashes += 1
                j -= 1
            # If odd number of backslashes before quote, it's escaped
            if num_backslashes % 2 == 0:
                in_string = not in_string
            result.append(char)
            i += 1
            continue

        # Check for backslash-n sequence inside string
        if in_string and char == '\\' and i + 1 < len(text) and text[i + 1] == 'n':
            # Convert \n to \\n to preserve as literal backslash+n
            result.append('\\\\n')
            i += 2
            continue

        # Check for raw newline inside string
        if in_string and char == '\n':
            # Replace with escaped newline
            result.append('\\n')
            i += 1
            continue

        result.append(char)
        i += 1

    return ''.join(result)


def _parse_with_length_markers(content: str) -> list | None:
    """Parse using Google RPC length-marker format."""
    import re

    pos = 0
    while pos < len(content):
        # Skip whitespace
        while pos < len(content) and content[pos] in ' \t\n':
            pos += 1
        if pos >= len(content):
            break

        # Try to match length marker
        match = re.match(r'(\d+)\n', content[pos:])
        if match:
            start = pos + match.end()
            # Try to parse JSON from this position (ignore the byte count from marker)
            remaining = content[start:]

            # Sanitize newlines inside strings before parsing
            sanitized = _sanitize_json_newlines(remaining)
            try:
                parsed = json.loads(sanitized)
                return _maybe_unwrap(parsed)
            except json.JSONDecodeError:
                # Try to find the end of a valid JSON chunk by incrementally parsing
                # Look for balanced brackets/braces
                if remaining.startswith('[') or remaining.startswith('{'):
                    bracket_count = 0
                    in_string = False
                    escape_next = False
                    for i, char in enumerate(remaining):
                        if escape_next:
                            escape_next = False
                            continue
                        if char == '\\' and in_string:
                            escape_next = True
                            continue
                        if char == '"' and not escape_next:
                            in_string = not in_string
                            continue
                        if not in_string:
                            if char in '[{':
                                bracket_count += 1
                            elif char in ']}':
                                bracket_count -= 1
                                if bracket_count == 0:
                                    chunk = remaining[:i+1]
                                    sanitized_chunk = _sanitize_json_newlines(chunk)
                                    try:
                                        parsed = json.loads(sanitized_chunk)
                                        return _maybe_unwrap(parsed)
                                    except json.JSONDecodeError:
                                        break
                # Move past this marker and try next
                pos = start
                continue
        else:
            break

    return None


def extract_json_from_response(text: str) -> list:
    """
    Clean and extract the JSON content from a Google API response.

    Parameters
    ----------
    text: `str`
        The raw response text from a Google API.

    Returns
    -------
    `list`
        The extracted JSON array or object (should be an array).

    Raises
    ------
    `TypeError`
        If the input is not a string.
    `ValueError`
        If no JSON object is found or the response is empty.
    """

    if not isinstance(text, str):
        raise TypeError(
            f"Input text is expected to be a string, got {type(text).__name__} instead."
        )

    # Remove XSSI header (may include extra quotes after )]})
    content = text.strip()
    if content.startswith(")]}'"):
        content = content[4:]
        # Strip any additional quotes or apostrophes after the XSSI header
        content = content.lstrip("'\"\n")

    # Try length-marker parsing first
    result = _parse_with_length_markers(content)
    if result is not None:
        return result

    # Fallback to line-by-line
    for line in content.splitlines():
        try:
            return json.loads(line.strip())
        except json.JSONDecodeError:
            continue

    # If no JSON is found, raise ValueError
    raise ValueError("Could not find a valid JSON object or array in the response.")
