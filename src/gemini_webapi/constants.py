import re
from enum import Enum, IntEnum, StrEnum

import orjson as json


STREAMING_FLAG_INDEX = 7
GEM_FLAG_INDEX = 19
TEMPORARY_CHAT_FLAG_INDEX = 45

CARD_CONTENT_RE = re.compile(r"^http://googleusercontent\.com/card_content/\d+")
ARTIFACTS_RE = re.compile(r"http://googleusercontent\.com/\w+/\d+\n*")
DEFAULT_METADATA = ["", "", "", None, None, None, None, None, None, ""]

MODEL_HEADER_KEY = "x-goog-ext-525001261-jspb"


def build_model_header(model_id: str, capacity_tail: str | int) -> dict[str, str]:
    """
    Builds the complete HTTP header dictionary required for model selection.
    """

    return {
        MODEL_HEADER_KEY: f'[1,null,null,null,"{model_id}",null,null,0,[4],null,null,{capacity_tail}]',
        "x-goog-ext-73010989-jspb": "[0]",
        "x-goog-ext-73010990-jspb": "[0]",
    }


class Endpoint(StrEnum):
    GOOGLE = "https://www.google.com"
    INIT = "https://gemini.google.com/app"
    GENERATE = "https://gemini.google.com/_/BardChatUi/data/assistant.lamda.BardFrontendService/StreamGenerate"
    ROTATE_COOKIES = "https://accounts.google.com/RotateCookies"
    UPLOAD = "https://content-push.googleapis.com/upload"
    BATCH_EXEC = "https://gemini.google.com/_/BardChatUi/data/batchexecute"


class GRPC(StrEnum):
    """
    Google RPC ids used in Gemini API.
    """

    # Chat methods
    LIST_CHATS = "MaZiqc"
    READ_CHAT = "hNvQHb"
    DELETE_CHAT_1 = "GzXR5e"
    DELETE_CHAT_2 = "qWymEb"

    # Gem methods
    LIST_GEMS = "CNgdBe"
    CREATE_GEM = "oMH3Zd"
    UPDATE_GEM = "kHv0Vd"
    DELETE_GEM = "UXcSJb"

    GET_USER_STATUS = "otAQ7b"

    GET_FULL_SIZE_IMAGE = "c8o8Fe"

    BARD_SETTINGS = "ESY5D"


class Headers(Enum):
    REFERER = {
        "Origin": "https://gemini.google.com",
        "Referer": "https://gemini.google.com/",
    }
    SAME_DOMAIN = {
        "X-Same-Domain": "1",
    }
    GEMINI = {
        "Content-Type": "application/x-www-form-urlencoded;charset=utf-8",
        **REFERER,
    }
    ROTATE_COOKIES = {
        "Content-Type": "application/json",
        "Origin": "https://accounts.google.com",
    }
    UPLOAD = {"X-Tenant-Id": "bard-storage"}
    BATCH_EXEC = {
        "x-goog-ext-525001261-jspb": "[1,null,null,null,null,null,null,null,[4]]",
        "x-goog-ext-73010989-jspb": "[0]",
    }


class Model(Enum):
    UNSPECIFIED = ("unspecified", {}, False)
    BASIC_PRO = (
        "gemini-3-pro",
        build_model_header("9d8ca3786ebdfbea", 1),
        False,
    )
    BASIC_FLASH = (
        "gemini-3-flash",
        build_model_header("fbb127bbb056c959", 1),
        False,
    )
    BASIC_THINKING = (
        "gemini-3-flash-thinking",
        build_model_header("5bf011840784117a", 1),
        False,
    )
    PLUS_PRO = (
        "gemini-3-pro-plus",
        build_model_header("e6fa609c3fa255c0", 4),
        True,
    )
    PLUS_FLASH = (
        "gemini-3-flash-plus",
        build_model_header("56fdd199312815e2", 4),
        True,
    )
    PLUS_THINKING = (
        "gemini-3-flash-thinking-plus",
        build_model_header("e051ce1aa80aa576", 4),
        True,
    )
    ADVANCED_PRO = (
        "gemini-3-pro-advanced",
        build_model_header("e6fa609c3fa255c0", 2),
        True,
    )
    ADVANCED_FLASH = (
        "gemini-3-flash-advanced",
        build_model_header("56fdd199312815e2", 2),
        True,
    )
    ADVANCED_THINKING = (
        "gemini-3-flash-thinking-advanced",
        build_model_header("e051ce1aa80aa576", 2),
        True,
    )

    def __init__(self, name, header, advanced_only):
        self.model_name = name
        self.model_header = header
        self.advanced_only = advanced_only

    @property
    def model_id(self) -> str:
        """
        Extract the internal model_id from the model_header.
        """

        header_value = self.model_header.get(MODEL_HEADER_KEY)
        if not header_value:
            return ""

        try:
            from .utils.parsing import get_nested_value

            parsed = json.loads(header_value)
            return get_nested_value(parsed, [4], "")
        except json.JSONDecodeError:
            return ""

    @classmethod
    def from_name(cls, name: str) -> "Model":
        for model in cls:
            if model.model_name == name:
                return model

        raise ValueError(
            f"Unknown model name: {name}. Available models: {', '.join([model.model_name for model in cls])}"
        )

    @classmethod
    def from_dict(cls, model_dict: dict) -> "Model":
        if "model_name" not in model_dict or "model_header" not in model_dict:
            raise ValueError(
                "When passing a custom model as a dictionary, 'model_name' and 'model_header' keys must be provided."
            )

        if not isinstance(model_dict["model_header"], dict):
            raise ValueError(
                "When passing a custom model as a dictionary, 'model_header' must be a dictionary containing valid header strings."
            )

        custom_model = cls.UNSPECIFIED
        custom_model.model_name = model_dict["model_name"]
        custom_model.model_header = model_dict["model_header"]
        return custom_model


class AccountStatus(IntEnum):
    """
    Numeric status codes returned by the GetUserStatus RPC and their descriptions.
    """

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
        """
        Map numeric account status codes to AccountStatus enum members.

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
    """
    Known error codes returned from server.
    """

    TEMPORARY_ERROR_1013 = 1013  # Randomly raised when generating with certain models, but disappears soon after
    USAGE_LIMIT_EXCEEDED = 1037
    MODEL_INCONSISTENT = 1050
    MODEL_HEADER_INVALID = 1052
    IP_TEMPORARILY_BLOCKED = 1060
