import contextlib
import difflib
import re
import reprlib
from typing import Any

import orjson as json

from .logger import logger

_LENGTH_MARKER_PATTERN = re.compile(r"(\d+)\n")
_FLICKER_ESC_RE = re.compile(r"\\+[`*_~].*$")


def get_clean_text(s: str) -> str:
    """Clean Gemini text by removing trailing code block artifacts and temporary escapes of Markdown markers."""
    if not s:
        return ""

    s = s.removesuffix("\n```")

    return _FLICKER_ESC_RE.sub("", s)


def get_delta_by_fp_len(new_raw: str, last_sent_clean: str, is_final: bool) -> tuple[str, str]:
    """Calculate text delta by aligning stable content and matching volatile symbols.
    Handles temporary flicker at ends and permanent escaping drift during code block transitions.
    Uses SequenceMatcher to robustly handle middle-string modifications.
    """
    new_c = new_raw if is_final else get_clean_text(new_raw)

    if new_c.startswith(last_sent_clean):
        return new_c[len(last_sent_clean) :], new_c

    # Find the matching suffix to handle differences gracefully
    search_len = min(3000, max(1000, len(last_sent_clean)))
    search_len = min(search_len, len(last_sent_clean), len(new_c))

    if search_len == 0:
        return new_c, new_c

    tail_last = last_sent_clean[-search_len:]
    tail_new = new_c[-search_len:]

    sm = difflib.SequenceMatcher(None, tail_last, tail_new)
    if blocks := [b for b in sm.get_matching_blocks() if b.size > 0]:
        last_match = blocks[-1]
        match_end = last_match.b + last_match.size
        return tail_new[match_end:], new_c

    # Fallback to full string if tail didn't match at all
    sm = difflib.SequenceMatcher(None, last_sent_clean, new_c)
    if blocks := [b for b in sm.get_matching_blocks() if b.size > 0]:
        last_match = blocks[-1]
        match_end = last_match.b + last_match.size
        return new_c[match_end:], new_c

    return new_c, new_c


def get_nested_value(
    data: Any, path: list[int | str], default: Any = None, verbose: bool = False
) -> Any:
    """Safely navigate through a nested structure (list or dict) using a sequence of keys/indices.

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
        match current, key:
            case list(), int() if -len(current) <= key < len(current):
                current = current[key]
            case dict(), str() if key in current:
                current = current[key]
            case _:
                if verbose:
                    logger.debug(
                        f"Safe navigation: path {path} ended at index {i} (key '{key}'), "
                        f"returning default. Context: {reprlib.repr(current)}"
                    )
                return default

    return current if current is not None else default


def get_sparse_bundle(container: Any) -> dict | None:
    """The dict of sparse fields a JSPB array carries in its final slot.

    Low field numbers occupy their positional index, while sparse high-numbered fields are
    collected into a dict keyed by the 1-based field number, so positional 86 appears as
    key "87". That dict is always the array's last element, so its index moves with the
    array's length - index 0 of a one-element block on a music turn, index 8 of a
    nine-element block on a finished research turn - and cannot be anchored to.
    """
    if isinstance(container, list) and container and isinstance(container[-1], dict):
        return container[-1]
    return None


def get_field(container: Any, index: int, default: Any = None) -> Any:
    """Read field `index` of a JSPB array from whichever form carries it.

    Checks the positional slot first, then the sparse bundle described in
    :func:`get_sparse_bundle`. Only one of the two ever holds a given field.
    """
    if not isinstance(container, list) or not container:
        return default

    value = container[index] if 0 <= index < len(container) else None
    # A dict in that slot is the sparse bundle itself, not the field's value
    if value in (None, [], {}) or isinstance(value, dict):
        bundle = get_sparse_bundle(container)
        value = bundle.get(str(index + 1)) if bundle else None

    return default if value in (None, [], {}) else value


def get_rich_content_field(candidate_data: Any, index: int, default: Any = None) -> Any:
    """Read field `index` of a candidate's `[12]` rich content block."""
    return get_field(get_nested_value(candidate_data, [12]), index, default)


