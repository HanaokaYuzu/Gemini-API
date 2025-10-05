from enum import Enum, IntEnum, StrEnum


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
    READ_CHAT = "hNvQHb"

    # Gem methods
    LIST_GEMS = "CNgdBe"
    CREATE_GEM = "oMH3Zd"
    UPDATE_GEM = "kHv0Vd"
    DELETE_GEM = "UXcSJb"


class Headers(Enum):
    GEMINI = {
        "Content-Type": "application/x-www-form-urlencoded;charset=utf-8",
        "Host": "gemini.google.com",
        "Origin": "https://gemini.google.com",
        "Priority": "u=0, i",
        "Referer": "https://gemini.google.com/",
        "Sec-Ch-Ua": 'Chromium";v="140", "Not=A?Brand";v="24", "Google Chrome";v="140',
        'Sec-Ch-Ua-Arch': 'x86',
        'Sec-Ch-Ua-Bitness': '64',
        'Sec-Ch-Ua-Form-Factors': 'Desktop',
        'Sec-Ch-Ua-Full-Version': '140.0.7339.208',
        'Sec-Ch-Ua-Full-Version-List': '"Chromium";v="140.0.7339.208", "Not=A?Brand";v="24.0.0.0", "Google Chrome";v="140.0.7339.208"',
        'Sec-Ch-Ua-Mobile': '?0',
        'Sec-Ch-Ua-Model': '',
        'Sec-Ch-Ua-Platform': 'Windows',
        'Sec-Ch-Ua-Platform-Version': '19.0.0',
        'Sec-Ch-Ua-Wow64': '?0',
        'Sec-Fetch-Dest': 'empty',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Site': 'same-origin',
        "X-Forced-Rollout-Stage": "0",
        "Accept": "*/*",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
        "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
        "X-Goog-Ext-73010989-Jspb": "[0]",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "X-Same-Domain": "1",
    }
    ROTATE_COOKIES = {
        "Content-Type": "application/json",
    }
    UPLOAD = {"Push-ID": "feeds/mcudyrk2a4khkz"}


class Model(Enum):
    UNSPECIFIED = ("unspecified", {}, False)
    G_2_5_FLASH = (
        "gemini-2.5-flash",
        {"x-goog-ext-525001261-jspb": '[1,null,null,null,"71c2d248d3b102ff",null,null,0,[4]]'},
        False,
    )
    G_2_5_PRO = (
        "gemini-2.5-pro",
        {"x-goog-ext-525001261-jspb": '[1,null,null,null,"4af6c7f5da75d65d",null,null,0,[4]]'},
        False,
    )
    G_2_0_FLASH = (
        "gemini-2.0-flash",
        {"x-goog-ext-525001261-jspb": '[1,null,null,null,"f299729663a2343f"]'},
        False,
    )  # Deprecated
    G_2_0_FLASH_THINKING = (
        "gemini-2.0-flash-thinking",
        {"x-goog-ext-525001261-jspb": '[null,null,null,null,"7ca48d02d802f20a"]'},
        False,
    )  # Deprecated

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


class ErrorCode(IntEnum):
    """
    Known error codes returned from server.
    """

    USAGE_LIMIT_EXCEEDED = 1037
    MODEL_INCONSISTENT = 1050
    MODEL_HEADER_INVALID = 1052
    IP_TEMPORARILY_BLOCKED = 1060
