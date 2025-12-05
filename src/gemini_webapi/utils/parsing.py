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

    # Find the first line which is valid JSON
    for line in text.splitlines():
        try:
            return json.loads(line.strip())
        except json.JSONDecodeError:
            continue

    # If no JSON is found, raise ValueError
    raise ValueError("Could not find a valid JSON object or array in the response.")
