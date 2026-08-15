from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import orjson as json

from gemini_webapi.constants import GRPC, Field
from gemini_webapi.types import (
    Candidate,
    ChatHistory,
    ChatInfo,
    ChatTurn,
    DeepResearchDocument,
    ModelOutput,
    RPCData,
)
from gemini_webapi.utils import (
    extract_deep_research_document,
    extract_json_from_response,
    get_nested_value,
    get_rich_content_field,
    logger,
)

if TYPE_CHECKING:
    from curl_cffi.requests import Response


class ChatMixin:
    """Mixin class providing chat management functionality for GeminiClient.

    Handles fetching, listing, reading, and deleting chats via server RPCs.
    """

    if TYPE_CHECKING:
        # Provided by GeminiClient, which composes this mixin
        async def _batch_execute(
            self,
            payloads: list[RPCData],
            source_path: str = "/app",
            close_on_error: bool = True,
            **kwargs,
        ) -> "Response": ...

        def _check_account_status(self, raise_error: bool = False) -> bool: ...

        def _parse_candidate(
            self, candidate_data: list[Any], cid: str, rid: str, rcid: str
        ) -> tuple[Any, ...]: ...

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._recent_chats: list[ChatInfo] | None = None

    async def _fetch_recent_chats(self, recent: int = 13) -> None:
        """Fetch and parse recent chats."""
        if not self._check_account_status():
            return

        recent_chats: list[ChatInfo] = []

        response_chats1 = await self._batch_execute(
            [
                RPCData(
                    rpcid=GRPC.LIST_CONVERSATIONS,
                    payload=json.dumps([recent, None, [1, None, 1]]).decode("utf-8"),
                ),
            ]
        )
        response_chats2 = await self._batch_execute(
            [
                RPCData(
                    rpcid=GRPC.LIST_CONVERSATIONS,
                    payload=json.dumps([recent, None, [0, None, 1]]).decode("utf-8"),
                ),
            ]
        )

        for response_chats in (response_chats1, response_chats2):
            chats_json = extract_json_from_response(response_chats.text)
            for part in chats_json:
                part_body_str = get_nested_value(part, [2])
                if not part_body_str:
                    continue

                try:
                    part_body = json.loads(part_body_str)
                except json.JSONDecodeError:
                    continue

                chat_list = get_nested_value(part_body, [2])
                if isinstance(chat_list, list):
                    for chat_data in chat_list:
                        if isinstance(chat_data, list) and len(chat_data) > 1:
                            cid = get_nested_value(chat_data, [0], "")
                            title = get_nested_value(chat_data, [1], "")
                            is_pinned = bool(get_nested_value(chat_data, [2]))
                            timestamp_data = get_nested_value(chat_data, [5])
                            timestamp = 0.0
                            if isinstance(timestamp_data, list) and len(timestamp_data) >= 2:
                                seconds = timestamp_data[0]
                                nanos = timestamp_data[1]
                                timestamp = float(seconds) + (float(nanos) / 1e9)

                            if cid and all(c.cid != cid for c in recent_chats):
                                recent_chats.append(
                                    ChatInfo(
                                        cid=cid,
                                        title=title,
                                        is_pinned=is_pinned,
                                        timestamp=timestamp,
                                    )
                                )
                    break

        self._recent_chats = recent_chats

    def list_chats(self) -> list[ChatInfo] | None:
        """List all conversations.

        Returns
        -------
        `list[gemini_webapi.types.ChatInfo] | None`
            The list of conversations. Returns `None` if the client holds no session cache.

        """
        return self._recent_chats

    async def read_chat(self, cid: str, limit: int = 10) -> ChatHistory | None:
        """Fetch the complete conversation history by chat ID, ordered from the latest turn to the oldest.

        Parameters
        ----------
        cid: `str`
            The ID of the chat to read (e.g. "c_...").
        limit: `int`, optional
            The maximum number of turns to fetch, by default 10.

        Returns
        -------
        :class:`ChatHistory` | None
            The conversation history, or None if reading failed.

        """
        self._check_account_status(raise_error=True)

        try:
            response = await self._batch_execute(
                [
                    RPCData(
                        rpcid=GRPC.LIST_CONVERSATION_TURNS,
                        payload=json.dumps([cid, limit, None, 1, [1], [4], None, 1]).decode(
                            "utf-8"
                        ),
                    ),
                ]
            )
            response_json = extract_json_from_response(response.text)

            for part in response_json:
                part_body_str = get_nested_value(part, [2])
                if not part_body_str:
                    continue

                part_body = json.loads(part_body_str)
                turns_data = get_nested_value(part_body, [0])
                if not turns_data:
                    continue

                chat_turns = []
                for conv_turn in turns_data:
                    rid = get_nested_value(conv_turn, [0, 1], "")

                    if candidates_list := get_nested_value(conv_turn, [3, 0]):
                        output_candidates = []
                        for candidate_data in candidates_list:
                            completion_status = get_nested_value(candidate_data, [8, 0])
                            has_progress_signal = (
                                get_nested_value(
                                    get_rich_content_field(candidate_data, Field.PROGRESS), [0]
                                )
                                is not None
                            )
                            doc_data = extract_deep_research_document(candidate_data)
                            # An accepted research turn reports status 1 with an empty
                            # document: the task is running server-side, a normal state
                            # rather than an interruption. The extracted document is the
                            # test, not the raw `[30][0]` slot a YouTube card also fills.
                            research_running = completion_status == 1 and doc_data is not None

                            if completion_status == 2:
                                # Finished successfully
                                logger.debug(
                                    f"[read_chat] Gemini has successfully finalized the response for {cid!r}."
                                )
                            elif research_running:
                                logger.debug(
                                    f"[read_chat] Deep research is running server-side for {cid!r}. "
                                    "The report will attach to this turn once it completes."
                                )
                            elif has_progress_signal:
                                # Still generating / searching / thinking
                                logger.debug(
                                    f"[read_chat] Gemini is still working on the response for {cid!r}. Continuing to wait..."
                                )
                                return None
                            else:
                                # Stopped generating (e.g. usage limit, policy refusal)
                                reason = (
                                    get_nested_value(candidate_data, [1, 0])
                                    or "Gemini has stopped generating (this is usually due to a safety policy, content filter, or daily usage limit)."
                                )
                                logger.warning(
                                    f"[read_chat] Gemini generation was interrupted/stopped for {cid!r}. Reason: {reason}"
                                )

                            rcid = get_nested_value(candidate_data, [0])
                            if not rcid:
                                continue
                            (
                                text,
                                thoughts,
                                web_images,
                                generated_images,
                                generated_videos,
                                generated_media,
                                citations,
                            ) = self._parse_candidate(candidate_data, cid, rid, rcid)
                            document = DeepResearchDocument(**doc_data) if doc_data else None

                            output_candidates.append(
                                Candidate(
                                    rcid=rcid,
                                    text=text,
                                    text_delta=text,
                                    thoughts=thoughts,
                                    thoughts_delta=thoughts,
                                    web_images=web_images,
                                    generated_images=generated_images,
                                    generated_videos=generated_videos,
                                    generated_media=generated_media,
                                    citations=citations,
                                    deep_research_document=document,
                                )
                            )
                        if output_candidates:
                            model_output = ModelOutput(
                                metadata=[cid, rid],
                                candidates=output_candidates,
                            )
                            chat_turns.append(
                                ChatTurn(
                                    role="model",
                                    text=model_output.text,
                                    model_output=model_output,
                                )
                            )

                    if user_text := get_nested_value(conv_turn, [2, 0, 0], ""):
                        chat_turns.append(ChatTurn(role="user", text=user_text))

                return ChatHistory(cid=cid, turns=chat_turns)

            return None
        except Exception:
            logger.debug(
                f"[read_chat] Response data for {cid!r} is still incomplete (model is still processing)..."
            )
            return None

    async def fetch_latest_chat_response(
        self,
        cid: str,
        limit: int = 5,
        match: Callable[[ModelOutput], bool] | None = None,
    ) -> ModelOutput | None:
        """Fetch the latest model response from a chat by its cid.

        ``read_chat`` returns turns newest-first, so the first model turn is the most recent
        response. Used by ``ResearchMixin`` for fallback recovery when a streaming request
        fails but the server may have already produced a response.

        Parameters
        ----------
        cid: `str`
            The chat ID to read (e.g. ``"c_..."``).
        limit: `int`, optional
            Maximum number of turns to read back through, by default 5.
        match: `Callable`, optional
            Accept only a model output this returns `True` for, searching back from the
            newest turn. When nothing matches the newest output is still returned, so the
            caller always gets the conversation's current state - re-apply the same test to
            tell the two cases apart. Deep research needs this: a repeated confirmation can
            answer with a plain summary while the report stays on an earlier turn.

        Returns
        -------
        :class:`ModelOutput` | None
            The matching model output, the latest one when nothing matches, or ``None`` if
            the chat has no model turns.

        """
        self._check_account_status(raise_error=True)

        try:
            history = await self.read_chat(cid, limit=limit)
            if not history or not history.turns:
                logger.debug(f"fetch_latest_chat_response({cid!r}): no turns")
                return None

            latest: ModelOutput | None = None
            for turn in history.turns:  # newest-first
                if turn.role != "model" or not turn.model_output:
                    continue

                if latest is None:
                    latest = turn.model_output
                    logger.debug(
                        f"fetch_latest_chat_response({cid!r}): "
                        f"found model turn with {len(turn.text)} chars"
                    )

                if match is None:
                    return latest
                if match(turn.model_output):
                    return turn.model_output

            if latest is None:
                logger.debug(f"fetch_latest_chat_response({cid!r}): no model turns")
            return latest
        except Exception as e:
            logger.debug(f"fetch_latest_chat_response({cid!r}) failed: {type(e).__name__}: {e}")
            return None

    async def delete_chat(self, cid: str) -> None:
        """Delete a specific conversation by chat id.

        Parameters
        ----------
        cid: `str`
            The ID of the chat requiring deletion (e.g. "c_...").

        """
        self._check_account_status(raise_error=True)

        await self._batch_execute(
            [
                RPCData(
                    rpcid=GRPC.DELETE_CONVERSATION,
                    payload=json.dumps([cid]).decode("utf-8"),
                ),
            ]
        )
        await self._batch_execute(
            [
                RPCData(
                    rpcid=GRPC.GET_TASKS_IN_CONVERSATION,
                    payload=json.dumps([cid, [1, None, 0, 1]]).decode("utf-8"),
                ),
            ]
        )
