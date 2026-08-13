import re
from enum import Enum, IntEnum, StrEnum
from functools import cache

import orjson as json
from curl_cffi import CurlHttpVersion
from curl_cffi.requests import BrowserTypeLiteral
from loguru import logger

STREAMING_FLAG_INDEX = 7
GEM_FLAG_INDEX = 19
TEMPORARY_CHAT_FLAG_INDEX = 45

BROWSER_TYPE: BrowserTypeLiteral = (
    "chrome145"  # Default to chrome145 to avoid Device Bound Session Credentials
)

CARD_CONTENT_RE = re.compile(r"^http://googleusercontent\.com/card_content/\d+")
ARTIFACTS_RE = re.compile(r"http://googleusercontent\.com/\w+/\d+\n*")
MODEL_PREFIX_RE = re.compile(r"^gemini-(?:\d+(?:\.\d+)?-)?")
DEFAULT_METADATA = ["", "", "", None, None, None, None, None, None, ""]

MODEL_HEADER_KEY = "x-goog-ext-525001261-jspb"

DEFAULT_LANGUAGE = "en"
DEFAULT_PUSH_ID = "feeds/mcudyrk2a4khkz"

# Gemini Flash Quota: Targeted at Gemini Flash & Flash Lite models
GEMINI_FLASH_QUOTA_PAYLOAD = "[[[1,11],[2,11],[6,11]]]"

# Gemini Advanced Quota: Targeted at Gemini Pro models & Extended Thinking level
GEMINI_ADVANCED_QUOTA_PAYLOAD = "[[[1,4],[6,6],[1,15]]]"


def build_model_header(
    model_id: str, capacity_tail: str | int, model_number: int
) -> dict[str, str]:
    """Builds the complete HTTP header dictionary required for model selection."""
    return {
        MODEL_HEADER_KEY: f'[1,null,null,null,"{model_id}",null,null,0,[4,5,6,8],null,null,{capacity_tail}, null,null,{model_number}]',
        "x-goog-ext-73010989-jspb": "[0]",
        "x-goog-ext-73010990-jspb": "[0,0,0]",
    }


class Endpoint(StrEnum):
    GOOGLE = "https://www.google.com"
    INIT = "https://gemini.google.com/app"
    GENERATE = "https://gemini.google.com/_/BardChatUi/data/assistant.lamda.BardFrontendService/StreamGenerate"
    ROTATE_COOKIES = "https://accounts.google.com/RotateCookies"
    UPLOAD = "https://content-push.googleapis.com/upload"
    BATCH_EXEC = "https://gemini.google.com/_/BardChatUi/data/batchexecute"


class GRPC(StrEnum):
    """Google RPC ids used in Gemini API."""

    # Conversation methods
    LIST_CONVERSATIONS = "MaZiqc"
    LIST_CONVERSATION_TURNS = "hNvQHb"
    GET_CONVERSATION_TURN = "EqPOKe"
    DELETE_CONVERSATION = "GzXR5e"
    UPDATE_CONVERSATION = "MUAZcd"
    MARK_LAST_CONVERSATION_TURN = "kOWVAe"
    GENERATE_HEADLINE = "ukz1Fe"

    # Gem methods
    LIST_BOTS = "CNgdBe"
    CREATE_BOT = "oMH3Zd"
    GET_BOT = "HcT8bb"
    UPDATE_BOT_METADATA = "kHv0Vd"
    DELETE_BOT = "UXcSJb"
    DELETE_BOT_AND_CONVERSATIONS = "Nwkn9"

    # Task & Research methods
    CREATE_TASK = "Jba3ib"
    GET_TASK = "kwDCne"
    GET_ALL_TASKS = "XPSWpd"
    GET_TASKS_IN_CONVERSATION = "qWymEb"
    GET_CANDIDATES = "PCck7e"
    LIST_DISCOVERY_CARDS = "ku4Jyf"
    GET_DISCOVERY_CARD = "oApPWc"
    LIST_DISCOVERY_BANNERS = "Te6DCf"

    # Artifact methods
    LIST_GEMINI_APP_ARTIFACTS = "jGArJ"
    DELETE_GEMINI_APP_ARTIFACTS = "PGX16d"

    # Memory methods
    LIST_MEMORIES = "ZKcapf"
    CREATE_MEMORY = "xVRQX"
    UPDATE_MEMORY = "gSnMcd"
    DELETE_MEMORY = "Ok9j9b"
    DELETE_ALL_MEMORIES = "YgU2Cc"

    # User & System methods
    GET_USER_STATUS = "otAQ7b"
    CHECK_GEMINI_QUOTA = "qpEbW"
    CHECK_QUOTA = "aPya6c"
    DOWNLOAD_GENERATED_IMAGE = "c8o8Fe"
    GET_ABUSE_STATUS = "GPRiHf"
    UPDATE_USER_PREFERENCES = "L5adhe"
    READ_USER_PREFERENCES = "ESY5D"
    CONTINUE_SHARED_CONVERSATION = "ra9Swb"
    GET_USAGE_INFO = "jSf9Qc"


