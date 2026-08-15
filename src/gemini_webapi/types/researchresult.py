from pydantic import BaseModel

from .modeloutput import ModelOutput
from .research import DeepResearchDocument, DeepResearchPlan


class DeepResearchResult(BaseModel):
    """High-level result of a deep research run."""

    plan: DeepResearchPlan
    start_output: ModelOutput | None = None
    final_output: ModelOutput | None = None
    done: bool = False

    def __repr__(self) -> str:
        return (
            f"DeepResearchResult(plan={self.plan!r}, done={self.done!r}, "
            f"final_output={self.final_output!r})"
        )

    @property
    def document(self) -> DeepResearchDocument | None:
        """The report document attached to the final turn, if the research produced one."""
        for output in (self.final_output, self.start_output):
            if output and (doc := output.deep_research_document) and doc.ready:
                return doc
        return None

    @property
    def text(self) -> str:
        """The research report.

        Gemini delivers the report as an inline document and leaves the reply text as a
        short notice, so the document is preferred and the reply text is only a fallback
        for a run that produced none.
        """
        if doc := self.document:
            return doc.content
        return self.final_output.text if self.final_output else ""
