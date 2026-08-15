from pydantic import BaseModel

from .citation import Citation


class DeepResearchPlan(BaseModel):
    """Research plan Gemini proposes before starting, and waits for confirmation on.

    `confirm_prompt` is the reply that accepts the plan as it stands; `modify_prompt` is
    the one that asks for changes instead.
    """

    research_id: str | None = None
    title: str | None = None
    query: str | None = None
    steps: list[str] = []
    eta_text: str | None = None
    confirm_prompt: str | None = None
    modify_prompt: str | None = None
    confirmation_url: str | None = None
    metadata: list[str | None] = []
    cid: str | None = None
    response_text: str | None = None
    raw_state: int | None = None

    def __repr__(self) -> str:
        return (
            f"DeepResearchPlan(research_id={self.research_id!r}, title={self.title!r}, "
            f"eta_text={self.eta_text!r}, metadata={self.metadata!r})"
        )


class DeepResearchDocument(BaseModel):
    """Inline document a deep research turn attaches to its reply.

    Gemini delivers the finished report as an immersive document rather than as reply
    text - the reply itself is only a short notice such as "I've completed your research".
    A turn sent while the research is still running carries this container with an empty
    `content`, so a non-empty `content` is what marks the report as ready.

    `content` is markdown, keeping the report's headings, tables and links intact, with
    inline `[cite: N]` markers whose sources are resolved in `sources`.
    """

    id: str | None = None
    title: str | None = None
    content: str = ""
    sources: list[Citation] = []

    def __repr__(self) -> str:
        return (
            f"DeepResearchDocument(id={self.id!r}, title={self.title!r}, "
            f"content={len(self.content)} chars, sources={len(self.sources)})"
        )

    # Reports run to tens of thousands of characters, so neither form prints the body
    __str__ = __repr__

    @property
    def ready(self) -> bool:
        """Whether the document carries a finished report."""
        return bool(self.content.strip())

    @property
    def markdown(self) -> str:
        """The report as a self-contained markdown document.

        The body is returned as Gemini wrote it, followed by a numbered source list so the
        inline `[cite: N]` markers resolve to links once the report leaves the chat.
        """
        if not self.sources:
            return self.content

        lines = [self.content.rstrip(), "", "## Sources", ""]
        lines.extend(
            f"{source.id}. [{source.title or source.url}]({source.url})"
            if source.url
            else f"{source.id}. {source.title or ''}"
            for source in self.sources
        )
        return "\n".join(lines) + "\n"
