from asyncio import Task

from .upload_file import upload_file  # noqa: F401
from .rotate_1psidts import rotate_1psidts  # noqa: F401
from .get_access_token import get_access_token  # noqa: F401
from .load_browser_cookies import load_browser_cookies  # noqa: F401
from .logger import logger, set_log_level  # noqa: F401


rotate_tasks: dict[str, Task] = {}
