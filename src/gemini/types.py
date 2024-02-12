from pydantic import BaseModel


class Image(BaseModel):
    """
    A single image object returned from Gemini.

    Parameters
    ----------
    url: `str`
        URL of the image
    title: `str`, optional
        Title of the image, by default is "[Image]"
    alt: `str`, optional
        Optional description of the image
    """

    url: str
    title: str = "[Image]"
    alt: str = ""

    def __str__(self):
        return f"{self.title}({self.url}) - {self.alt}"

    def __repr__(self):
        return f"""Image(title='{self.title}', url='{len(self.url) <= 20 and self.url or self.url[:8] + '...' + self.url[-12:]}', alt='{self.alt}')"""


class Candidate(BaseModel):
    rcid: str
    text: str
    images: list[Image]

    def __str__(self):
        return self.text

    def __repr__(self):
        return f"Candidate(rcid='{self.rcid}', text='{len(self.text) <= 20 and self.text or self.text[:20] + '...'}', images={self.images})"


class ModelOutput(BaseModel):
    """
    Classified output from gemini.google.com

    Parameters
    ----------
    metadata: `list[str]`
        List of chat metadata `[cid, rid, rcid]`, can be shorter than 3 elements, like `[cid, rid]` or `[cid]` only
    candidates: `list[Candidate]`
        List of all candidates returned from gemini
    chosen: `int`, optional
        Index of the chosen candidate, by default will choose the first one
    """

    metadata: list[str]
    candidates: list[Candidate]
    chosen: int = 0

    def __str__(self):
        return self.text

    def __repr__(self):
        return f"ModelOutput(metadata={self.metadata}, chosen={self.chosen}, candidates={self.candidates})"

    @property
    def text(self):
        return self.candidates[self.chosen].text

    @property
    def images(self):
        return self.candidates[self.chosen].images

    @property
    def rcid(self):
        return self.candidates[self.chosen].rcid


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
