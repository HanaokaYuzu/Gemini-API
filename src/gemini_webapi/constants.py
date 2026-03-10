from enum import Enum, IntEnum, StrEnum

STREAMING_FLAG_INDEX = 7
GEM_FLAG_INDEX = 19
TEMPORARY_CHAT_FLAG_INDEX = 45


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
    DELETE_CHAT = "GzXR5e"
    DELETE_CHAT_SECOND = "qWymEb"

    # Gem methods
    LIST_GEMS = "CNgdBe"
    CREATE_GEM = "oMH3Zd"
    UPDATE_GEM = "kHv0Vd"
    DELETE_GEM = "UXcSJb"

    BARD_SETTINGS = "ESY5D"

    LIST_MODELS = "otAQ7b"

    IMAGE_FULL_SIZE = "c8o8Fe"


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
    }
    UPLOAD = {"Push-ID": "feeds/mcudyrk2a4khkz", "x-tenant-id": "bard-storage"}
    BATCH_EXEC = {
        "x-goog-ext-525001261-jspb": "[1,null,null,null,null,null,null,null,[4]]",
        "x-goog-ext-73010989-jspb": "[0]",
    }


class Model(Enum):
    UNSPECIFIED = ("unspecified", {}, False)
    G_3_PRO_AI_FREE = (
        "gemini-3-pro-ai-free",
        {
            "x-goog-ext-525001261-jspb": '[1,null,null,null,"9d8ca3786ebdfbea",null,null,0,[4],null,null,1]',
            "x-goog-ext-73010989-jspb": "[0]",
            "x-goog-ext-73010990-jspb": "[0]",
        },
        False,
    )
    G_3_FLASH_AI_FREE = (
        "gemini-3-flash-ai-free",
        {
            "x-goog-ext-525001261-jspb": '[1,null,null,null,"fbb127bbb056c959",null,null,0,[4],null,null,1]',
            "x-goog-ext-73010989-jspb": "[0]",
            "x-goog-ext-73010990-jspb": "[0]",
        },
        False,
    )
    G_3_FLASH_THINKING_AI_FREE = (
        "gemini-3-flash-thinking-ai-free",
        {
            "x-goog-ext-525001261-jspb": '[1,null,null,null,"5bf011840784117a",null,null,0,[4],null,null,1]',
            "x-goog-ext-73010989-jspb": "[0]",
            "x-goog-ext-73010990-jspb": "[0]",
        },
        False,
    )
    G_3_PRO_AI_PRO = (
        "gemini-3-pro-ai-pro",
        {
            "x-goog-ext-525001261-jspb": '[1,null,null,null,"e6fa609c3fa255c0",null,null,0,[4],null,null,2]',
            "x-goog-ext-73010989-jspb": "[0]",
            "x-goog-ext-73010990-jspb": "[0]",
        },
        True,
    )
    G_3_FLASH_AI_PRO = (
        "gemini-3-flash-ai-pro",
        {
            "x-goog-ext-525001261-jspb": '[1,null,null,null,"56fdd199312815e2",null,null,0,[4],null,null,2]',
            "x-goog-ext-73010989-jspb": "[0]",
            "x-goog-ext-73010990-jspb": "[0]",
        },
        True,
    )
    G_3_FLASH_THINKING_AI_PRO = (
        "gemini-3-flash-thinking-ai-pro",
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