# Header sets are built here rather than inline in `Headers` so that every enum
# member is a plain reference, keeping them recognizable as members to linters
_REFERER_HEADERS = {
    "Origin": "https://gemini.google.com",
    "Referer": "https://gemini.google.com/",
}
_SAME_DOMAIN_HEADERS = {
    "X-Same-Domain": "1",
}
_GEMINI_HEADERS = {
    "Content-Type": "application/x-www-form-urlencoded;charset=utf-8",
    **_REFERER_HEADERS,
}
_ROTATE_COOKIES_HEADERS = {
    "Content-Type": "application/json",
    "Origin": "https://accounts.google.com",
}
_UPLOAD_HEADERS = {"X-Tenant-Id": "bard-storage"}
_BATCH_EXEC_HEADERS = {
    MODEL_HEADER_KEY: "[1,null,null,null,null,null,null,null,[4,5,6,8],null,null,null,null,null,null,null]",
    "x-goog-ext-73010989-jspb": "[0]",
}


class Headers(Enum):
    REFERER = _REFERER_HEADERS
    SAME_DOMAIN = _SAME_DOMAIN_HEADERS
    GEMINI = _GEMINI_HEADERS
    ROTATE_COOKIES = _ROTATE_COOKIES_HEADERS
    UPLOAD = _UPLOAD_HEADERS
    BATCH_EXEC = _BATCH_EXEC_HEADERS


@cache
def warn_deprecated_model(usage: str) -> None:
    """Log the :class:`Model` deprecation, once per call site."""
    logger.warning(
        f"{usage} relies on the deprecated `Model` enum, which will be removed. Pass a model name "
        "string instead: models are discovered per account at runtime, so the values hardcoded "
        "here go stale whenever Google renames, renumbers or retiers a model."
    )


