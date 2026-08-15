from typing import Any

from gemini_webapi.constants import Field

from .citation import extract_citations
from .parsing import get_field, get_nested_value, get_rich_content_field


def _iter_nested(data: Any):
    yield data
    if isinstance(data, list):
        for item in data:
            yield from _iter_nested(item)
    elif isinstance(data, dict):
        for item in data.values():
            yield from _iter_nested(item)


def _find_first_string(data: Any, *, exclude: set[str] | None = None) -> str | None:
    exclude = exclude or set()
    return next(
        (
            item
            for item in _iter_nested(data)
            if isinstance(item, str) and item and item not in exclude
        ),
        None,
    )


# Gemini sends this in the task id field of a research document instead of a real id
_TASK_ID_PLACEHOLDER = "agency-placeholder-task-id"


def _extract_research_id(data: Any) -> str | None:
    """Read the research task id from its field, or report that there is none.

    The id belongs at `[30][0][3]` of a candidate, which Gemini fills with a placeholder
    while the task has no real id. There is nowhere else to look: scanning the payload for
    the first UUID-shaped string returns an id belonging to something else entirely, and a
    report that merely discusses UUIDs is enough to poison it. `None` is the honest answer,
    and callers handle it - completion is tracked through the conversation instead.
    """
    task_id = get_nested_value(data, [30, 0, 3])
    if isinstance(task_id, str) and task_id and task_id != _TASK_ID_PLACEHOLDER:
        return task_id

    return None


def extract_deep_research_plan(
    candidate_data: list, fallback_text: str = ""
) -> dict[str, Any] | None:
    """Extract the research plan a deep research turn proposes before starting.

    Gemini answers the opening prompt with a plan - a title, numbered steps and an ETA -
    and waits for the next turn to confirm it. The plan is field 55 of the candidate's
    rich content block, with 56 seen as an alternate.

    Parameters
    ----------
    candidate_data: `list`
        The raw candidate list from the API response.
    fallback_text: `str`, optional
        The turn's reply text, carried through as `response_text`.

    Returns
    -------
    `dict[str, Any] | None`
        Plan fields ready for :class:`types.DeepResearchPlan`, or `None` if the turn
        proposes no plan.

    """
    # These two reads cover every place a plan is published, in either encoding. A former
    # fallback searched the payload for a dict keyed "56"/"57" - the very keys these reads
    # resolve - so it could only match a dict outside the block, inventing a wrong plan
    # rather than recovering a real one.
    payload = None

    for index in (Field.RESEARCH_PLAN, Field.RESEARCH_PLAN_ALT):
        field = get_rich_content_field(candidate_data, index)
        if isinstance(field, list):
            payload = field
            break

    if payload is None:
        return None

    research_id = _extract_research_id(candidate_data)

    title = get_nested_value(payload, [0])
    steps_payload = get_nested_value(payload, [1], [])
    steps: list[str] = []
    if isinstance(steps_payload, list):
        for step in steps_payload:
            if isinstance(step, list):
                label = step[1] if len(step) > 1 and isinstance(step[1], str) else None
                body = step[2] if len(step) > 2 and isinstance(step[2], str) else None
                if label and body:
                    steps.append(f"{label}: {body}")
                elif body:
                    steps.append(body)
                elif label:
                    steps.append(label)

    modify_payload = get_nested_value(payload, [5])
    modify_prompt = None
    if isinstance(modify_payload, list):
        modify_prompt = _find_first_string(modify_payload)

    query = (
        get_nested_value(payload, [1, 0, 2])
        if isinstance(get_nested_value(payload, [1, 0, 2]), str)
        else None
    )
    eta_text = (
        get_nested_value(payload, [2]) if isinstance(get_nested_value(payload, [2]), str) else None
    )
    confirm_prompt = (
        get_nested_value(payload, [3, 0])
        if isinstance(get_nested_value(payload, [3, 0]), str)
        else None
    )
    confirmation_url = (
        get_nested_value(payload, [4, 0])
        if isinstance(get_nested_value(payload, [4, 0]), str)
        else None
    )
    raw_state = get_rich_content_field(candidate_data, Field.RESEARCH_PLAN_STATE)
    if not isinstance(raw_state, int):
        raw_state = None

    if not any(
        [
            title if isinstance(title, str) else None,
            query,
            steps,
            eta_text,
            confirm_prompt,
            confirmation_url,
            modify_prompt,
        ]
    ):
        return None

    return {
        "research_id": research_id,
        "title": title if isinstance(title, str) else None,
        "query": query,
        "steps": steps,
        "eta_text": eta_text,
        "confirm_prompt": confirm_prompt,
        "confirmation_url": confirmation_url,
        "modify_prompt": modify_prompt,
        "raw_state": raw_state,
        "response_text": fallback_text or None,
    }


def extract_deep_research_document(candidate_data: list) -> dict[str, Any] | None:
    """Extract the immersive document a deep research turn attaches to its reply.

    The finished report is not part of the reply text - that is only a short notice, and
    the artifact marker pointing at the document is stripped from it. The document sits at
    `candidate_data[30][0]`, holding its id, title and the report body as markdown. The
    body is empty while the research is still running.

    Parameters
    ----------
    candidate_data: `list`
        The raw candidate list from the API response.

    Returns
    -------
    `dict[str, Any] | None`
        Keys `id`, `title`, `content` and `sources`, or `None` if the turn carries no
        document.

    """
    document = get_nested_value(candidate_data, [30, 0])
    if not isinstance(document, list):
        return None

    # `[30]` is a generic attachment block: a turn answering with a YouTube card fills it
    # too, with a null task id. Only a research document populates the task id at `[3]`,
    # so that separates the two without depending on the body having arrived yet.
    if not get_nested_value(document, [3]):
        return None

    doc_id = get_nested_value(document, [0])
    title = get_nested_value(document, [2])
    # [17, 0] mirrors the body; it is the fallback in case the primary field moves
    content = get_nested_value(document, [4]) or get_nested_value(document, [17, 0]) or ""

    if not isinstance(content, str):
        content = ""

    # A report publishes its citations inside the document, as field 43 of `[17][1]` or
    # `[5]` - the same field number an ordinary grounded turn uses in its content block.
    sources = extract_citations(
        get_field(get_nested_value(document, [17, 1]), Field.CITATIONS)
        or get_field(get_nested_value(document, [5]), Field.CITATIONS)
    )

    if not any([doc_id, title, content, sources]):
        return None

    return {
        "id": doc_id if isinstance(doc_id, str) else None,
        "title": title if isinstance(title, str) else None,
        "content": content,
        "sources": sources,
    }
