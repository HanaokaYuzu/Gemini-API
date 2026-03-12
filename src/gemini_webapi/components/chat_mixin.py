from datetime import datetime

import orjson as json

from ..constants import GRPC
from ..types import Candidate, ConversationTurn, ModelOutput, RPCData
from ..utils import extract_json_from_response, get_nested_value, iter_nested, logger


class ChatMixin:
    """
    Mixin class providing chat related functionality for GeminiClient.
    """

    async def _fetch_chat_turns(self, cid: str, max_turns: int = 10) -> list | None:
        """
        Fetch raw conversation turns for a chat by its id.

        Handles the RPC call and response parsing for reading chats.

        Returns
        -------
        `list | None`
            The raw turns list from the first valid response part, or None if no turns are found.
        """

        source_paths = [self._source_path(cid)]
        fallback_source = f"/app/{cid}"
        if fallback_source not in source_paths:
            source_paths.append(fallback_source)

        saw_reject_7 = False

        for source_path in source_paths:
            try:
                response = await self._batch_execute(
                    [
                        RPCData(
                            rpcid=GRPC.READ_CHAT,
                            payload=json.dumps(
                                [cid, max_turns, None, 1, [1], [4], None, 1]
                            ).decode("utf-8"),
                        ),
                    ],
                    source_path=source_path,
                    close_on_error=False,
                    current_retry=0,
                )
            except Exception as e:
                if self.verbose:
                    logger.debug(
                        f"_fetch_chat_turns({cid!r}) request failed with source_path={source_path!r}: {e}"
                    )
                continue

            if self.verbose:
                logger.debug(
                    f"_fetch_chat_turns({cid!r}) raw response: status={response.status_code}, "
                    f"len={len(response.text)}, first_500={response.text[:500]!r}"
                )

            response_json = extract_json_from_response(response.text)
            if self.verbose:
                logger.debug(
                    f"_fetch_chat_turns({cid!r}) parsed {len(response_json)} top-level parts"
                )

            reject_code = None
            for part in response_json:
                if get_nested_value(part, [0]) == "wrb.fr" and get_nested_value(part, [1]) == GRPC.READ_CHAT:
                    code = get_nested_value(part, [5, 0])
                    if isinstance(code, int):
                        reject_code = code
                        break

            if reject_code == 7:
                saw_reject_7 = True
                if self.verbose:
                    logger.debug(
                        f"_fetch_chat_turns({cid!r}) rejected with code=7 on source_path={source_path!r}"
                    )
                continue

            for i, part in enumerate(response_json):
                part_body_str = get_nested_value(part, [2])
                if not part_body_str:
                    if self.verbose:
                        logger.debug(f"_fetch_chat_turns part[{i}]: no body at [2]")
                    continue

                part_body = json.loads(part_body_str)
                turns = get_nested_value(part_body, [0])
                if not turns or not isinstance(turns, list):
                    if self.verbose:
                        logger.debug(
                            f"_fetch_chat_turns part[{i}]: no turns at [0], "
                            f"body type={type(part_body).__name__}"
                        )
                    continue

                if self.verbose:
                    logger.debug(
                        f"_fetch_chat_turns({cid!r}) found {len(turns)} turns (source_path={source_path!r})"
                    )
                return turns

        if saw_reject_7:
            logger.warning(
                f"_fetch_chat_turns({cid!r}) rejected by server (reject_code=7). "
                "Likely account mismatch or insufficient permission for this chat."
            )
        else:
            logger.warning(
                f"_fetch_chat_turns({cid!r}) parsed all parts but found no turns"
            )
        return None

    async def list_chats(
        self,
        cursor: str | None = None,
    ) -> dict:
        """
        List chat history summaries.

        Parameters
        ----------
        cursor: `str`, optional
            Pagination cursor returned by previous call.

        Returns
        -------
        `dict`
            {"cursor": str | None, "items": list[dict]} where each item contains
            chat id/title/update timestamp and lightweight metadata.
        """

        source_paths = [self._source_path()]
        if "/app" not in source_paths:
            source_paths.append("/app")

        def _extract_body_and_reject(response_text: str):
            response_json = extract_json_from_response(response_text)
            body = None
            reject_code = None
            for part in response_json:
                if get_nested_value(part, [0]) != "wrb.fr":
                    continue
                if get_nested_value(part, [1]) != GRPC.LIST_CHATS:
                    continue

                code = get_nested_value(part, [5, 0])
                if isinstance(code, int):
                    reject_code = code

                raw = get_nested_value(part, [2])
                if raw:
                    body = json.loads(raw)
                    break
            return body, reject_code

        def _collect_rows(node):
            rows = []
            if isinstance(node, list):
                if (
                    len(node) >= 2
                    and isinstance(node[0], str)
                    and node[0].startswith("c_")
                    and isinstance(node[1], str)
                ):
                    rows.append(node)
                for child in node:
                    rows.extend(_collect_rows(child))
            elif isinstance(node, dict):
                for child in node.values():
                    rows.extend(_collect_rows(child))
            return rows

        def _parse_rows(body):
            rows = []
            if isinstance(body, list) and len(body) > 2 and isinstance(body[2], list):
                rows = body[2]
            if not rows:
                rows = _collect_rows(body)

            seen = set()
            items = []
            for row in rows:
                if not isinstance(row, list):
                    continue

                cid = get_nested_value(row, [0], "")
                if not (isinstance(cid, str) and cid.startswith("c_")):
                    continue
                if cid in seen:
                    continue
                seen.add(cid)

                title = get_nested_value(row, [1], "")
                if not isinstance(title, str):
                    title = ""
                rid = get_nested_value(row, [6, 0, 1], "")
                if not isinstance(rid, str):
                    rid = ""

                ts_pair = get_nested_value(row, [5])
                if not (
                    isinstance(ts_pair, list)
                    and ts_pair
                    and isinstance(ts_pair[0], (int, float))
                ):
                    ts_pair = None

                ts = None
                if ts_pair:
                    try:
                        ts = datetime.fromtimestamp(ts_pair[0]).isoformat()
                    except (OSError, ValueError):
                        ts = None

                items.append(
                    {
                        "cid": cid,
                        "title": title,
                        "rid": rid,
                        "updated_at": ts,
                        "timestamp": ts_pair,
                        "kind": get_nested_value(row, [9]),
                    }
                )

            return items

        def _parse_cursor(body):
            if isinstance(body, list) and len(body) > 1 and isinstance(body[1], str):
                return body[1] or None
            return None

        payloads = []
        if cursor:
            payloads.append([20, cursor, [0, None, 1]])
        else:
            # Browser observed variants. Try all and return first non-empty list.
            payloads.extend(
                [
                    [13, None, [1, None, 1]],
                    [13, None, [0, None, 1]],
                    [13, None, [0, None, 2]],
                ]
            )

        last_cursor = cursor
        saw_reject_7 = False

        for source_path in source_paths:
            for payload_obj in payloads:
                payload = json.dumps(payload_obj).decode("utf-8")
                try:
                    response = await self._batch_execute(
                        [RPCData(rpcid=GRPC.LIST_CHATS, payload=payload)],
                        source_path=source_path,
                        close_on_error=False,
                        current_retry=0,
                    )
                except Exception as e:
                    if self.verbose:
                        logger.debug(
                            f"list_chats source_path={source_path} payload={payload_obj} failed: {e}"
                        )
                    continue

                body, reject_code = _extract_body_and_reject(response.text)
                if reject_code == 7:
                    saw_reject_7 = True
                    if self.verbose:
                        logger.debug(
                            f"list_chats source_path={source_path} payload={payload_obj} rejected with code=7"
                        )
                    continue

                if body is None:
                    continue

                parsed_cursor = _parse_cursor(body)
                if parsed_cursor:
                    last_cursor = parsed_cursor

                items = _parse_rows(body)
                if self.verbose:
                    logger.debug(
                        f"list_chats source_path={source_path} payload={payload_obj} -> "
                        f"items={len(items)}, cursor_present={bool(parsed_cursor)}"
                    )

                if items:
                    return {"cursor": parsed_cursor, "items": items}

        # Cursor-only response; try next-page form once.
        if not cursor and last_cursor:
            for source_path in source_paths:
                try:
                    response = await self._batch_execute(
                        [
                            RPCData(
                                rpcid=GRPC.LIST_CHATS,
                                payload=json.dumps([20, last_cursor, [0, None, 1]]).decode("utf-8"),
                            )
                        ],
                        source_path=source_path,
                        close_on_error=False,
                        current_retry=0,
                    )
                    body, reject_code = _extract_body_and_reject(response.text)
                    if reject_code == 7:
                        saw_reject_7 = True
                        continue
                    if body is not None:
                        items = _parse_rows(body)
                        parsed_cursor = _parse_cursor(body) or last_cursor
                        if items:
                            return {"cursor": parsed_cursor, "items": items}
                        last_cursor = parsed_cursor
                except Exception:
                    pass

        result = {"cursor": last_cursor, "items": []}
        if saw_reject_7:
            result["error"] = (
                "LIST_CHATS rejected with code=7. "
                "Likely account mismatch, disabled chat history, or insufficient permission."
            )
        return result

    async def fetch_latest_chat_response(self, cid: str) -> ModelOutput | None:
        """
        Fetch the latest assistant response from a conversation by chat id.

        Used for recovery when a stream fails after Gemini assigned a cid
        mid-stream. Returns None on any failure (network, parsing, empty response).
        """

        def _looks_human_text(s: str) -> bool:
            s = s.strip()
            if len(s) < 8:
                return False
            if s.startswith("http://") or s.startswith("https://"):
                return False

            visible = sum(
                1
                for ch in s
                if ch.isalpha() or ch.isdigit() or ch.isspace() or "\u4e00" <= ch <= "\u9fff"
            )
            return visible / max(len(s), 1) >= 0.45

        def _pick_best_text(candidate_node) -> str:
            # Legacy primary path.
            best_text = get_nested_value(candidate_node, [1, 0], "") or ""
            best_score = 0
            if isinstance(best_text, str) and best_text:
                best_score = len(best_text)

            for s in iter_nested(candidate_node):
                if not isinstance(s, str):
                    continue
                text = s.strip()
                if not _looks_human_text(text):
                    continue

                score = len(text)
                if text.startswith("#") or "\n## " in text:
                    score += 20000
                if "http://googleusercontent.com/immersive_entry_chip/0" in text:
                    score -= 500
                if "http://googleusercontent.com/deep_research_confirmation_content/0" in text:
                    score -= 500

                if score > best_score:
                    best_score = score
                    best_text = text

            return best_text if isinstance(best_text, str) else ""

        def _iter_candidates(node):
            if isinstance(node, list):
                if (
                    len(node) >= 2
                    and isinstance(node[0], str)
                    and node[0].startswith("rc_")
                ):
                    text = _pick_best_text(node)
                    if isinstance(text, str):
                        yield node[0], text
                for child in node:
                    yield from _iter_candidates(child)
            elif isinstance(node, dict):
                for child in node.values():
                    yield from _iter_candidates(child)

        try:
            turns = await self._fetch_chat_turns(cid, max_turns=10)
            if not turns:
                return None

            best = None
            scanned = 0

            # Server order is newest-first. Keep a small recency bonus.
            for turn_idx, conv_turn in enumerate(turns):
                if not conv_turn:
                    continue

                turn_metadata = get_nested_value(conv_turn, [0])
                rid = (
                    turn_metadata[1]
                    if isinstance(turn_metadata, list)
                    and len(turn_metadata) >= 2
                    and isinstance(turn_metadata[1], str)
                    else ""
                )

                turn_candidates = list(_iter_candidates(get_nested_value(conv_turn, [3])))
                if not turn_candidates:
                    # Fallback to legacy path shape
                    candidate_data = get_nested_value(conv_turn, [3, 0, 0])
                    rcid = get_nested_value(candidate_data, [0], "") if candidate_data else ""
                    text = get_nested_value(candidate_data, [1, 0], "") if candidate_data else ""
                    if rcid and isinstance(text, str):
                        turn_candidates = [(rcid, text)]

                for rcid, text in turn_candidates:
                    if not text:
                        continue
                    scanned += 1
                    low = text.lower()
                    score = len(text) + (1000 - turn_idx)

                    # Prefer final/completed report over "starting" placeholder.
                    if (
                        "我已经完成了研究" in text
                        or "i have completed the research" in low
                        or "i've completed the research" in low
                    ):
                        score += 1_000_000
                    if (
                        "我这就开始" in text
                        or "you can leave this chat" in low
                        or "in the meantime, you can leave this chat" in low
                    ):
                        score -= 50_000

                    if best is None or score > best["score"]:
                        best = {
                            "score": score,
                            "rcid": rcid,
                            "rid": rid,
                            "text": text,
                        }

            if not best:
                logger.debug(f"read_chat({cid!r}): no usable assistant candidate found")
                return None

            metadata = [cid, best["rid"]] if best["rid"] else [cid]
            if self.verbose:
                logger.debug(
                    f"read_chat({cid!r}) SUCCESS: rcid={best['rcid']!r}, rid={best['rid']!r}, "
                    f"text_len={len(best['text'])}, candidates_scanned={scanned}"
                )

            return ModelOutput(
                metadata=metadata,
                candidates=[Candidate(rcid=best["rcid"], text=best["text"])],
            )
        except (json.JSONDecodeError, ValueError, KeyError, IndexError) as e:
            logger.warning(f"read_chat({cid!r}) parse error: {type(e).__name__}: {e}")
            return None
        except Exception as e:
            logger.error(
                f"read_chat({cid!r}) unexpected error: {type(e).__name__}: {e}",
                exc_info=True,
            )
            return None

    async def read_chat_raw(self, cid: str, max_turns: int = 10) -> list | None:
        """
        Return raw turns payload as returned by READ_CHAT RPC.
        """

        return await self._fetch_chat_turns(cid, max_turns=max_turns)

    async def read_chat(self, cid: str, max_turns: int = 100) -> list[ConversationTurn]:
        """
        Fetch the full conversation history for a chat by its id.

        Returns all user + assistant turns in chronological order (oldest first).

        Parameters
        ----------
        cid: `str`
            The ID of the conversation to read (e.g. "c_...").
        max_turns: `int`, optional
            Maximum number of turns to request from the server, by default 100.

        Returns
        -------
        :class:`list[ConversationTurn]`
            List of conversation turns in chronological order. Empty list if
            the conversation has no turns or parsing fails.
        """

        try:
            turns = await self._fetch_chat_turns(cid, max_turns=max_turns)
            if not turns:
                return []

            result: list[ConversationTurn] = []

            for turn in turns:
                if not isinstance(turn, list) or len(turn) < 4:
                    continue

                # [0] = [cid, rid]
                turn_meta = get_nested_value(turn, [0])
                rid = (
                    get_nested_value(turn_meta, [1], "")
                    if isinstance(turn_meta, list)
                    else ""
                )

                # [2][0][0] = user prompt text
                user_prompt = get_nested_value(turn, [2, 0, 0], "")

                # [3][0][0] = first candidate
                candidate_data = get_nested_value(turn, [3, 0, 0])
                if not candidate_data:
                    continue

                rcid = get_nested_value(candidate_data, [0], "")
                text = get_nested_value(candidate_data, [1, 0], "")

                if not text:
                    continue

                # [37][0][0] = thoughts (thinking models)
                thoughts = get_nested_value(candidate_data, [37, 0, 0]) or None

                # [4] = [epoch_seconds, nanoseconds]
                ts_data = get_nested_value(turn, [4])
                timestamp = None
                if (
                    isinstance(ts_data, list)
                    and ts_data
                    and isinstance(ts_data[0], (int, float))
                ):
                    try:
                        timestamp = datetime.fromtimestamp(ts_data[0])
                    except (OSError, ValueError):
                        pass

                result.append(
                    ConversationTurn(
                        rid=rid,
                        user_prompt=user_prompt,
                        assistant_response=text,
                        rcid=rcid,
                        thoughts=thoughts,
                        timestamp=timestamp,
                    )
                )

            # Reverse to chronological order (server returns newest-first)
            result.reverse()
            return result
        except (json.JSONDecodeError, ValueError, KeyError, IndexError) as e:
            logger.warning(
                f"read_chat_history({cid!r}) parse error: {type(e).__name__}: {e}"
            )
            return []
        except Exception as e:
            logger.error(
                f"read_chat_history({cid!r}) unexpected error: {type(e).__name__}: {e}",
                exc_info=True,
            )
            return []

    async def delete_chat(self, cid: str) -> None:
        """
        Delete a specific conversation from Gemini history by chat id.

        Parameters
        ----------
        cid: `str`
            The ID of the chat requiring deletion (e.g. "c_...").
        """

        await self._batch_execute(
            [
                RPCData(
                    rpcid=GRPC.DELETE_CHAT,
                    payload=json.dumps([cid]).decode("utf-8"),
                ),
            ]
        )