class Model(Enum):
    """Deprecated, pending removal. Pass a model name string, or an :class:`AvailableModel`.

    Model identity is discovered per account at initialization, which keeps names, ids and tier
    capacity current without a library release. These members cannot: their ids go stale, and the
    `PLUS_`/`ADVANCED_` variants ask the caller to know their own account tier - the same value
    :meth:`gemini_webapi.types.AvailableModel.compute_capacity` reads from the account itself.

    Nothing in this library resolves models through the enum. A member passed to
    `generate_content` is still mapped onto the account's equivalent model, with a warning; that
    compatibility shim is all that remains.
    """

    UNSPECIFIED = ("unspecified", {}, False)
    BASIC_PRO = (
        "gemini-pro",
        build_model_header("9d8ca3786ebdfbea", 1, 3),
        False,
    )
    BASIC_FLASH = (
        "gemini-flash",
        build_model_header("fbb127bbb056c959", 1, 1),
        False,
    )
    BASIC_LITE = (
        "gemini-flash-lite",
        build_model_header("cf41b0e0dd7d53e5", 1, 6),
        False,
    )
    PLUS_PRO = (
        "gemini-pro-plus",
        build_model_header("e6fa609c3fa255c0", 4, 3),
        True,
    )
    PLUS_FLASH = (
        "gemini-flash-plus",
        build_model_header("56fdd199312815e2", 4, 1),
        True,
    )
    PLUS_LITE = (
        "gemini-flash-lite-plus",
        build_model_header("8c46e95b1a07cecc", 4, 6),
        True,
    )
    ADVANCED_PRO = (
        "gemini-pro-advanced",
        build_model_header("e6fa609c3fa255c0", 2, 3),
        True,
    )
    ADVANCED_FLASH = (
        "gemini-flash-advanced",
        build_model_header("56fdd199312815e2", 2, 1),
        True,
    )
    ADVANCED_LITE = (
        "gemini-flash-lite-advanced",
        build_model_header("8c46e95b1a07cecc", 2, 6),
        True,
    )

    def __init__(self, name, header, advanced_only):
        self.model_name = name
        self.model_header = header
        self.advanced_only = advanced_only

    @property
    def model_id(self) -> str:
        """Extract the internal model_id from the model_header."""
        header_value = self.model_header.get(MODEL_HEADER_KEY)
        if not header_value:
            return ""

        try:
            from .utils.parsing import get_nested_value

            parsed = json.loads(header_value)
            return get_nested_value(parsed, [4], "")
        except json.JSONDecodeError:
            return ""


class AccountStatus(IntEnum):
    """Numeric status codes returned by the GetUserStatus RPC and their descriptions."""

    description: str  # Second element of each member value, assigned in __new__

    AVAILABLE = 1000, "Account is authorized and has normal access."

    ACCESS_TEMPORARILY_UNAVAILABLE = (
        1014,
        "Access is restricted, possibly due to regional or temporary session issues.",
    )

    UNAUTHENTICATED = (
        1016,
        "Session is not authenticated or cookies have expired. Please check your cookies.",
    )

    ACCOUNT_REJECTED = (
        1021,
        "Account access is rejected. Please check your Google Account settings.",
    )

    ACCOUNT_UNTRUSTED = (
        1033,
        "Account did not pass safety or trust checks for some features.",
    )

    TOS_PENDING = (
        1040,
        "You need to accept the latest Terms of Service to continue.",
    )

    TOS_OUT_OF_DATE = (
        1042,
        "Terms of Service are out of date; please accept the new ones.",
    )

    ACCOUNT_REJECTED_BY_GUARDIAN = (
        1054,
        "Access is blocked by a parent or guardian.",
    )

    GUARDIAN_APPROVAL_REQUIRED = (
        1057,
        "Access requires parent or guardian approval.",
    )

    LOCATION_REJECTED = (
        1060,
        "Gemini is not currently supported in your country/region.",
    )

    def __new__(cls, value: int, description: str):
        obj = int.__new__(cls, value)
        obj._value_ = value
        obj.description = description
        return obj

    @classmethod
    def from_status_code(cls, status_code: int | None) -> "AccountStatus":
        """Map numeric account status codes to AccountStatus enum members.

        Parameters
        ----------
        status_code: `int`, optional
            Numeric status code from the GetUserStatus RPC response.

        Returns
        -------
        `AccountStatus`
             The mapped AccountStatus enum member.

        """
        if status_code is None or status_code == 1000:
            return cls.AVAILABLE

        try:
            return cls(status_code)
        except ValueError:
            return cls.ACCOUNT_REJECTED


class ErrorCode(IntEnum):
    """Known error codes returned from server."""

    TEMPORARY_ERROR_1013 = (
        1013  # Randomly raised when generating with certain models, but disappears soon after
    )
    USAGE_LIMIT_EXCEEDED = 1037
    MODEL_INCONSISTENT = 1050
    MODEL_HEADER_INVALID = 1052
    IP_TEMPORARILY_BLOCKED = 1060


def format_http_version(version_int: int) -> str:
    """Format the raw HTTP version integer from curl_cffi into a human-readable string."""
    try:
        return CurlHttpVersion(version_int).name
    except ValueError:
        return str(version_int)
