from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Optional

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
    iter_nested,
    logger,
)

if TYPE_CHECKING:
    from ..client import ChatSession
    from ..types import ModelOutput


class ResearchMixin:
    """
    Mixin class providing deep research workflow helpers.
    """

    async def inspect_account_status(
        self,
        chat: Optional["ChatSession"] = None,
    ) -> dict:
        """
        Probe account/model capability related RPCs and return raw parsed snapshots.
        """

        source_path = self._source_path(chat.cid if chat and chat.cid else "")

        probes = [
            ("activity", GRPC.BARD_ACTIVITY, '[[["bard_activity_enabled"]]]'),
            ("bootstrap", GRPC.DEEP_RESEARCH_BOOTSTRAP, '["en",null,null,null,4,null,null,[2,4,7,15],null,[[5]]]'),
            ("model_state", GRPC.DEEP_RESEARCH_MODEL_STATE, '[[[1,4],[6,6],[1,15]]]'),
            ("quota", GRPC.DEEP_RESEARCH_MODEL_STATE, '[[[1,11],[2,11],[6,11]]]'),
            ("caps", GRPC.DEEP_RESEARCH_CAPS, '[]'),
        ]

        result: dict = {"source_path": source_path, "account_path": getattr(self, "account_path", ""), "rpc": {}}

        for probe_name, rpcid, payload in probes:
            try:
                response = await self._batch_execute(
                    [RPCData(rpcid=rpcid, payload=payload)],
                    source_path=source_path,
                    close_on_error=False,
                    current_retry=0,
                )

                parsed = []
                reject_code = None
                parts = extract_json_from_response(response.text)
                for part in parts:
                    # Keep only wrb.fr envelope for this RPC
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
                    "raw_preview": response.text[:300],
                }
            except Exception as e:
                result["rpc"][probe_name] = {
                    "rpcid": rpcid,
                    "ok": False,
                    "error": f"{type(e).__name__}: {e}",
                }

        # Summary fields for quick permission diagnostics
        all_strings = []
        for probe in result["rpc"].values():
            for item in probe.get("parsed", []):
                all_strings.extend([x for x in iter_nested(item) if isinstance(x, str)])

        def _extract_quota_rows(obj) -> list[dict]:
            rows: list[dict] = []
            if isinstance(obj, list):
                if (
                    len(obj) >= 6
                    and isinstance(obj[0], list)
                    and len(obj[0]) >= 2
                    and obj[0][1] == 11
                    and isinstance(obj[4], int)
                    and isinstance(obj[5], int)
                ):
                    rows.append(
                        {
                            "key": obj[0],
                            "window": obj[3] if len(obj) > 3 else None,
                            "remaining": obj[4],
                            "limit": obj[5],
                        }
                    )
                for child in obj:
                    rows.extend(_extract_quota_rows(child))
            elif isinstance(obj, dict):
                for child in obj.values():
                    rows.extend(_extract_quota_rows(child))
            return rows

        quota_rows: list[dict] = []
        quota_probe = result["rpc"].get("quota", {})
        for item in quota_probe.get("parsed", []):
            quota_rows.extend(_extract_quota_rows(item))

        result["summary"] = {
            "deep_research_feature_present": any(s == "DEEP_RESEARCH" for s in all_strings),
            "rejected_probes": [
                name
                for name, probe in result["rpc"].items()
                if isinstance(probe, dict) and probe.get("reject_code") == 7
            ],
            "quota_rows": quota_rows,
            "deep_research_rate_limited": any(
                row.get("remaining") == 0 and row.get("limit") == 0 for row in quota_rows
            ),
        }

        return result

    async def _assert_deep_research_capable(
        self,
        chat: Optional["ChatSession"] = None,
    ) -> None:
        snapshot = await self.inspect_account_status(chat=chat)
        rpc = snapshot.get("rpc", {})

        critical = ["activity", "model_state", "caps"]
        rejected = [
            name
            for name in critical
            if isinstance(rpc.get(name), dict) and rpc[name].get("reject_code") == 7
        ]

        if len(rejected) >= 2:
            raise GeminiError(
                "Current account/session appears not eligible for deep research (RPC reject_code=7). "
                f"Rejected RPCs: {rejected}"
            )

        summary = snapshot.get("summary", {})
        if summary.get("deep_research_rate_limited"):
            quota_rows = summary.get("quota_rows", [])
            raise UsageLimitExceeded(
                "Deep research rate limit reached for current account/session. "
                f"quota_rows={quota_rows}"
            )

    async def _deep_research_preflight(
        self,
        chat: Optional["ChatSession"] = None,
    ) -> None:
        source_path = self._source_path(chat.cid if chat and chat.cid else "")

        async def _best_effort(payloads: list[RPCData]) -> None:
            try:
                await self._batch_execute(
                    payloads,
                    source_path=source_path,
                    close_on_error=False,
                    current_retry=0,
                )
            except APIError as e:
                logger.warning(f"Skipping non-critical preflight RPC: {e}")

        await _best_effort(
            [
                RPCData(
                    rpcid=GRPC.BARD_ACTIVITY,
                    payload='[[["bard_activity_enabled"]]]',
                )
            ]
        )

        feature_state = [None] * 193
        feature_state[192] = [
            [
                "music_generation_soft",
                "image_generation_soft",
                "music_generation_soft",
                "image_generation_soft",
                "music_generation_soft",
            ]
        ]
        await _best_effort(
            [
                RPCData(
                    rpcid=GRPC.DEEP_RESEARCH_PREFS,
                    payload=json.dumps(
                        [feature_state, [["tool_menu_soft_badge_disabled_ids"]]]
                    ).decode("utf-8"),
                )
            ]
        )

        popup_state = [None] * 87
        popup_state[86] = 1
        await _best_effort(
            [
                RPCData(
                    rpcid=GRPC.DEEP_RESEARCH_PREFS,
                    payload=json.dumps(
                        [popup_state, [["popup_zs_visits_cooldown"]]]
                    ).decode("utf-8"),
                )
            ]
        )

        await _best_effort(
            [
                RPCData(
                    rpcid=GRPC.DEEP_RESEARCH_BOOTSTRAP,
                    payload='["en",null,null,null,4,null,null,[2,4,7,15],null,[[5]]]',
                )
            ]
        )

        if chat and chat.cid:
            await _best_effort(
                [
                    RPCData(
                        rpcid=GRPC.DEEP_RESEARCH_MODEL_STATE,
                        payload='[[[1,4],[6,6],[1,15]]]',
                    ),
                    RPCData(
                        rpcid=GRPC.DEEP_RESEARCH_CAPS,
                        payload='[]',
                    ),
                ]
            )

            if chat.rid:
                await _best_effort(
                    [
                        RPCData(
                            rpcid=GRPC.DEEP_RESEARCH_ACK,
                            payload=json.dumps([chat.rid]).decode("utf-8"),
                        )
                    ]
                )

    async def _collect_research_output(
        self,
        chat: "ChatSession",
        prompt: str,
    ) -> "ModelOutput":
        recoverable_error: GeminiError | APIError | None = None

        try:
            output = await chat.send_message(
                prompt,
                deep_research=True,
                current_retry=0,
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

        # Classify likely account-level limitation when Gemini returns empty/rejected body.
        try:
            snapshot = await self.inspect_account_status(chat=chat)
            summary = snapshot.get("summary", {})
            if summary.get("deep_research_rate_limited"):
                raise UsageLimitExceeded(
                    "Deep research rate limit reached for current account/session. "
                    f"quota_rows={summary.get('quota_rows', [])}"
                )
        except UsageLimitExceeded:
            raise
        except Exception:
            pass

        if recoverable_error is not None:
            raise recoverable_error

        raise GeminiError(
            "Gemini returned no usable output for deep research request. "
            f"chat.cid={chat.cid!r}; "
            f"long_token_len={len(self.deep_research_long_token) if self.deep_research_long_token else 0}; "
            f"hex_token={self.deep_research_hex_token!r}"
        )

    async def create_deep_research_plan(
        self,
        prompt: str,
        chat: Optional["ChatSession"] = None,
        model: Model | str | dict = Model.UNSPECIFIED,
        **kwargs,
    ) -> DeepResearchPlan:
        if kwargs:
            logger.debug(f"Ignoring unsupported deep research plan kwargs: {kwargs}")

        if chat is None:
            chat = self.start_chat(model=model)

        await self._assert_deep_research_capable(chat=chat)
        await self._deep_research_preflight(chat)
        output = await self._collect_research_output(chat, prompt)
        plan = output.deep_research_plan
        if not plan:
            preview = (output.text or "")[:1200]
            lower_preview = preview.lower()
            if (
                "reached your deep research limit" in lower_preview
                or "use it again when your limit resets" in lower_preview
                or "达到 deep research 限额" in preview
            ):
                raise UsageLimitExceeded(
                    "Deep research rate limit reached for current account/session. "
                    f"First response preview: {preview!r}"
                )
            if "抱歉，目前我无法提供帮助" in preview or "i’m unable to help" in lower_preview:
                raise GeminiError(
                    "Deep research was rejected by Gemini for current account/session. "
                    f"First response preview: {preview!r}"
                )
            raise GeminiError(
                "Gemini did not return a deep research plan for this prompt. "
                f"First response preview: {preview!r}"
            )

        plan.metadata = list(chat.metadata)
        plan.cid = chat.cid or plan.cid
        if not plan.confirm_prompt:
            plan.confirm_prompt = "开始研究"
        if not plan.response_text:
            plan.response_text = output.text
        return plan

    async def start_deep_research(
        self,
        plan: DeepResearchPlan,
        chat: Optional["ChatSession"] = None,
        confirm_prompt: str | None = None,
        **kwargs,
    ) -> "ModelOutput":
        if kwargs:
            logger.debug(f"Ignoring unsupported deep research start kwargs: {kwargs}")

        if chat is None:
            chat = self.start_chat(metadata=list(plan.metadata), cid=plan.cid)

        await self._deep_research_preflight(chat)
        prompt = confirm_prompt or plan.confirm_prompt or "开始研究"
        return await self._collect_research_output(chat, prompt)

    async def get_deep_research_status(
        self, research_id: str, chat: Optional["ChatSession"] = None
    ) -> DeepResearchStatus | None:
        source_path = self._source_path(chat.cid if chat and chat.cid else "")
        response = await self._batch_execute(
            [
                RPCData(
                    rpcid=GRPC.DEEP_RESEARCH_STATUS,
                    payload=json.dumps([research_id]).decode("utf-8"),
                )
            ],
            source_path=source_path,
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
        chat: Optional["ChatSession"] = None,
        poll_interval: float = 15,
        timeout: float = 1800,
    ) -> DeepResearchResult:
        started = time.monotonic()
        statuses: list[DeepResearchStatus] = []
        latest_output = None

        if chat is None:
            chat = self.start_chat(metadata=list(plan.metadata), cid=plan.cid)

        while True:
            if time.monotonic() - started > timeout:
                raise TimeoutError(
                    f"Timed out while waiting for deep research task {plan.research_id}."
                )

            await self._deep_research_preflight(chat)
            status = await self.get_deep_research_status(plan.research_id, chat=chat)
            if status:
                statuses.append(status)
                if status.cid:
                    if not plan.cid:
                        plan.cid = status.cid
                    if not chat.cid:
                        chat.cid = status.cid
                logger.debug(
                    f"Deep research {plan.research_id}: state={status.state}, done={status.done}"
                )

            if chat and chat.cid:
                latest_output = await self.fetch_latest_chat_response(chat.cid)
                if latest_output:
                    latest_text = latest_output.text or ""
                    lower_text = latest_text.lower()
                    completed = (
                        "我已经完成了研究" in latest_text
                        or "研究完成" in latest_text
                        or "i have completed the research" in lower_text
                        or "i've completed the research" in lower_text
                        or "research is complete" in lower_text
                    )
                    if completed:
                        chat.last_output = latest_output
                        return DeepResearchResult(
                            plan=plan,
                            final_output=latest_output,
                            statuses=statuses,
                            done=True,
                        )

            if status and status.done and latest_output:
                return DeepResearchResult(
                    plan=plan,
                    final_output=latest_output,
                    statuses=statuses,
                    done=True,
                )

            await asyncio.sleep(poll_interval)

    async def deep_research(
        self,
        prompt: str,
        chat: Optional["ChatSession"] = None,
        model: Model | str | dict = Model.UNSPECIFIED,
        confirm_prompt: str | None = None,
        poll_interval: float = 15,
        timeout: float = 1800,
        **kwargs,
    ) -> DeepResearchResult:
        if chat is None:
            chat = self.start_chat(model=model)

        plan = await self.create_deep_research_plan(
            prompt=prompt,
            chat=chat,
            **kwargs,
        )
        start_output = await self.start_deep_research(
            plan=plan,
            chat=chat,
            confirm_prompt=confirm_prompt,
        )
        if start_output.deep_research_plan:
            if not plan.research_id:
                plan.research_id = start_output.deep_research_plan.research_id
            if not plan.cid:
                plan.cid = start_output.deep_research_plan.cid
        if not plan.research_id:
            preview = (start_output.text or "")[:1200]
            raise GeminiError(
                "Deep research confirmation succeeded, but no research task id was found. "
                f"Start response preview: {preview!r}"
            )
        result = await self.wait_for_deep_research(
            plan=plan,
            chat=chat,
            poll_interval=poll_interval,
            timeout=timeout,
        )
        result.start_output = start_output
        return result
