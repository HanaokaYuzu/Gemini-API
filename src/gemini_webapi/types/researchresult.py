from pydantic import BaseModel

from .modeloutput import ModelOutput
from .research import DeepResearchPlan, DeepResearchStatus


class DeepResearchResult(BaseModel):
    """
    High-level result of a deep research run.
    """

    plan: DeepResearchPlan
    start_output: ModelOutput | None = None
    final_output: ModelOutput | None = None
    statuses: list[DeepResearchStatus] = []
    done: bool = False

    @property
    def text(self) -> str:
        if self.final_output:
            return self.final_output.text

        return ""
