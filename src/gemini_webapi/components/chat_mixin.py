from datetime import datetime

import orjson as json

from ..constants import GRPC
from ..types import Candidate, ConversationTurn, ModelOutput, RPCData
from ..utils import extract_json_from_response, get_nested_value, logger


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

        response = await self._batch_execute(
            [
                RPCData(
                    rpcid=GRPC.READ_CHAT,
                    payload=json.dumps(
                        [cid, max_turns, None, 1, [0], [4], None, 1]
                    ).decode("utf-8"),
                ),
            ]
        )

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
                logger.debug(f"_fetch_chat_turns({cid!r}) found {len(turns)} turns")
            return turns

        logger.warning(
            f"_fetch_chat_turns({cid!r}) parsed all parts but found no turns"
        )
        return None

    async def fetch_latest_chat_response(self, cid: str) -> ModelOutput | None:
        """
        Fetch the last assistant response from a conversation by chat id.

        Used for recovery when a stream fails after Gemini assigned a cid
        mid-stream. Returns None on any failure (network, parsing, empty response).

        Parameters
        ----------
        cid: `str`
            The ID of the conversation to read (e.g. "c_...").

        Returns
        -------
        :class:`ModelOutput` | None
            The recovered response, or None if recovery failed.
        """

        try:
            turns = await self._fetch_chat_turns(cid, max_turns=10)
            if not turns:
                return None

            conv_turn = turns[-1]
            if not conv_turn:
                logger.debug(
                    f"read_chat({cid!r}): turns[-1] is empty/None, "
                    f"num_turns={len(turns)}"
                )
                return None

            candidates_list = get_nested_value(conv_turn, [3, 0])
            if not candidates_list:
                turn3 = get_nested_value(conv_turn, [3])
                logger.debug(
                    f"read_chat({cid!r}): no candidates at [3][0], "
                    f"turn[3] type={type(turn3).__name__}, "
                    f"turn[3] preview={str(turn3)[:300]!r}"
                )
                return None

            candidate_data = get_nested_value(candidates_list, [0])
            if not candidate_data:
                logger.debug(
                    f"read_chat({cid!r}): candidates_list[0] empty, "
                    f"candidates_list len={len(candidates_list)}"
                )
                return None

            rcid = get_nested_value(candidate_data, [0], "")
            text = get_nested_value(candidate_data, [1, 0], "")

            if not text:
                logger.debug(
                    f"read_chat({cid!r}): candidate has empty text, "
                    f"rcid={rcid!r}, skipping"
                )
                return None

            turn_metadata = get_nested_value(conv_turn, [0])
            if isinstance(turn_metadata, list) and len(turn_metadata) >= 2:
                rid = turn_metadata[1] if isinstance(turn_metadata[1], str) else ""
            else:
                rid = ""
                logger.warning(
                    f"read_chat({cid!r}): could not extract rid from turn_metadata "
                    f"(type={type(turn_metadata).__name__}). "
                    f"Next continuation turn may use a stale rid."
                )

            metadata = [cid, rid] if rid else [cid]

            if self.verbose:
                logger.debug(
                    f"read_chat({cid!r}) SUCCESS: rcid={rcid!r}, rid={rid!r}, text_len={len(text)}"
                )
            return ModelOutput(
                metadata=metadata,
                candidates=[Candidate(rcid=rcid, text=text)],
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
