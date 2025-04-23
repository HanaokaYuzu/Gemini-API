from enum import Enum


class Endpoint(Enum):
    INIT = "https://gemini.google.com/app"
    GENERATE = "https://gemini.google.com/_/BardChatUi/data/assistant.lamda.BardFrontendService/StreamGenerate"
    ROTATE_COOKIES = "https://accounts.google.com/RotateCookies"
    UPLOAD = "https://content-push.googleapis.com/upload"


class Headers(Enum):
    GEMINI = {
        "Content-Type": "application/x-www-form-urlencoded;charset=utf-8",
        "Host": "gemini.google.com",
        "Origin": "https://gemini.google.com",
        "Referer": "https://gemini.google.com/",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "X-Same-Domain": "1",
    }
    ROTATE_COOKIES = {
        "Content-Type": "application/json",
    }
    UPLOAD = {"Push-ID": "feeds/mcudyrk2a4khkz"}


class Model(Enum):
    UNSPECIFIED = ("unspecified", {}, False)
    G_2_0_FLASH = (
        "gemini-2.0-flash",
        {"x-goog-ext-525001261-jspb": '[1,null,null,null,"f299729663a2343f"]'},
        False,
    )
    G_2_0_FLASH_THINKING = (
        "gemini-2.0-flash-thinking",
        {"x-goog-ext-525001261-jspb": '[null,null,null,null,"7ca48d02d802f20a"]'},
        False,
    )  # Deprecated
    G_2_5_FLASH = (
        "gemini-2.5-flash",
        {"x-goog-ext-525001261-jspb": '[1,null,null,null,"35609594dbe934d8"]'},
        False,
    )
    G_2_5_PRO = (
        "gemini-2.5-pro",
        {"x-goog-ext-525001261-jspb": '[1,null,null,null,"2525e3954d185b3c"]'},
        False,
    )
    G_2_0_EXP_ADVANCED = (
        "gemini-2.0-exp-advanced",
        {"x-goog-ext-525001261-jspb": '[null,null,null,null,"b1e46a6037e6aa9f"]'},
        True,
    )
    G_2_5_EXP_ADVANCED = (
        "gemini-2.5-exp-advanced",
        {"x-goog-ext-525001261-jspb": '[null,null,null,null,"203e6bb81620bcfe"]'},
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


class ErrorCode(Enum):
    """
    Known error codes returned from server.
    """

    USAGE_LIMIT_EXCEEDED = 1037
    MODEL_HEADER_INVALID = 1052
    IP_TEMPORARILY_BLOCKED = 1060
