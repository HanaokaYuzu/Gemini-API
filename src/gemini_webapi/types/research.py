from pydantic import BaseModel


class DeepResearchPlan(BaseModel):
    """
    Structured deep research plan extracted from Gemini's confirmation response.
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


class DeepResearchStatus(BaseModel):
    """
    Status snapshot returned by the deep research polling RPC.
    """

    research_id: str
    state: str = "running"
    title: str | None = None
    query: str | None = None
    cid: str | None = None
    notes: list[str] = []
    done: bool = False
    raw_state: int | None = None
    raw: list | dict | str | None = None
