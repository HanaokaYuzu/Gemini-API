from pydantic import BaseModel

from .image import Image
from .candidate import Candidate


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
    def text(self) -> str:
        return self.candidates[self.chosen].text

    @property
    def images(self) -> list[Image]:
        return self.candidates[self.chosen].images

    @property
    def rcid(self) -> str:
        return self.candidates[self.chosen].rcid