class StreamingFrameParser:
    """Incrementally parse Google's length-prefixed streaming frames without
    rescanning unfinished frame payloads after every network chunk.

    The parser keeps the incomplete frame state internally. Complete frames are
    decoded and returned from :meth:`feed`, while partial frames remain buffered
    until enough text arrives. The length marker is interpreted as UTF-16 code
    units to match JavaScript string length semantics used by Google.
    """

    def __init__(self) -> None:
        """Initialize an empty streaming parser state."""
        self.buffer = ""
        self.expected_units: int | None = None
        self.payload_start = 0
        self.scanned_chars = 0
        self.scanned_units = 0
        self.prefix_checked = False

    def reset(self) -> None:
        """Clear buffered text and any in-progress frame state."""
        self.buffer = ""
        self._reset_frame_state()
        self.prefix_checked = False

    def feed(self, content: str) -> list[Any]:
        """Add decoded stream text and return all complete JSON frames.

        Parameters
        ----------
        content: `str`
            Newly decoded stream text from the HTTP response.

        Returns
        -------
        `list[Any]`
            Parsed JSON envelopes completed by this feed call.

        """
        if not isinstance(content, str):
            raise TypeError(
                f"Input content is expected to be a string, got {type(content).__name__} instead."
            )

        if content:
            self.buffer += content

        self._strip_prefix_once()

        parsed_frames = []
        while (
            self.expected_units is not None or self._read_length_marker()
        ) and self.expected_units is not None:
            self._scan_available_payload()
            if self.scanned_units < self.expected_units:
                break

            end_pos = self.payload_start + self.scanned_chars
            chunk = self.buffer[self.payload_start : end_pos]
            self.buffer = self.buffer[end_pos:]
            self._reset_frame_state()

            if not chunk.strip():
                continue

            try:
                parsed = json.loads(chunk)
            except json.JSONDecodeError:
                logger.debug(
                    f"Failed to parse streaming frame with length {len(chunk)}. "
                    f"Frame content: {reprlib.repr(chunk)}"
                )
                continue

            if isinstance(parsed, list):
                parsed_frames.extend(parsed)
            else:
                parsed_frames.append(parsed)

        return parsed_frames

    def flush(self) -> list[Any]:
        """Parse any complete frame left after the decoder has emitted final text."""
        return self.feed("")

    def _reset_frame_state(self) -> None:
        """Clear only the currently tracked frame metadata."""
        self.expected_units = None
        self.payload_start = 0
        self.scanned_chars = 0
        self.scanned_units = 0

    def _strip_prefix_once(self) -> None:
        """Remove Google's anti-XSSI prefix once enough leading text is available."""
        if self.prefix_checked:
            return

        prefix = ")]}'"
        if len(self.buffer) < len(prefix) and prefix.startswith(self.buffer):
            return

        if self.buffer.startswith(prefix):
            self.buffer = self.buffer[len(prefix) :].lstrip()

        self.prefix_checked = True

    def _read_length_marker(self) -> bool:
        """Read the next frame length marker when the marker is fully buffered."""
        consumed_pos = 0
        total_len = len(self.buffer)
        while consumed_pos < total_len and self.buffer[consumed_pos].isspace():
            consumed_pos += 1

        if consumed_pos:
            self.buffer = self.buffer[consumed_pos:]
            total_len = len(self.buffer)

        if total_len == 0:
            return False

        match = _LENGTH_MARKER_PATTERN.match(self.buffer)
        if not match:
            return False
        length_val = match.group(1)
        self.expected_units = int(length_val)
        self.payload_start = len(length_val)
        self.scanned_chars = 0
        self.scanned_units = 0
        return True

    def _scan_available_payload(self) -> None:
        """Advance UTF-16 unit accounting over only the newly buffered payload text."""
        if self.expected_units is None:
            return

        idx = self.payload_start + self.scanned_chars
        limit = len(self.buffer)

        while self.scanned_units < self.expected_units and idx < limit:
            unit_count = 2 if ord(self.buffer[idx]) > 0xFFFF else 1
            if self.scanned_units + unit_count > self.expected_units:
                break
            self.scanned_units += unit_count
            self.scanned_chars += 1
            idx += 1


def extract_json_from_response(text: str) -> list:
    """Extract and normalize JSON content from a Google API response.

    Length-prefixed responses are parsed through the same incremental frame
    parser used by streaming code so frame parsing behavior stays centralized.
    """
    if not isinstance(text, str):
        raise TypeError(
            f"Input text is expected to be a string, got {type(text).__name__} instead."
        )

    content = text
    content = content.removeprefix(")]}'")
    content = content.lstrip()

    frame_parser = StreamingFrameParser()
    result = frame_parser.feed(content)
    result.extend(frame_parser.flush())
    if result:
        return result

    # Extract the entire content if parsing by frames failed
    content_stripped = content.strip()
    with contextlib.suppress(json.JSONDecodeError):
        parsed = json.loads(content_stripped)
        return parsed if isinstance(parsed, list) else [parsed]
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
