import asyncio
import time
from textwrap import shorten
from typing import TYPE_CHECKING, Callable, Optional

import orjson as json

from ..constants import GRPC, Model
from ..exceptions import (
    APIError,
    GeminiError,
    ModelInvalid,
    TemporarilyBlocked,
    TimeoutError,
    UsageLimitExceeded,
)
from ..types import DeepResearchPlan, DeepResearchResult, DeepResearchStatus, RPCData
from ..utils import (
    extract_deep_research_status_payload,
    extract_json_from_response,
    get_nested_value,
    logger,
)

if TYPE_CHECKING:
    from ..client import ChatSession
    from ..types import ModelOutput


class ResearchMixin:
    """
    Mixin class providing deep research workflow helpers.
    """

    async def inspect_account_status(self) -> dict:
        """Probe account/model capability RPCs and return raw parsed snapshots."""

        probes = [
            ("activity", GRPC.BARD_SETTINGS, '[[["bard_activity_enabled"]]]'),
            (
                "bootstrap",
                GRPC.DEEP_RESEARCH_BOOTSTRAP,
                '["en",null,null,null,4,null,null,[2,4,7,15],null,[[5]]]',
            ),
            ("model_state", GRPC.DEEP_RESEARCH_MODEL_STATE, "[[[1,4],[6,6],[1,15]]]"),
            ("quota", GRPC.DEEP_RESEARCH_MODEL_STATE, "[[[1,11],[2,11],[6,11]]]"),
            ("caps", GRPC.DEEP_RESEARCH_CAPS, "[]"),
        ]

        result: dict = {
            "source_path": "/app",
            "account_path": getattr(self, "account_path", ""),
            "rpc": {},
        }

        for probe_name, rpcid, payload in probes:
            try:
                response = await self._batch_execute(
                    [RPCData(rpcid=rpcid, payload=payload)], close_on_error=False
                )
                parsed = []
                reject_code = None
                parts = extract_json_from_response(response.text)
                for part in parts:
                    if get_nested_value(part, [0]) != "wrb.fr":
                        continue
                    if get_nested_value(part, [1]) != rpcid:
                        continue
                    code = get_nested_value(part, [5, 0])
                    if isinstance(code, int):
                        reject_code = code
                    body = get_nested_value(part, [2])
                    if isinstance(body, str):
                        try:
                            parsed.append(json.loads(body))
                        except json.JSONDecodeError:
                            parsed.append(body)
                    elif body is not None:
                        parsed.append(body)

                result["rpc"][probe_name] = {
                    "rpcid": rpcid,
                    "ok": True,
                    "status_code": response.status_code,
                    "parsed": parsed,
                    "reject_code": reject_code,
                    "raw_preview": shorten(response.text, width=300),
                }
            except Exception as e:
                result["rpc"][probe_name] = {
                    "rpcid": rpcid,
                    "ok": False,
                    "error": f"{type(e).__name__}: {e}",
                }

        # Summary for quick permission diagnostics
        rejected = [
            name
            for name, probe in result["rpc"].items()
            if isinstance(probe, dict) and probe.get("reject_code") == 7
        ]

        # Deep research is available when the three DR-specific probes
        # all succeed without rejection.  The old heuristic looked for a
        # literal "DEEP_RESEARCH" string in the responses, but the RPC
        # payloads only contain numeric/boolean data.
        dr_probes = ("bootstrap", "model_state", "caps")
        dr_available = all(
            result["rpc"].get(p, {}).get("ok", False)
            and result["rpc"].get(p, {}).get("reject_code") is None
            for p in dr_probes
        )

        result["summary"] = {
            "deep_research_feature_present": dr_available,
            "rejected_probes": rejected,
        }

        return result

    async def _assert_deep_research_capable(self) -> None:
        snapshot = await self.inspect_account_status()
        summary = snapshot.get("summary", {})

        if not summary.get("deep_research_feature_present", False):
            rejected = summary.get("rejected_probes", [])
            rpc = snapshot.get("rpc", {})
            failed = [
                name
                for name, probe in rpc.items()
                if isinstance(probe, dict) and not probe.get("ok", False)
            ]
            raise GeminiError(
                "Current account/session appears not eligible for "
                f"deep research. Rejected: {rejected}, Failed: {failed}"
            )

    async def _deep_research_preflight(self) -> None:
        async def _best_effort(payloads: list[RPCData]) -> None:
            try:
                await self._batch_execute(payloads, close_on_error=False)
            except APIError as e:
                logger.warning(f"Skipping non-critical preflight RPC: {e}")

        await _best_effort(
            [
                RPCData(
                    rpcid=GRPC.BARD_SETTINGS,
                    payload='[[["bard_activity_enabled"]]]',
                )
            ]
        )

        await _best_effort(
            [
                RPCData(
                    rpcid=GRPC.DEEP_RESEARCH_BOOTSTRAP,
                    payload='["en",null,null,null,4,null,null,'
                    "[2,4,7,15],null,[[5]]]",
                )
            ]
        )

    async def _collect_research_output(
        self, chat: "ChatSession", prompt: str
    ) -> "ModelOutput":
        recoverable_error: GeminiError | APIError | None = None
        try:
            output = await chat.send_message(
                prompt,
                deep_research=True,
            )
            preview = (output.text or "").strip()
            if output.deep_research_plan or preview:
                chat.last_output = output
                return output
        except UsageLimitExceeded:
            raise
        except (TimeoutError, ModelInvalid, TemporarilyBlocked):
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
            "Gemini returned no usable output for deep research. "
            f"chat.cid={chat.cid!r}"
        )

    async def create_deep_research_plan(
        self,
        prompt: str,
        chat: Optional["ChatSession"] = None,
        model: Model | str | dict = Model.UNSPECIFIED,
    ) -> DeepResearchPlan:
        """
        Send a deep research prompt and extract the plan Gemini proposes.

        Parameters
        ----------
        prompt: `str`
            Research topic or question.
        chat: `ChatSession`, optional
            Existing chat session to reuse.
        model: `Model | str | dict`, optional
            Model to use for generation.

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

        await self._assert_deep_research_capable()
        await self._deep_research_preflight()
        output = await self._collect_research_output(chat, prompt)
        plan = output.deep_research_plan
        if not plan:
            preview = shorten(output.text or "", width=1200)
            raise GeminiError(
                "Gemini did not return a deep research plan. " f"Preview: {preview!r}"
            )

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
        """
        Confirm and start a deep research plan.

        Parameters
        ----------
        plan: `DeepResearchPlan`
            Plan returned by ``create_deep_research_plan``.
        chat: `ChatSession`, optional
            Existing session. Created from plan metadata if omitted.
        confirm_prompt: `str`, optional
            Override the default confirmation text.

        Returns
        -------
        :class:`ModelOutput`
            The model's initial response after starting research.
        """

        if chat is None:
            chat = self.start_chat(metadata=list(plan.metadata), cid=plan.cid)
        await self._deep_research_preflight()
        prompt = confirm_prompt or plan.confirm_prompt or "Start research"
        return await self._collect_research_output(chat, prompt)

    async def get_deep_research_status(
        self, research_id: str
    ) -> DeepResearchStatus | None:
        response = await self._batch_execute(
            [
                RPCData(
                    rpcid=GRPC.DEEP_RESEARCH_STATUS,
                    payload=json.dumps([research_id]).decode("utf-8"),
                )
            ]
        )
        response_json = extract_json_from_response(response.text)
        for part in response_json:
            part_body_str = get_nested_value(part, [2])
            if not part_body_str:
                continue
            try:
                part_body = json.loads(part_body_str)
            except json.JSONDecodeError:
                continue
            parsed = extract_deep_research_status_payload(part_body)
            if parsed:
                return DeepResearchStatus(**parsed)
        return None

    async def wait_for_deep_research(
        self,
        plan: DeepResearchPlan,
        poll_interval: float = 10.0,
        timeout: float = 600.0,
        on_status: Callable[[DeepResearchStatus], None] | None = None,
    ) -> DeepResearchResult:
        """
        Poll deep research status until completion or timeout.

        Parameters
        ----------
        plan: `DeepResearchPlan`
            Active research plan.
        poll_interval: `float`, optional
            Seconds between status checks. Default 10.
        timeout: `float`, optional
            Maximum seconds to wait. Default 600.
        on_status: `Callable`, optional
            Callback invoked with each `DeepResearchStatus`.

        Returns
        -------
        :class:`DeepResearchResult`
            Result with status history and final output.
        """

        if not plan.research_id:
            raise GeminiError(
                "Cannot poll deep research status: plan.research_id is missing. "
                "The research task may not have started successfully."
            )

        start = time.time()
        statuses: list[DeepResearchStatus] = []
        chat = self.start_chat(metadata=list(plan.metadata), cid=plan.cid)

        while (time.time() - start) < timeout:
            status = None
            if plan.research_id:
                status = await self.get_deep_research_status(plan.research_id)
            if status:
                statuses.append(status)
                logger.debug(
                    f"Deep research [{plan.research_id}] " f"status: {status.state}"
                )
                if on_status:
                    on_status(status)
                if status.done:
                    break
            await asyncio.sleep(poll_interval)

        if not statuses or not statuses[-1].done:
            logger.warning(
                f"Deep research [{plan.research_id}] timed out "
                f"after {timeout}s with {len(statuses)} status updates"
            )

        final_output = None
        if chat.cid:
            final_output = await self.fetch_latest_chat_response(chat.cid)

        done = bool(statuses and statuses[-1].done)
        return DeepResearchResult(
            plan=plan,
            statuses=statuses,
            final_output=final_output,
            done=done,
        )

    async def deep_research(
        self,
        prompt: str,
        poll_interval: float = 10.0,
        timeout: float = 600.0,
        on_status: Callable[[DeepResearchStatus], None] | None = None,
    ) -> DeepResearchResult:
        """
        Run a full deep research cycle: plan → start → wait → result.

        Parameters
        ----------
        prompt: `str`
            Research topic or question.
        poll_interval: `float`, optional
            Seconds between status checks. Default 10.
        timeout: `float`, optional
            Maximum seconds to wait. Default 600.
        on_status: `Callable`, optional
            Callback invoked with each `DeepResearchStatus`.
        """

        plan = await self.create_deep_research_plan(prompt)
        start_output = await self.start_deep_research(plan)
        result = await self.wait_for_deep_research(
            plan,
            poll_interval=poll_interval,
            timeout=timeout,
            on_status=on_status,
        )
        result.start_output = start_output
        return result
