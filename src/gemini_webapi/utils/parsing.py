import re
import reprlib
import string
from typing import Any

import orjson as json

from .logger import logger


_LENGTH_MARKER_PATTERN = re.compile(r"(\d+)\n")
_VOLATILE_SYMBOLS = string.whitespace + string.punctuation
_VOLATILE_SET = frozenset(_VOLATILE_SYMBOLS)
_VOLATILE_TRANS_TABLE = str.maketrans("", "", _VOLATILE_SYMBOLS)
_FLICKER_ESC_RE = re.compile(r"\\+[`*_~].*$")


def get_clean_text(s: str) -> str:
    """
    Clean Gemini text by removing trailing code block artifacts and temporary escapes of Markdown markers.
    """

    if not s:
        return ""

    if s.endswith("\n```"):
        s = s[:-4]

    return _FLICKER_ESC_RE.sub("", s)


def get_fp_len(s: str) -> int:
    """
    Calculate the length of the string after removing volatile symbols.
    Uses string translate for maximum performance.
    """

    return len(s.translate(_VOLATILE_TRANS_TABLE))


def get_delta_by_fp_len(
    new_raw: str, last_sent_clean: str, is_final: bool
) -> tuple[str, str]:
    """
    Calculate text delta by aligning stable content and matching volatile symbols.
    Handles temporary flicker at ends and permanent escaping drift during code block transitions.
    """

    new_c = get_clean_text(new_raw) if not is_final else new_raw

    if new_c.startswith(last_sent_clean):
        return new_c[len(last_sent_clean) :], new_c

    target_fp_len = get_fp_len(last_sent_clean)
    p_low = 0
    if target_fp_len > 0:
        curr_fp_len = 0
        for i, char in enumerate(new_c):
            if char not in _VOLATILE_SET:
                curr_fp_len += 1
            if curr_fp_len == target_fp_len:
                p_low = i + 1
                break
        else:
            common_len = 0
            for c1, c2 in zip(last_sent_clean, new_c):
                if c1 == c2:
                    common_len += 1
                else:
                    break
            return new_c[common_len:], new_c

    last_content_idx = -1
    for i in range(len(last_sent_clean) - 1, -1, -1):
        if last_sent_clean[i] not in _VOLATILE_SET:
            last_content_idx = i
            break

    suffix = last_sent_clean[last_content_idx + 1 :]

    i = 0
    j = 0
    limit_n = len(new_c)
    limit_s = len(suffix)

    while i < limit_s and (p_low + j) < limit_n:
        char_s = suffix[i]
        char_n = new_c[p_low + j]

        if char_s == char_n:
            i += 1
            j += 1
        elif (
            char_n == "\\"
            and (p_low + j + 1) < limit_n
            and new_c[p_low + j + 1] == char_s
        ):
            j += 2
            i += 1
        elif char_s == "\\" and (i + 1) < limit_s and suffix[i + 1] == char_n:
            i += 2
            j += 1
        else:
            break

    return new_c[p_low + j :], new_c


def _get_char_count_for_utf16_units(
    s: str, start_idx: int, utf16_units: int
) -> tuple[int, int]:
    """
    Calculate the number of Python characters (code points) and actual UTF-16
    units found.
    """

    count = 0
    units = 0
    limit = len(s)

    while units < utf16_units and (start_idx + count) < limit:
        char = s[start_idx + count]
        u = 2 if ord(char) > 0xFFFF else 1
        if units + u > utf16_units:
            break
        units += u
        count += 1

    return count, units


def get_nested_value(
    data: Any, path: list[int | str], default: Any = None, verbose: bool = False
) -> Any:
    """
    Safely navigate through a nested structure (list or dict) using a sequence of keys/indices.

    Parameters
    ----------
    data: `Any`
        The nested structure to traverse.
    path: `list[int | str]`
        A list of indices or keys representing the path.
    default: `Any`
        Value to return if the path is invalid.
    verbose: `bool`
        If True, log debug information when the path cannot be fully traversed.
    """

    current = data

    for i, key in enumerate(path):
        found = False
        if isinstance(key, int):
            if isinstance(current, list) and -len(current) <= key < len(current):
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


def parse_response_by_frame(content: str) -> tuple[list[Any], str]:
    """
    Core parser for Google's length-prefixed framing protocol,
    Parse as many JSON frames as possible from an accumulated buffer received from streaming responses.

    This function implements Google's length-prefixed framing protocol. Each frame starts
    with a length marker (number of characters) followed by a newline and the JSON content.
    If a frame is partially received, it stays in the buffer for the next call.

    Each frame has the format: `[length]\n[json_payload]\n`,
    The length value includes the newline after the number and the newline after the JSON.

    Parameters
    ----------
    content: `str`
        The accumulated string buffer containing raw streaming data from the API.

    Returns
    -------
    `tuple[list[Any], str]`
        A tuple containing:
        - A list of parsed JSON objects (envelopes) extracted from the buffer.
        - The remaining unparsed part of the buffer (incomplete frames).
    """

    consumed_pos = 0
    total_len = len(content)
    parsed_frames = []

    while consumed_pos < total_len:
        while consumed_pos < total_len and content[consumed_pos].isspace():
            consumed_pos += 1

        if consumed_pos >= total_len:
            break

        match = _LENGTH_MARKER_PATTERN.match(content, pos=consumed_pos)
        if not match:
            break

        length_val = match.group(1)
        length = int(length_val)

        # Content starts immediately after the digits.
        # Google uses UTF-16 code units (JavaScript `String.length`) for the length marker.
        start_content = match.start() + len(length_val)
        char_count, units_found = _get_char_count_for_utf16_units(
            content, start_content, length
        )

        if units_found < length:
            # Incomplete frame — don't advance pos so remainder includes it
            logger.debug(
                f"Incomplete frame at pos {consumed_pos}: expected {length} UTF-16 units, "
                f"got {units_found}"
            )
            break

        end_pos = start_content + char_count
        chunk = content[start_content:end_pos].strip()
        consumed_pos = end_pos

        if not chunk:
            continue

        try:
            parsed = json.loads(chunk)
            if isinstance(parsed, list):
                parsed_frames.extend(parsed)
            else:
                parsed_frames.append(parsed)
        except json.JSONDecodeError:
            logger.debug(
                f"Failed to parse chunk at pos {start_content} with length {length}. "
                f"Frame content: {reprlib.repr(chunk)}"
            )

    return parsed_frames, content[consumed_pos:]


def extract_json_from_response(text: str) -> list:
    """
    Extract and normalize JSON content from a Google API response.
    """

    if not isinstance(text, str):
        raise TypeError(
            f"Input text is expected to be a string, got {type(text).__name__} instead."
        )

    content = text
    if content.startswith(")]}'"):
        content = content[4:]

    content = content.lstrip()

    # Try extracting with framing protocol first, as it's the most structured format
    result, _ = parse_response_by_frame(content)
    if result:
        return result

    # Extract the entire content if parsing by frames failed
    content_stripped = content.strip()
    try:
        parsed = json.loads(content_stripped)
        return parsed if isinstance(parsed, list) else [parsed]
    except json.JSONDecodeError:
        pass

    # Extract with NDJSON
    collected_lines = []
    for line in content_stripped.splitlines():
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
