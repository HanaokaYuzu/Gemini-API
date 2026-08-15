"""Resolving the `[cite: N]` markers Gemini leaves in grounded replies.

Citations are not a deep research feature - an ordinary chat turn can carry them too, if
irregularly. The layout is the same wherever they appear, so this lives outside
`research.py` and takes the container it is given rather than knowing where to look:
field 43 of a candidate's rich content block for a chat turn, of `[17][1]` or `[5]` for a
research document.
"""

import re
from typing import Any

from .parsing import get_nested_value

_CITE_MARKER_RE = re.compile(r"\[cite:\s*([\d,\s]+)\]")
_CITE_NUMBER_RE = re.compile(r"\d+")


def citation_numbers(marker: str) -> list[str]:
    """The citation numbers a marker declares, in order.

    Markers arrive as `" [cite: 1, 2, 3]"`, and the numbers are positionally zipped with
    the source entries, so any digit picked up from outside the brackets would shift every
    source onto the wrong citation. Reading the bracket contents keeps that impossible;
    a marker without brackets falls back to scanning the whole string.
    """
    if bracket := _CITE_MARKER_RE.search(marker):
        return _CITE_NUMBER_RE.findall(bracket.group(1))
    return _CITE_NUMBER_RE.findall(marker)


def extract_citations(groups: Any) -> list[dict[str, Any]]:
    """Resolve `[cite: N]` markers to the web sources backing them.

    Sources are grouped by the citation marker they belong to, each group pairing a marker
    such as `" [cite: 1, 2, 3]"` with the sources backing it, in the order the numbers
    appear. The same source recurs across groups, so the first occurrence of each number
    wins and the result is returned sorted by citation number.

    Parameters
    ----------
    groups: `Any`
        The citation groups container, read as `constants.Field.CITATIONS` of whichever
        array publishes it.

    Returns
    -------
    `list[dict[str, Any]]`
        One mapping per citation with keys `id`, `title`, `url` and `favicon`.

    """
    if not isinstance(groups, list):
        return []

    resolved: dict[int, dict[str, Any]] = {}
    for group in groups:
        marker = get_nested_value(group, [0, 0])
        entries = get_nested_value(group, [1])
        if not isinstance(marker, str) or not isinstance(entries, list):
            continue

        for number, entry in zip(citation_numbers(marker), entries, strict=False):
            citation_id = int(number)
            if citation_id in resolved:
                continue

            url = get_nested_value(entry, [3, 0, 1])
            title = get_nested_value(entry, [3, 0, 2])
            if not isinstance(url, str):
                continue

            resolved[citation_id] = {
                "id": citation_id,
                "title": title if isinstance(title, str) else None,
                "url": url,
                "favicon": get_nested_value(entry, [3, 0, 0]),
            }

    return [resolved[key] for key in sorted(resolved)]
