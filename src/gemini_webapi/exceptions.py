class AuthError(Exception):
    """
    Exception for authentication errors caused by invalid credentials/cookies.
    """

    pass


class APIError(Exception):
    """
    Exception for package-level errors which need to be fixed in the future development (e.g. validation errors).
    """

    pass


class GeminiError(Exception):
    """
    Exception for errors returned from Gemini server which are not handled by the package.
    """

    pass


class TimeoutError(GeminiError):
    """
    Exception for request timeouts.
    """

    pass
