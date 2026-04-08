import orjson as json

from ..constants import GRPC
from ..types import (
    ChatHistory,
    ChatInfo,
    ChatListPage,
    ChatTurn,
    Candidate,
    ModelOutput,
    RPCData,
)
from ..utils import extract_json_from_response, get_nested_value, logger


class ChatMixin:
    """
    Mixin class providing chat management functionality for GeminiClient.

    Handles fetching, listing, reading, and deleting chats via server RPCs.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._recent_chats: list[ChatInfo] | None = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_chat_list_response(
        response_text: str,
    ) -> tuple[list[ChatInfo], str]:
        """
        Parse a LIST_CHATS RPC response into chat items and a next-page
        cursor.

        The inner RPC body has structure ``[unknown, cursor_or_null, [chat_item, ...]]``.

        Returns
        -------
        tuple[list[ChatInfo], str]
            (chat_items, next_cursor). next_cursor is ``""`` when there
            are no more pages.
        """
        items: list[ChatInfo] = []
        next_cursor = ""

        chats_json = extract_json_from_response(response_text)
        for part in chats_json:
            part_body_str = get_nested_value(part, [2])
            if not part_body_str:
                continue

            try:
                part_body = json.loads(part_body_str)
            except json.JSONDecodeError:
                continue

            # --- Cursor at part_body[1] (matches Go: data[1]) ---
            cursor_val = get_nested_value(part_body, [1])
            if isinstance(cursor_val, str) and cursor_val:
                next_cursor = cursor_val

            # --- Chat items at part_body[2] (matches Go: data[2]) ---
            chat_list = get_nested_value(part_body, [2])
            if isinstance(chat_list, list):
                for chat_data in chat_list:
                    if not isinstance(chat_data, list) or len(chat_data) < 2:
                        continue
                    cid = get_nested_value(chat_data, [0], "")
                    title = get_nested_value(chat_data, [1], "")
                    is_pinned = bool(get_nested_value(chat_data, [2]))
                    timestamp_data = get_nested_value(chat_data, [5])
                    timestamp = 0.0
                    if (
                        isinstance(timestamp_data, list)
                        and len(timestamp_data) >= 2
                    ):
                        seconds = timestamp_data[0]
                        nanos = timestamp_data[1]
                        timestamp = float(seconds) + (float(nanos) / 1e9)

                    if cid:
                        items.append(
                            ChatInfo(
                                cid=cid,
                                title=title,
                                is_pinned=is_pinned,
                                timestamp=timestamp,
                            )
                        )
                break  # only process the first valid part

        return items, next_cursor

    async def _try_list_chats(
        self,
        payload: list,
        source_path: str = "/app",
    ) -> tuple[list[ChatInfo], str]:
        """
        Attempt a single LIST_CHATS RPC call with the given payload and
        source path.

        Returns
        -------
        tuple[list[ChatInfo], str]
            Parsed chat items and the next-page cursor (``""`` if none).
        """
        try:
            response = await self._batch_execute(
                [
                    RPCData(
                        rpcid=GRPC.LIST_CHATS,
                        payload=json.dumps(payload).decode("utf-8"),
                    ),
                ],
                source_path=source_path,
            )
            return self._parse_chat_list_response(response.text)
        except Exception as e:
            logger.debug(
                f"list_chats attempt failed (path={source_path}, "
                f"payload={payload!r}): {e}"
            )
            return [], ""

    # ------------------------------------------------------------------
    # Init-time fetch (backward compatible, called by _init_rpc)
    # ------------------------------------------------------------------

    async def _fetch_recent_chats(self, recent: int = 13) -> None:
        """
        Fetch and parse recent chats (called during client init).

        Tries all three payload variants to collect both pinned and
        unpinned chats, matching the Go reference implementation.
        """
        payloads = [
            [recent, None, [1, None, 1]],   # pinned
            [recent, None, [0, None, 1]],   # unpinned
            [recent, None, [0, None, 2]],   # extra variant (Go compat)
        ]

        # Try the default source path; a second path could be added here
        # if the client ever supports a configurable app path.

        source_paths = ["/app"]

        seen_cids: set[str] = set()
        recent_chats: list[ChatInfo] = []

        for source_path in source_paths:
            for payload in payloads:
                items, _ = await self._try_list_chats(payload, source_path)
                for item in items:
                    if item.cid not in seen_cids:
                        seen_cids.add(item.cid)
                        recent_chats.append(item)
                # Don't break — try all variants to collect both
                # pinned and unpinned chats during init.

        self._recent_chats = recent_chats

    # ------------------------------------------------------------------
    # Public API — synchronous cached access (backward compatible)
    # ------------------------------------------------------------------

    def list_chats(self) -> list[ChatInfo] | None:
        """
        List all conversations (cached from init).

        For paginated access to all chats, use :meth:`list_chats_page` instead.

        Returns
        -------
        `list[gemini_webapi.types.ChatInfo] | None`
            The list of conversations. Returns `None` if the client
            holds no session cache.
        """
        return self._recent_chats

    # ------------------------------------------------------------------
    # Public API — async paginated access (NEW)
    # ------------------------------------------------------------------

    async def list_chats_page(
        self,
        cursor: str = "",
        page_size: int = 20,
    ) -> ChatListPage:
        """
        Fetch a single page of chats with optional pagination cursor.

        Mirrors the Go library's ``ListChats(ctx, cursor)`` behavior.

        Parameters
        ----------
        cursor: `str`, optional
            Pagination cursor from a previous call's
            :attr:`ChatListPage.cursor`. Pass ``""`` (default) to start
            from the beginning.
        page_size: `int`, optional
            Number of chats to request per page. Default is 20.

        Returns
        -------
        :class:`ChatListPage`
            A page containing chat items and a next-page cursor.
            If ``cursor`` is empty, there are no more pages.
        """
        if cursor:
            # Paginated request — single payload with cursor
            # (matches Go: {20, cursor, [0, nil, 1]})
            payloads = [
                [page_size, cursor, [0, None, 1]],
            ]
        else:
            # First page — try multiple variants like the Go library
            payloads = [
                [page_size, None, [1, None, 1]],
                [page_size, None, [0, None, 1]],
                [page_size, None, [0, None, 2]],
            ]

        all_items: list[ChatInfo] = []
        seen_cids: set[str] = set()
        last_cursor = ""

        for payload in payloads:
            items, next_cursor = await self._try_list_chats(payload)
            for item in items:
                if item.cid not in seen_cids:
                    seen_cids.add(item.cid)
                    all_items.append(item)
            if next_cursor:
                last_cursor = next_cursor
            if all_items:
                break  # got results, stop trying variants

        return ChatListPage(items=all_items, cursor=last_cursor)

    async def list_all_chats(self, limit: int = 100) -> list[ChatInfo]:
        """
        Auto-paginate to collect up to ``limit`` chats.

        Convenience wrapper around :meth:`list_chats_page` that follows
        cursors until the requested number of chats is reached or there
        are no more pages.

        Parameters
        ----------
        limit: `int`, optional
            Maximum number of chats to collect. Default is 100.

        Returns
        -------
        `list[ChatInfo]`
            Collected chat items (may be fewer than ``limit`` if the
            account has fewer chats).
        """
        all_items: list[ChatInfo] = []
        seen_cids: set[str] = set()
        cursor = ""
        page_size = min(limit, 20)

        while len(all_items) < limit:
            page = await self.list_chats_page(cursor=cursor, page_size=page_size)
            for item in page.items:
                if item.cid not in seen_cids:
                    seen_cids.add(item.cid)
                    all_items.append(item)
                    if len(all_items) >= limit:
                        break

            if not page.cursor:
                break  # no more pages
            cursor = page.cursor

        return all_items

    async def read_chat(self, cid: str, limit: int = 10) -> ChatHistory | None:
        """
        Fetch the complete conversation history by chat ID, ordered from the latest turn to the oldest.

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

        try:
            response = await self._batch_execute(
                [
                    RPCData(
                        rpcid=GRPC.READ_CHAT,
                        payload=json.dumps(
                            [cid, limit, None, 1, [1], [4], None, 1]
                        ).decode("utf-8"),
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

                    # Model turn
                    candidates_list = get_nested_value(conv_turn, [3, 0])
                    if candidates_list:
                        output_candidates = []
                        for candidate_data in candidates_list:
                            completion_status = get_nested_value(candidate_data, [8, 0])
                            has_progress_signal = (
                                get_nested_value(candidate_data, [12, 6, 0]) is not None
                            )

                            if completion_status == 2:
                                # Finished successfully
                                logger.debug(
                                    f"[read_chat] Gemini has successfully finalized the response for {cid!r}."
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
                            ) = self._parse_candidate(candidate_data, cid, rid, rcid)
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

                    # User turn
                    user_text = get_nested_value(conv_turn, [2, 0, 0], "")
                    if user_text:
                        chat_turns.append(ChatTurn(role="user", text=user_text))

                return ChatHistory(cid=cid, turns=chat_turns)

            return None
        except Exception:
            logger.debug(
                f"[read_chat] Response data for {cid!r} is still incomplete (model is still processing)..."
            )
            return None

    async def fetch_latest_chat_response(self, cid: str) -> ModelOutput | None:
        """
        Fetch the latest model response from a chat by its cid.

        ``read_chat`` returns turns newest-first, so the first model turn
        is the most recent response. Used by ``ResearchMixin`` for fallback
        recovery when a streaming request fails but the server may have
        already produced a response.

        Parameters
        ----------
        cid: `str`
            The chat ID to read (e.g. ``"c_..."``).

        Returns
        -------
        :class:`ModelOutput` | None
            The latest model output, or ``None`` if unavailable.
        """

        try:
            history = await self.read_chat(cid, limit=5)
            if not history or not history.turns:
                logger.debug(f"fetch_latest_chat_response({cid!r}): no turns")
                return None
            for turn in history.turns:  # newest-first
                if turn.role == "model" and turn.model_output:
                    logger.debug(
                        f"fetch_latest_chat_response({cid!r}): "
                        f"found model turn with {len(turn.text)} chars"
                    )
                    return turn.model_output
            logger.debug(f"fetch_latest_chat_response({cid!r}): no model turns")
            return None
        except Exception as e:
            logger.debug(
                f"fetch_latest_chat_response({cid!r}) failed: "
                f"{type(e).__name__}: {e}"
            )
            return None

    async def delete_chat(self, cid: str) -> None:
        """
        Delete a specific conversation by chat id.

        Parameters
        ----------
        cid: `str`
            The ID of the chat requiring deletion (e.g. "c_...").
        """

        await self._batch_execute(
            [
                RPCData(
                    rpcid=GRPC.DELETE_CHAT_1,
                    payload=json.dumps([cid]).decode("utf-8"),
                ),
            ]
        )
        await self._batch_execute(
            [
                RPCData(
                    rpcid=GRPC.DELETE_CHAT_2,
                    payload=json.dumps([cid, [1, None, 0, 1]]).decode("utf-8"),
                ),
            ]
        )
