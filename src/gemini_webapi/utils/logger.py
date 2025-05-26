import sys
from loguru import logger as _logger

_handler_id = None


def set_log_level(level: str | int) -> None:
    """
    Set the log level for gemini_webapi. The default log level is "INFO".

    Note: calling this function for the first time will globally remove all existing loguru
    handlers. To avoid this, you may want to set logging behaviors directly with loguru.

    Parameters
    ----------
    level : `str | int`
        Log level: "TRACE", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"

    Examples
    --------
    >>> from gemini_webapi import set_log_level
    >>> set_log_level("DEBUG")  # Show debug messages
    >>> set_log_level("ERROR")  # Only show errors
    """

    global _handler_id

    _logger.remove(_handler_id)

    _handler_id = _logger.add(
        sys.stderr,
        level=level,
        filter=lambda record: record["extra"].get("name") == "gemini_webapi",
    )


logger = _logger.bind(name="gemini_webapi")
