class AuthError(Exception):
    """Exception for authentication errors caused by invalid credentials/cookies."""


class APIError(Exception):
    """Exception for package-level errors which need to be fixed in the future development (e.g. validation errors)."""


class ImageGenerationError(APIError):
    """Exception for generated image parsing errors."""


class GeminiError(Exception):
    """Exception for errors returned from Gemini server which are not handled by the package."""


class TimeoutError(GeminiError):
    """Exception for request timeouts."""


class UsageLimitExceededError(GeminiError):
    """Exception for model usage limit exceeded errors."""


class ModelInvalidError(GeminiError):
    """Exception for invalid model header string errors."""


class TemporarilyBlockedError(GeminiError):
    """Exception for 429 Too Many Requests when IP is temporarily blocked."""
