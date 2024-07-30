import atexit
from sys import stderr

from loguru._logger import Core as _Core
from loguru._logger import Logger as _Logger

logger = _Logger(
    core=_Core(),
    exception=None,
    depth=0,
    record=False,
    lazy=False,
    colors=False,
    raw=False,
    capture=True,
    patchers=[],
    extra={},
)

if stderr:
    logger.add(stderr, level="INFO")

atexit.register(logger.remove)


def set_log_level(level: str):
    """
    Set the log level for the whole module. Default is "INFO". Set to "DEBUG" to see more detailed logs.

    Parameters
    ----------
    level : str
        The log level to set. Must be one of "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL".
    """

    assert level in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

    logger.remove()
    logger.add(stderr, level=level)
