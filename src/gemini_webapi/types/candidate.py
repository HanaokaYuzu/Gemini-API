import html
from textwrap import shorten

from pydantic import BaseModel, field_validator

from .citation import Citation
from .image import GeneratedImage, Image, WebImage
from .research import DeepResearchDocument, DeepResearchPlan
from .video import GeneratedMedia, GeneratedVideo


class Candidate(BaseModel):
    """A single reply candidate object in the model output. A full response from Gemini usually contains multiple reply candidates.

    Parameters
    ----------
    rcid: `str`
        Reply candidate ID to build the metadata
    text: `str`
        Text output
    thoughts: `str`, optional
        Model's thought process, can be empty.
    web_images: `list[WebImage]`, optional
        List of web images in reply, can be empty.
    generated_images: `list[GeneratedImage]`, optional
        List of generated images in reply, can be empty
    generated_videos: `list[GeneratedVideo]`, optional
        List of generated videos in reply, can be empty
    generated_media: `list[GeneratedMedia]`, optional
        List of generated media (music/audio) in reply, can be empty
    citations: `list[Citation]`, optional
        Web sources resolving the `[cite: N]` markers in `text`, can be empty
    deep_research_plan: `DeepResearchPlan`, optional
        Research plan proposed by a deep research turn, if any.
    deep_research_document: `DeepResearchDocument`, optional
        Inline report document attached by a deep research turn, if any.

    """

    rcid: str
    text: str
    text_delta: str | None = None
    thoughts: str | None = None
    thoughts_delta: str | None = None
    web_images: list[WebImage] = []
    generated_images: list[GeneratedImage] = []
    generated_videos: list[GeneratedVideo] = []
    generated_media: list[GeneratedMedia] = []
    citations: list[Citation] = []
    deep_research_plan: DeepResearchPlan | None = None
    deep_research_document: DeepResearchDocument | None = None

    def __str__(self) -> str:
        return shorten(self.text, width=100)

    def __repr__(self) -> str:
        return (
            f"Candidate(rcid={self.rcid!r}, text={shorten(self.text, width=100)!r}, "
            f"images={self.images!r}, videos={self.generated_videos!r}, media={self.generated_media!r})"
        )

    @field_validator("text", "thoughts")
    @classmethod
    def decode_html(cls, value: str) -> str:
        """Auto unescape HTML entities in text/thoughts if any."""
        if value:
            value = html.unescape(value)
        return value

    @property
    def images(self) -> list[Image]:
        images: list[Image] = [*self.web_images, *self.generated_images]
        return images
