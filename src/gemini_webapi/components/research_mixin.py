import asyncio
import time
from collections.abc import Callable, Iterator
from textwrap import shorten
from typing import TYPE_CHECKING, Any, Optional

from gemini_webapi.constants import Model
from gemini_webapi.exceptions import (
    APIError,
    GeminiError,
    ModelInvalidError,
    TemporarilyBlockedError,
    TimeoutError,
    UsageLimitExceededError,
)
from gemini_webapi.types import (
    AvailableModel,
    DeepResearchPlan,
    DeepResearchResult,
    RPCData,
)
from gemini_webapi.utils import (
    get_nested_value,
    logger,
)

if TYPE_CHECKING:
    from curl_cffi.requests import Response

    from gemini_webapi.client import ChatSession

from gemini_webapi.types import ModelOutput


def _has_report(output: "ModelOutput") -> bool:
    """Whether a turn carries a finished research report rather than an empty placeholder."""
    document = output.deep_research_document
    return bool(document and document.ready)


class ResearchMixin:
    """Mixin class providing deep research workflow helpers."""

    if TYPE_CHECKING:
        # Provided by GeminiClient and ChatMixin, which are composed alongside this mixin
        async def _batch_execute(
            self,
            payloads: list[RPCData],
            source_path: str = "/app",
            close_on_error: bool = True,
            **kwargs,
        ) -> "Response": ...

        def _parse_rpc_results(self, response_text: str, target_id: str) -> Iterator[Any]: ...

        def start_chat(self, **kwargs) -> "ChatSession": ...

        async def fetch_latest_chat_response(
            self,
            cid: str,
            limit: int = 5,
            match: Callable[[ModelOutput], bool] | None = None,
        ) -> ModelOutput | None: ...

    async def _collect_research_output(self, chat: "ChatSession", prompt: str) -> "ModelOutput":
        """Send one turn of the research conversation and return its output.

        Deep research is an ordinary multi-turn chat flagged `deep_research=True`, so the
        turn goes through `ChatSession.send_message` and inherits the account check,
        activity sync, retries and `last_output` bookkeeping of the normal generation path.
        Only the recovery below is research-specific: a research turn can land server-side
        while the request itself fails, so the chat is re-read before the error surfaces.
        """
        recoverable_error: GeminiError | APIError | None = None
        try:
            output = await chat.send_message(prompt, deep_research=True)
            # `generate_content` already assigned `chat.last_output`, advancing the session
            if output.deep_research_plan or (output.text or "").strip():
                return output
        except (UsageLimitExceededError, TimeoutError, ModelInvalidError, TemporarilyBlockedError):
            # Definitive failures - re-reading the chat cannot produce a turn that never ran
            raise
        except (GeminiError, APIError) as e:
            recoverable_error = e

        if chat.cid:
            fallback = await self.fetch_latest_chat_response(chat.cid)
            if fallback:
                chat.last_output = fallback
                return fallback

        if recoverable_error is not None:
            raise recoverable_error

        raise GeminiError(
            f"Gemini returned no usable output for deep research. chat.cid={chat.cid!r}"
        )

    async def create_deep_research_plan(
        self,
        prompt: str,
        chat: Optional["ChatSession"] = None,
        model: AvailableModel | Model | str | dict | None = None,
    ) -> DeepResearchPlan:
        """Send a deep research prompt and extract the plan Gemini proposes.

        Parameters
        ----------
        prompt: `str`
            Research topic or question.
        chat: `ChatSession`, optional
            Existing chat session to reuse.
        model: `AvailableModel | str | dict`, optional
            Model to use for generation, by name or as a model from `list_models()`.
            Defaults to the account's default model.

        Returns
        -------
        :class:`DeepResearchPlan`
            The research plan with steps, title, and confirmation prompt.

        Raises
        ------
        `gemini_webapi.GeminiError`
            If the account is ineligible or no plan is returned.

        """
        if chat is None:
            chat = self.start_chat(model=model)

        # No preflight gate here: `generate_content()` already checks the account status and
        # syncs activity for every `deep_research=True` request.
        output = await self._collect_research_output(chat, prompt)

        plan = output.deep_research_plan
        if not plan:
            preview = shorten(output.text or "", width=1200)
            raise GeminiError(f"Gemini did not return a deep research plan. Preview: {preview!r}")

        plan.metadata = list(chat.metadata)
        plan.cid = chat.cid or plan.cid
        if not plan.confirm_prompt:
            plan.confirm_prompt = "Start research"
        if not plan.response_text:
            plan.response_text = output.text
        return plan

    async def start_deep_research(
        self,
        plan: DeepResearchPlan,
        chat: Optional["ChatSession"] = None,
        confirm_prompt: str | None = None,
    ) -> "ModelOutput":
        """Confirm and start a deep research plan.

        Parameters
        ----------
        plan: `DeepResearchPlan`
            Plan returned by ``create_deep_research_plan``.
        chat: `ChatSession`, optional
            Session that produced the plan. Pass it to continue the same conversation;
            omitted, an equivalent session is rebuilt from the plan's metadata.
        confirm_prompt: `str`, optional
            Override the default confirmation text.

        Returns
        -------
        :class:`ModelOutput`
            The model's initial response after starting research.

        """
        if chat is None:
            chat = self.start_chat(metadata=list(plan.metadata), cid=plan.cid)
        prompt = confirm_prompt or plan.confirm_prompt or "Start research"
        output = await self._collect_research_output(chat, prompt)

        # The task is created by this confirmation, so its turn is the first place a real
        # id could appear. Gemini has only ever sent a placeholder, but adopting it costs
        # nothing and keeps the plan complete should that change.
        if confirmed := output.deep_research_plan:
            if not plan.research_id and confirmed.research_id:
                plan.research_id = confirmed.research_id
            if not plan.title and confirmed.title:
                plan.title = confirmed.title

        # Keep the plan pointing at the newest turn of the conversation it now owns
        if chat.metadata:
            plan.metadata = list(chat.metadata)
        plan.cid = chat.cid or plan.cid

        return output

    async def wait_for_deep_research(
        self,
        plan: DeepResearchPlan,
        poll_interval: float = 10.0,
        timeout: float = 600.0,
    ) -> DeepResearchResult:
        """Poll the conversation until the research report appears, or until timeout.

        Progress is not reported while the task runs. Gemini exposes no task entity for
        this flow: the task id field holds the literal "agency-placeholder-task-id" from
        the moment research starts until the report lands, both task-listing RPCs stay
        empty throughout, and no id appears anywhere in the raw stream - so there is
        nothing to poll for status with. The report's own arrival is the only signal.

        Parameters
        ----------
        plan: `DeepResearchPlan`
            Active research plan.
        poll_interval: `float`, optional
            Seconds between checks. Default 10.
        timeout: `float`, optional
            Maximum seconds to wait. Default 600.

        Returns
        -------
        :class:`DeepResearchResult`
            Result carrying the final output.

        """
        # Polling only needs the conversation id - the task runs server-side, detached from
        # any session, which is why the report survives leaving the chat.
        cid = plan.cid or get_nested_value(plan.metadata, [0], "")
        if not cid:
            raise GeminiError(
                "Cannot poll deep research: the plan carries no chat id. "
                "The research task may not have started successfully."
            )

        start = time.time()
        final_output: ModelOutput | None = None
        done = False

        while True:
            # The document's body stays empty until the research finishes, and the reply
            # text reads as a short notice either way, so a non-empty body is the only
            # completion signal. It can land on an earlier turn than the newest one, hence
            # the search rather than a plain "latest turn" read.
            final_output = await self.fetch_latest_chat_response(cid, limit=10, match=_has_report)
            if final_output and _has_report(final_output):
                done = True
                document = final_output.deep_research_document
                logger.debug(
                    f"Deep research [{cid}] completed: "
                    f"{len(document.content) if document else 0} chars"
                )
                break

            if (time.time() - start) >= timeout:
                logger.warning(
                    f"Deep research [{cid}] timed out after {timeout}s. The task keeps "
                    "running server-side - re-read the chat later to collect the report."
                )
                break

            await asyncio.sleep(poll_interval)

        return DeepResearchResult(
            plan=plan,
            final_output=final_output,
            done=done,
        )

    async def deep_research(
        self,
        prompt: str,
        poll_interval: float = 10.0,
        timeout: float = 600.0,
        model: AvailableModel | Model | str | dict | None = None,
        chat: Optional["ChatSession"] = None,
    ) -> DeepResearchResult:
        """Run a full deep research cycle: plan → confirm → wait → result.

        The plan and its confirmation are two turns of a single conversation, so both
        run on one `ChatSession`. To review or refine the plan between those turns, call
        `create_deep_research_plan()` and `start_deep_research()` separately with a chat
        session of your own instead.

        Parameters
        ----------
        prompt: `str`
            Research topic or question.
        poll_interval: `float`, optional
            Seconds between checks. Default 10.
        timeout: `float`, optional
            Maximum seconds to wait. Default 600. Reports commonly take 5-10 minutes, so
            raise this for broad topics.
        model: `AvailableModel | str | dict`, optional
            Model to use, by name or as a model from `list_models()`. Ignored if `chat`
            is given, which carries its own model.
        chat: `ChatSession`, optional
            Existing session to run the research conversation in. Pass one to keep a
            reference to the conversation after this call returns.

        """
        if chat is None:
            chat = self.start_chat(model=model)

        plan = await self.create_deep_research_plan(prompt, chat=chat)
        start_output = await self.start_deep_research(plan, chat=chat)
        result = await self.wait_for_deep_research(
            plan,
            poll_interval=poll_interval,
            timeout=timeout,
        )
        result.start_output = start_output
        return result
