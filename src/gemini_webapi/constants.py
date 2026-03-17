import re
from enum import Enum, IntEnum, StrEnum


STREAMING_FLAG_INDEX = 7
GEM_FLAG_INDEX = 19
TEMPORARY_CHAT_FLAG_INDEX = 45

CARD_CONTENT_RE = re.compile(r"^http://googleusercontent\.com/card_content/\d+")
ARTIFACTS_RE = re.compile(r"http://googleusercontent\.com/\w+/\d+\n*")
DEFAULT_METADATA = ["", "", "", None, None, None, None, None, None, ""]


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

    LIST_MODELS = "otAQ7b"

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
    UPLOAD = {"Push-ID": "feeds/mcudyrk2a4khkz", "x-tenant-id": "bard-storage"}
    BATCH_EXEC = {
        "x-goog-ext-525001261-jspb": "[1,null,null,null,null,null,null,null,[4]]",
        "x-goog-ext-73010989-jspb": "[0]",
    }


class Model(Enum):
    UNSPECIFIED = ("unspecified", {}, False)
    BASIC_PRO = (
        "gemini-3-pro",
        {
            "x-goog-ext-525001261-jspb": '[1,null,null,null,"9d8ca3786ebdfbea",null,null,0,[4],null,null,1]',
            "x-goog-ext-73010989-jspb": "[0]",
            "x-goog-ext-73010990-jspb": "[0]",
        },
        False,
    )
    BASIC_FLASH = (
        "gemini-3-flash",
        {
            "x-goog-ext-525001261-jspb": '[1,null,null,null,"fbb127bbb056c959",null,null,0,[4],null,null,1]',
            "x-goog-ext-73010989-jspb": "[0]",
            "x-goog-ext-73010990-jspb": "[0]",
        },
        False,
    )
    BASIC_THINKING = (
        "gemini-3-flash-thinking",
        {
            "x-goog-ext-525001261-jspb": '[1,null,null,null,"5bf011840784117a",null,null,0,[4],null,null,1]',
            "x-goog-ext-73010989-jspb": "[0]",
            "x-goog-ext-73010990-jspb": "[0]",
        },
        False,
    )
    PLUS_PRO = (
        "gemini-3-pro-plus",
        {
            "x-goog-ext-525001261-jspb": '[1,null,null,null,"e6fa609c3fa255c0",null,null,0,[4],null,null,4]',
            "x-goog-ext-73010989-jspb": "[0]",
            "x-goog-ext-73010990-jspb": "[0]",
        },
        True,
    )
    PLUS_FLASH = (
        "gemini-3-flash-plus",
        {
            "x-goog-ext-525001261-jspb": '[1,null,null,null,"56fdd199312815e2",null,null,0,[4],null,null,4]',
            "x-goog-ext-73010989-jspb": "[0]",
            "x-goog-ext-73010990-jspb": "[0]",
        },
        True,
    )
    PLUS_THINKING = (
        "gemini-3-flash-thinking-plus",
        {
            "x-goog-ext-525001261-jspb": '[1,null,null,null,"e051ce1aa80aa576",null,null,0,[4],null,null,4]',
            "x-goog-ext-73010989-jspb": "[0]",
            "x-goog-ext-73010990-jspb": "[0]",
        },
        True,
    )
    ADVANCED_PRO = (
        "gemini-3-pro-advanced",
        {
            "x-goog-ext-525001261-jspb": '[1,null,null,null,"e6fa609c3fa255c0",null,null,0,[4],null,null,2]',
            "x-goog-ext-73010989-jspb": "[0]",
            "x-goog-ext-73010990-jspb": "[0]",
        },
        True,
    )
    ADVANCED_FLASH = (
        "gemini-3-flash-advanced",
        {
            "x-goog-ext-525001261-jspb": '[1,null,null,null,"56fdd199312815e2",null,null,0,[4],null,null,2]',
            "x-goog-ext-73010989-jspb": "[0]",
            "x-goog-ext-73010990-jspb": "[0]",
        },
        True,
    )
    ADVANCED_THINKING = (
        "gemini-3-flash-thinking-advanced",
        {
            "x-goog-ext-525001261-jspb": '[1,null,null,null,"e051ce1aa80aa576",null,null,0,[4],null,null,2]',
            "x-goog-ext-73010989-jspb": "[0]",
            "x-goog-ext-73010990-jspb": "[0]",
        },
        True,
    )

    def __init__(self, name, header, advanced_only):
        self.model_name = name
        self.model_header = header
        self.advanced_only = advanced_only

    @classmethod
    def from_name(cls, name: str):
        for model in cls:
            if model.model_name == name:
                return model

        raise ValueError(
            f"Unknown model name: {name}. Available models: {', '.join([model.model_name for model in cls])}"
        )

    @classmethod
    def from_dict(cls, model_dict: dict):
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


class ErrorCode(IntEnum):
    """
    Known error codes returned from server.
    """

    TEMPORARY_ERROR_1013 = 1013  # Randomly raised when generating with certain models, but disappears soon after
    USAGE_LIMIT_EXCEEDED = 1037
    MODEL_INCONSISTENT = 1050
    MODEL_HEADER_INVALID = 1052
    IP_TEMPORARILY_BLOCKED = 1060
