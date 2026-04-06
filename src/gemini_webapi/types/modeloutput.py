from pydantic import BaseModel
from textwrap import shorten

from .image import Image
from .candidate import Candidate
from .video import GeneratedVideo, GeneratedMedia
from .research import DeepResearchPlan


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

    def __str__(self) -> str:
        return shorten(self.text, width=100)

    def __repr__(self) -> str:
        return f"ModelOutput(metadata={self.metadata!r}, chosen={self.chosen!r}, candidates={self.candidates!r})"

    @property
    def rcid(self) -> str:
        return self.candidates[self.chosen].rcid

    @property
    def text(self) -> str:
        return self.candidates[self.chosen].text

    @property
    def text_delta(self) -> str:
        return self.candidates[self.chosen].text_delta or ""

    @property
    def thoughts(self) -> str | None:
        return self.candidates[self.chosen].thoughts

    @property
    def thoughts_delta(self) -> str:
        return self.candidates[self.chosen].thoughts_delta or ""

    @property
    def images(self) -> list[Image]:
        return self.candidates[self.chosen].images

    @property
    def videos(self) -> list[GeneratedVideo]:
        return self.candidates[self.chosen].generated_videos

    @property
    def media(self) -> list[GeneratedMedia]:
        return self.candidates[self.chosen].generated_media

    @property
    def deep_research_plan(self) -> DeepResearchPlan | None:
        return self.candidates[self.chosen].deep_research_plan
