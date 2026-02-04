import asyncio
import codecs
import io
import random
import re
from asyncio import Task
from pathlib import Path
from typing import Any, AsyncGenerator, Optional

import orjson as json
from httpx import AsyncClient, Cookies, ReadTimeout, Response

from .components import GemMixin
from .constants import Endpoint, ErrorCode, GRPC, Headers, Model
from .exceptions import (
    APIError,
    AuthError,
    GeminiError,
    ModelInvalid,
    TemporarilyBlocked,
    TimeoutError,
    UsageLimitExceeded,
)
from .types import (
    Candidate,
    Gem,
    GeneratedImage,
    ModelOutput,
    RPCData,
    WebImage,
)
from .utils import (
    get_access_token,
    get_nested_value,
    logger,
    parse_file_name,
    parse_stream_frames,
    rotate_1psidts,
    running,
    upload_file,
)


class GeminiClient(GemMixin):
    """
    Async httpx client interface for gemini.google.com.

    `secure_1psid` must be provided unless the optional dependency `browser-cookie3` is installed, and
    you have logged in to google.com in your local browser.

    Parameters
    ----------
    secure_1psid: `str`, optional
        __Secure-1PSID cookie value.
    secure_1psidts: `str`, optional
        __Secure-1PSIDTS cookie value, some Google accounts don't require this value, provide only if it's in the cookie list.
    proxy: `str`, optional
        Proxy URL.
    kwargs: `dict`, optional
        Additional arguments which will be passed to the http client.
        Refer to `httpx.AsyncClient` for more information.

    Raises
    ------
    `ValueError`
        If `browser-cookie3` is installed but cookies for google.com are not found in your local browser storage.
    """

    __slots__ = [
        "cookies",
        "proxy",
        "_running",
        "client",
        "access_token",
        "build_label",
        "session_id",
        "timeout",
        "auto_close",
        "close_delay",
        "close_task",
        "auto_refresh",
        "refresh_interval",
        "refresh_task",
        "verbose",
        "_lock",
        "_reqid",
        "_gems",  # From GemMixin
        "kwargs",
    ]

    def __init__(
        self,
        secure_1psid: str | None = None,
        secure_1psidts: str | None = None,
        proxy: str | None = None,
        **kwargs,
    ):
        super().__init__()
        self.cookies = Cookies()
        self.proxy = proxy
        self._running: bool = False
        self.client: AsyncClient | None = None
        self.access_token: str | None = None
        self.build_label: str | None = None
        self.session_id: str | None = None
        self.timeout: float = 300
        self.auto_close: bool = False
        self.close_delay: float = 300
        self.close_task: Task | None = None
        self.auto_refresh: bool = True
        self.refresh_interval: float = 540
        self.refresh_task: Task | None = None
        self.verbose: bool = True
        self._lock = asyncio.Lock()
        self._reqid: int = random.randint(10000, 99999)
        self.kwargs = kwargs

        if secure_1psid:
            self.cookies.set("__Secure-1PSID", secure_1psid, domain=".google.com")
            if secure_1psidts:
                self.cookies.set(
                    "__Secure-1PSIDTS", secure_1psidts, domain=".google.com"
                )

    async def init(
        self,
        timeout: float = 300,
        auto_close: bool = False,
        close_delay: float = 300,
        auto_refresh: bool = True,
        refresh_interval: float = 540,
        verbose: bool = True,
    ) -> None:
        """
        Get SNlM0e value as access token. Without this token posting will fail with 400 bad request.

        Parameters
        ----------
        timeout: `float`, optional
            Request timeout of the client in seconds. Used to limit the max waiting time when sending a request.
        auto_close: `bool`, optional
            If `True`, the client will close connections and clear resource usage after a certain period
            of inactivity. Useful for always-on services.
        close_delay: `float`, optional
            Time to wait before auto-closing the client in seconds. Effective only if `auto_close` is `True`.
        auto_refresh: `bool`, optional
            If `True`, will schedule a task to automatically refresh cookies and access token in the background.
        refresh_interval: `float`, optional
            Time interval for background cookie and access token refresh in seconds. Effective only if `auto_refresh` is `True`.
        verbose: `bool`, optional
            If `True`, will print more infomation in logs.
        """

        async with self._lock:
            if self._running:
                return

            try:
                self.verbose = verbose
                access_token, build_label, session_id, valid_cookies = (
                    await get_access_token(
                        base_cookies=self.cookies,
                        proxy=self.proxy,
                        verbose=self.verbose,
                        verify=self.kwargs.get("verify", True),
                    )
                )

                self.client = AsyncClient(
                    http2=True,
                    timeout=timeout,
                    proxy=self.proxy,
                    follow_redirects=True,
                    headers=Headers.GEMINI.value,
                    cookies=valid_cookies,
                    **self.kwargs,
                )
                self.access_token = access_token
                self.cookies = valid_cookies
                self.build_label = build_label
                self.session_id = session_id
                self._running = True

                self.timeout = timeout
                self.auto_close = auto_close
                self.close_delay = close_delay
                if self.auto_close:
                    await self.reset_close_task()

                self.auto_refresh = auto_refresh
                self.refresh_interval = refresh_interval

                if self.refresh_task:
                    self.refresh_task.cancel()
                    self.refresh_task = None

                if self.auto_refresh:
                    self.refresh_task = asyncio.create_task(self.start_auto_refresh())

                if self.verbose:
                    logger.success("Gemini client initialized successfully.")
            except Exception:
                await self.close()
                raise

    async def close(self, delay: float = 0) -> None:
        """
        Close the client after a certain period of inactivity, or call manually to close immediately.

        Parameters
        ----------
        delay: `float`, optional
            Time to wait before closing the client in seconds.
        """

        if delay:
            await asyncio.sleep(delay)

        self._running = False

        if self.close_task:
            self.close_task.cancel()
            self.close_task = None

        if self.refresh_task:
            self.refresh_task.cancel()
            self.refresh_task = None

        if self.client:
            await self.client.aclose()

    async def reset_close_task(self) -> None:
        """
        Reset the timer for closing the client when a new request is made.
        """

        if self.close_task:
            self.close_task.cancel()
            self.close_task = None

        self.close_task = asyncio.create_task(self.close(self.close_delay))

    async def start_auto_refresh(self) -> None:
        """
        Start the background task to automatically refresh cookies.
        """
        if self.refresh_interval < 60:
            self.refresh_interval = 60

        while self._running:
            await asyncio.sleep(self.refresh_interval)

            if not self._running:
                break

            try:
                async with self._lock:
                    # Refresh all cookies in the background to keep the session alive.
                    new_1psidts, rotated_cookies = await rotate_1psidts(
                        self.cookies, self.proxy
                    )
                    if rotated_cookies:
                        self.cookies.update(rotated_cookies)
                        if self.client:
                            self.client.cookies.update(rotated_cookies)

                    if new_1psidts:
                        if rotated_cookies:
                            logger.debug("Cookies refreshed (network update).")
                        else:
                            logger.debug("Cookies are up to date (cached).")
                    else:
                        logger.warning(
                            "Rotation response did not contain a new __Secure-1PSIDTS. "
                            "Session might expire soon if this persists."
                        )
            except asyncio.CancelledError:
                raise
            except AuthError:
                logger.warning(
                    "AuthError: Failed to refresh cookies. Retrying in next interval."
                )
            except Exception as e:
                logger.warning(f"Unexpected error while refreshing cookies: {e}")

    async def generate_content(
        self,
        prompt: str,
        files: list[str | Path | bytes | io.BytesIO] | None = None,
        model: Model | str | dict = Model.UNSPECIFIED,
        gem: Gem | str | None = None,
        chat: Optional["ChatSession"] = None,
        **kwargs,
    ) -> ModelOutput:
        """
        Generates contents with prompt.

        Parameters
        ----------
        prompt: `str`
            Prompt provided by user.
        files: `list[str | Path]`, optional
            List of file paths to be attached.
        model: `Model | str | dict`, optional
            Specify the model to use for generation.
            Pass either a `gemini_webapi.constants.Model` enum or a model name string to use predefined models.
            Pass a dictionary to use custom model header strings ("model_name" and "model_header" keys must be provided).
        gem: `Gem | str`, optional
            Specify a gem to use as system prompt for the chat session.
            Pass either a `gemini_webapi.types.Gem` object or a gem id string.
        chat: `ChatSession`, optional
            Chat data to retrieve conversation history. If None, will automatically generate a new chat id when sending post request.
        kwargs: `dict`, optional
            Additional arguments which will be passed to the post request.
            Refer to `httpx.AsyncClient.request` for more information.

        Returns
        -------
        :class:`ModelOutput`
            Output data from gemini.google.com, use `ModelOutput.text` to get the default text reply, `ModelOutput.images` to get a list
            of images in the default reply, `ModelOutput.candidates` to get a list of all answer candidates in the output.

        Raises
        ------
        `AssertionError`
            If prompt is empty.
        `gemini_webapi.TimeoutError`
            If request timed out.
        `gemini_webapi.GeminiError`
            If no reply candidate found in response.
        `gemini_webapi.APIError`
            - If request failed with status code other than 200.
            - If response structure is invalid and failed to parse.
        """

        if self.auto_close:
            await self.reset_close_task()

        if not (isinstance(chat, ChatSession) and chat.cid):
            self._reqid = random.randint(10000, 99999)

        file_data = None
        if files:
            await self._batch_execute(
                [
                    RPCData(
                        rpcid=GRPC.BARD_ACTIVITY,
                        payload='[[["bard_activity_enabled"]]]',
                    )
                ]
            )

            uploaded_urls = await asyncio.gather(
                *(upload_file(file, self.proxy) for file in files)
            )
            file_data = [
                [[url], parse_file_name(file)]
                for url, file in zip(uploaded_urls, files)
            ]

        try:
            await self._batch_execute(
                [
                    RPCData(
                        rpcid=GRPC.BARD_ACTIVITY,
                        payload='[[["bard_activity_enabled"]]]',
                    )
                ]
            )

            output = None
            async for output in self._generate(
                prompt=prompt,
                req_file_data=file_data,
                model=model,
                gem=gem,
                chat=chat,
                **kwargs,
            ):
                pass

            if output is None:
                raise GeminiError(
                    "Failed to generate contents. No output data found in response."
                )

            if isinstance(chat, ChatSession):
                chat.last_output = output

            return output

        finally:
            if files:
                for file in files:
                    if isinstance(file, io.BytesIO):
                        file.close()

    async def generate_content_stream(
        self,
        prompt: str,
        files: list[str | Path | bytes | io.BytesIO] | None = None,
        model: Model | str | dict = Model.UNSPECIFIED,
        gem: Gem | str | None = None,
        chat: Optional["ChatSession"] = None,
        **kwargs,
    ) -> AsyncGenerator[ModelOutput, None]:
        """
        Generates contents with prompt in streaming mode.

        This method sends a request to Gemini and yields partial responses as they arrive.
        It automatically calculates the text delta (new characters) to provide a smooth
        streaming experience. It also continuously updates chat metadata and candidate IDs.

        Parameters
        ----------
        prompt: `str`
            Prompt provided by user.
        files: `list[str | Path | bytes | io.BytesIO]`, optional
            List of file paths or byte streams to be attached.
        model: `Model | str | dict`, optional
            Specify the model to use for generation.
        gem: `Gem | str`, optional
            Specify a gem to use as system prompt for the chat session.
        chat: `ChatSession`, optional
            Chat data to retrieve conversation history.
        kwargs: `dict`, optional
            Additional arguments passed to `httpx.AsyncClient.stream`.

        Yields
        ------
        :class:`ModelOutput`
            Partial output data. The `text` attribute contains only the NEW characters
            received since the last yield.

        Raises
        ------
        `gemini_webapi.APIError`
            If the request fails or response structure is invalid.
        `gemini_webapi.TimeoutError`
            If the stream request times out.
        """

        if self.auto_close:
            await self.reset_close_task()

        if not (isinstance(chat, ChatSession) and chat.cid):
            self._reqid = random.randint(10000, 99999)

        file_data = None
        if files:
            await self._batch_execute(
                [
                    RPCData(
                        rpcid=GRPC.BARD_ACTIVITY,
                        payload='[[["bard_activity_enabled"]]]',
                    )
                ]
            )

            uploaded_urls = await asyncio.gather(
                *(upload_file(file, self.proxy) for file in files)
            )
            file_data = [
                [[url], parse_file_name(file)]
                for url, file in zip(uploaded_urls, files)
            ]

        try:
            await self._batch_execute(
                [
                    RPCData(
                        rpcid=GRPC.BARD_ACTIVITY,
                        payload='[[["bard_activity_enabled"]]]',
                    )
                ]
            )

            output = None
            async for output in self._generate(
                prompt=prompt,
                req_file_data=file_data,
                model=model,
                gem=gem,
                chat=chat,
                **kwargs,
            ):
                yield output

            if output and isinstance(chat, ChatSession):
                chat.last_output = output

        finally:
            if files:
                for file in files:
                    if isinstance(file, io.BytesIO):
                        file.close()

    @running(retry=5)
    async def _generate(
        self,
        prompt: str,
        req_file_data: list[Any] | None = None,
        model: Model | str | dict = Model.UNSPECIFIED,
        gem: Gem | str | None = None,
        chat: Optional["ChatSession"] = None,
        **kwargs,
    ) -> AsyncGenerator[ModelOutput, None]:
        """
        Internal method which actually sends content generation requests.
        """

        assert prompt, "Prompt cannot be empty."

        if isinstance(model, str):
            model = Model.from_name(model)
        elif isinstance(model, dict):
            model = Model.from_dict(model)
        elif not isinstance(model, Model):
            raise TypeError(
                f"'model' must be a `gemini_webapi.constants.Model` instance, "
                f"string, or dictionary; got `{type(model).__name__}`"
            )

        _reqid = self._reqid
        self._reqid += 100000

        gem_id = gem.id if isinstance(gem, Gem) else gem

        try:
            message_content = [
                prompt,
                0,
                None,
                req_file_data,
                None,
                None,
                0,
            ]

            params: dict[str, Any] = {"_reqid": _reqid, "rt": "c"}
            if self.build_label:
                params["bl"] = self.build_label
            if self.session_id:
                params["f.sid"] = self.session_id

            inner_req_list: list[Any] = [None] * 69
            inner_req_list[0] = message_content
            inner_req_list[2] = (
                chat.metadata
                if chat
                else ["", "", "", None, None, None, None, None, None, ""]
            )
            inner_req_list[7] = 1  # Enable Snapshot Streaming
            if gem_id:
                inner_req_list[19] = gem_id

            request_data = {
                "at": self.access_token,
                "f.req": json.dumps(
                    [
                        None,
                        json.dumps(inner_req_list).decode("utf-8"),
                    ]
                ).decode("utf-8"),
            }

            async with self.client.stream(
                "POST",
                Endpoint.GENERATE,
                params=params,
                headers=model.model_header,
                data=request_data,
                **kwargs,
            ) as response:
                if response.status_code != 200:
                    await self.close()
                    raise APIError(
                        f"Failed to generate contents. Status: {response.status_code}"
                    )

                if self.client:
                    self.cookies.update(self.client.cookies)

                buffer = ""
                decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")

                # Track last seen content for each candidate by rcid
                last_texts: dict[str, str] = {}
                last_thoughts: dict[str, str] = {}

                is_busy = False
                has_candidates = False

                async for chunk in response.aiter_bytes():
                    buffer += decoder.decode(chunk, final=False)
                    if buffer.startswith(")]}'"):
                        buffer = buffer[4:].lstrip()

                    parsed_parts, buffer = parse_stream_frames(buffer)

                    for part in parsed_parts:
                        part_json = None
                        # 0. Update chat metadata first whenever available to support follow-up polls
                        inner_json_str = get_nested_value(part, [2])
                        if inner_json_str:
                            try:
                                part_json = json.loads(inner_json_str)
                                m_data = get_nested_value(part_json, [1])
                                if m_data and isinstance(chat, ChatSession):
                                    chat.metadata = m_data

                                # Update context string from index 25 if available
                                context_str = get_nested_value(part_json, [25])
                                if isinstance(context_str, str) and isinstance(
                                    chat, ChatSession
                                ):
                                    chat.metadata = [None] * 9 + [context_str]
                            except json.JSONDecodeError:
                                pass

                        # 1. Check for fatal error codes in any part
                        error_code = get_nested_value(part, [5, 2, 0, 1, 0])
                        if error_code:
                            await self.close()
                            match error_code:
                                case ErrorCode.USAGE_LIMIT_EXCEEDED:
                                    raise UsageLimitExceeded(
                                        f"Usage limit exceeded for model '{model.model_name}'. Please wait a few minutes, "
                                        "switch to a different model (e.g., Gemini Flash), or check your account limits on gemini.google.com."
                                    )
                                case ErrorCode.MODEL_INCONSISTENT:
                                    raise ModelInvalid(
                                        "The specified model is inconsistent with the conversation history. "
                                        "Please ensure you are using the same 'model' parameter throughout the entire ChatSession."
                                    )
                                case ErrorCode.MODEL_HEADER_INVALID:
                                    raise ModelInvalid(
                                        f"The model '{model.model_name}' is currently unavailable or the request structure is outdated. "
                                        "Please update 'gemini_webapi' to the latest version or report this on GitHub if the problem persists."
                                    )
                                case ErrorCode.IP_TEMPORARILY_BLOCKED:
                                    raise TemporarilyBlocked(
                                        "Your IP address has been temporarily flagged or blocked by Google. "
                                        "Please try using a proxy, a different network, or wait for a while before retrying."
                                    )
                                case _:
                                    raise APIError(
                                        f"Failed to generate contents (stream). Unknown API error code: {error_code}. "
                                        "This might be a temporary Google service issue."
                                    )

                        # 2. Detect if model is busy analyzing data (Thinking state)
                        if "data_analysis_tool" in str(part):
                            is_busy = True
                            if not has_candidates:
                                logger.debug("Model is busy (thinking/analyzing)...")

                        # 3. Check for queueing status
                        status = get_nested_value(part, [5])
                        if isinstance(status, list) and status:
                            is_busy = True
                            if not has_candidates:
                                logger.debug(
                                    "Model is in a waiting state (queueing)..."
                                )

                        if not inner_json_str:
                            continue

                        try:
                            if part_json is None:
                                part_json = json.loads(inner_json_str)

                            # Extract data from candidates
                            candidates_list = get_nested_value(part_json, [4], [])
                            if not candidates_list:
                                continue

                            output_candidates = []
                            any_changed = False

                            for candidate_data in candidates_list:
                                rcid = get_nested_value(candidate_data, [0])
                                if not rcid:
                                    continue

                                if isinstance(chat, ChatSession):
                                    chat.rcid = rcid

                                # Text output and thoughts
                                text = get_nested_value(candidate_data, [1, 0], "")
                                if re.match(
                                    r"^http://googleusercontent\.com/card_content/\d+",
                                    text,
                                ):
                                    text = (
                                        get_nested_value(candidate_data, [22, 0])
                                        or text
                                    )

                                # Cleanup googleusercontent artifacts
                                text = re.sub(
                                    r"http://googleusercontent\.com/\w+/\d+\n*",
                                    "",
                                    text,
                                ).rstrip()

                                thoughts = (
                                    get_nested_value(candidate_data, [37, 0, 0]) or ""
                                )

                                # Web images
                                web_images = []
                                for web_img_data in get_nested_value(
                                    candidate_data, [12, 1], []
                                ):
                                    url = get_nested_value(web_img_data, [0, 0, 0])
                                    if url:
                                        web_images.append(
                                            WebImage(
                                                url=url,
                                                title=get_nested_value(
                                                    web_img_data, [7, 0], ""
                                                ),
                                                alt=get_nested_value(
                                                    web_img_data, [0, 4], ""
                                                ),
                                                proxy=self.proxy,
                                            )
                                        )

                                # Generated images
                                generated_images = []
                                for gen_img_data in get_nested_value(
                                    candidate_data, [12, 7, 0], []
                                ):
                                    url = get_nested_value(gen_img_data, [0, 3, 3])
                                    if url:
                                        img_num = get_nested_value(gen_img_data, [3, 6])
                                        alt_list = get_nested_value(
                                            gen_img_data, [3, 5], []
                                        )
                                        generated_images.append(
                                            GeneratedImage(
                                                url=url,
                                                title=(
                                                    f"[Generated Image {img_num}]"
                                                    if img_num
                                                    else "[Generated Image]"
                                                ),
                                                alt=get_nested_value(alt_list, [0], ""),
                                                proxy=self.proxy,
                                                cookies=self.cookies,
                                            )
                                        )

                                # Calculate Deltas for this specific candidate
                                last_text = last_texts.get(rcid, "")
                                last_thought = last_thoughts.get(rcid, "")

                                text_delta = text
                                if text.startswith(last_text):
                                    text_delta = text[len(last_text) :]

                                thoughts_delta = thoughts
                                if thoughts.startswith(last_thought):
                                    thoughts_delta = thoughts[len(last_thought) :]

                                if (
                                    text_delta
                                    or thoughts_delta
                                    or web_images
                                    or generated_images
                                ):
                                    any_changed = True

                                last_texts[rcid] = text
                                last_thoughts[rcid] = thoughts

                                output_candidates.append(
                                    Candidate(
                                        rcid=rcid,
                                        text=text,
                                        text_delta=text_delta,
                                        thoughts=thoughts or None,
                                        thoughts_delta=thoughts_delta,
                                        web_images=web_images,
                                        generated_images=generated_images,
                                    )
                                )

                            if any_changed:
                                has_candidates = True
                                yield ModelOutput(
                                    metadata=get_nested_value(part_json, [1], []),
                                    candidates=output_candidates,
                                )
                        except json.JSONDecodeError:
                            continue

                if is_busy and not has_candidates:
                    raise APIError("Model is busy. Polling again...")

        except ReadTimeout:
            raise TimeoutError(
                "The request timed out while waiting for Gemini to respond. This often happens with very long prompts "
                "or complex file analysis. Try increasing the 'timeout' value when initializing GeminiClient."
            )
        except (GeminiError, APIError):
            raise
        except Exception as e:
            logger.debug(
                f"{type(e).__name__}: {e}; Unexpected response or parsing error. Response: {locals().get('response', 'N/A')}"
            )
            raise APIError(f"Failed to parse response body: {e}")

    def start_chat(self, **kwargs) -> "ChatSession":
        """
        Returns a `ChatSession` object attached to this client.

        Parameters
        ----------
        kwargs: `dict`, optional
            Additional arguments which will be passed to the chat session.
            Refer to `gemini_webapi.ChatSession` for more information.

        Returns
        -------
        :class:`ChatSession`
            Empty chat session object for retrieving conversation history.
        """

        return ChatSession(geminiclient=self, **kwargs)

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
                    rpcid=GRPC.DELETE_CHAT,
                    payload=json.dumps([cid]),
                ),
            ]
        )

    @running(retry=2)
    async def _batch_execute(self, payloads: list[RPCData], **kwargs) -> Response:
        """
        Execute a batch of requests to Gemini API.

        Parameters
        ----------
        payloads: `list[RPCData]`
            List of `gemini_webapi.types.RPCData` objects to be executed.
        kwargs: `dict`, optional
            Additional arguments which will be passed to the post request.
            Refer to `httpx.AsyncClient.request` for more information.

        Returns
        -------
        :class:`httpx.Response`
            Response object containing the result of the batch execution.
        """

        _reqid = self._reqid
        self._reqid += 100000

        try:
            params: dict[str, Any] = {
                "rpcids": ",".join([p.rpcid for p in payloads]),
                "_reqid": _reqid,
                "rt": "c",
                "source-path": "/app",
            }
            if self.build_label:
                params["bl"] = self.build_label
            if self.session_id:
                params["f.sid"] = self.session_id

            response = await self.client.post(
                Endpoint.BATCH_EXEC,
                params=params,
                data={
                    "at": self.access_token,
                    "f.req": json.dumps(
                        [[payload.serialize() for payload in payloads]]
                    ).decode("utf-8"),
                },
                **kwargs,
            )
        except ReadTimeout:
            raise TimeoutError(
                "The request timed out while waiting for Gemini to respond. This often happens with very long prompts "
                "or complex file analysis. Try increasing the 'timeout' value when initializing GeminiClient."
            )

        if response.status_code != 200:
            await self.close()
            raise APIError(
                f"Batch execution failed with status code {response.status_code}"
            )

        if self.client:
            self.cookies.update(self.client.cookies)

        return response


class ChatSession:
    """
    Chat data to retrieve conversation history. Only if all 3 ids are provided will the conversation history be retrieved.

    Parameters
    ----------
    geminiclient: `GeminiClient`
        Async httpx client interface for gemini.google.com.
    metadata: `list[str]`, optional
        List of chat metadata `[cid, rid, rcid]`, can be shorter than 3 elements, like `[cid, rid]` or `[cid]` only.
    cid: `str`, optional
        Chat id, if provided together with metadata, will override the first value in it.
    rid: `str`, optional
        Reply id, if provided together with metadata, will override the second value in it.
    rcid: `str`, optional
        Reply candidate id, if provided together with metadata, will override the third value in it.
    model: `Model | str | dict`, optional
        Specify the model to use for generation.
        Pass either a `gemini_webapi.constants.Model` enum or a model name string to use predefined models.
        Pass a dictionary to use custom model header strings ("model_name" and "model_header" keys must be provided).
    gem: `Gem | str`, optional
        Specify a gem to use as system prompt for the chat session.
        Pass either a `gemini_webapi.types.Gem` object or a gem id string.
    """

    __slots__ = [
        "__metadata",
        "geminiclient",
        "last_output",
        "model",
        "gem",
    ]

    def __init__(
        self,
        geminiclient: GeminiClient,
        metadata: list[str | None] | None = None,
        cid: str | None = None,  # chat id
        rid: str | None = None,  # reply id
        rcid: str | None = None,  # reply candidate id
        model: Model | str | dict = Model.UNSPECIFIED,
        gem: Gem | str | None = None,
    ):
        self.__metadata: list[str | None] = [
            "",
            "",
            "",
            None,
            None,
            None,
            None,
            None,
            None,
            "",
        ]
        self.geminiclient: GeminiClient = geminiclient
        self.last_output: ModelOutput | None = None
        self.model: Model | str | dict = model
        self.gem: Gem | str | None = gem

        if metadata:
            self.metadata = metadata
        if cid:
            self.cid = cid
        if rid:
            self.rid = rid
        if rcid:
            self.rcid = rcid

    def __str__(self):
        return f"ChatSession(cid='{self.cid}', rid='{self.rid}', rcid='{self.rcid}')"

    __repr__ = __str__

    def __setattr__(self, name: str, value: Any) -> None:
        super().__setattr__(name, value)
        # update conversation history when last output is updated
        if name == "last_output" and isinstance(value, ModelOutput):
            self.metadata = value.metadata
            self.rcid = value.rcid

    async def send_message(
        self,
        prompt: str,
        files: list[str | Path] | None = None,
        **kwargs,
    ) -> ModelOutput:
        """
        Generates contents with prompt.
        Use as a shortcut for `GeminiClient.generate_content(prompt, image, self)`.

        Parameters
        ----------
        prompt: `str`
            Prompt provided by user.
        files: `list[str | Path]`, optional
            List of file paths to be attached.
        kwargs: `dict`, optional
            Additional arguments which will be passed to the post request.
            Refer to `httpx.AsyncClient.request` for more information.

        Returns
        -------
        :class:`ModelOutput`
            Output data from gemini.google.com, use `ModelOutput.text` to get the default text reply, `ModelOutput.images` to get a list
            of images in the default reply, `ModelOutput.candidates` to get a list of all answer candidates in the output.

        Raises
        ------
        `AssertionError`
            If prompt is empty.
        `gemini_webapi.TimeoutError`
            If request timed out.
        `gemini_webapi.GeminiError`
            If no reply candidate found in response.
        `gemini_webapi.APIError`
            - If request failed with status code other than 200.
            - If response structure is invalid and failed to parse.
        """

        return await self.geminiclient.generate_content(
            prompt=prompt,
            files=files,
            model=self.model,
            gem=self.gem,
            chat=self,
            **kwargs,
        )

    async def send_message_stream(
        self,
        prompt: str,
        files: list[str | Path] | None = None,
        **kwargs,
    ) -> AsyncGenerator[ModelOutput, None]:
        """
        Generates contents with prompt in streaming mode within this chat session.

        This is a shortcut for `GeminiClient.generate_content_stream(prompt, files, self)`.
        The session's metadata and conversation history are automatically managed.

        Parameters
        ----------
        prompt: `str`
            Prompt provided by user.
        files: `list[str | Path]`, optional
            List of file paths to be attached.
        kwargs: `dict`, optional
            Additional arguments passed to the streaming request.

        Yields
        ------
        :class:`ModelOutput`
            Partial output data containing text deltas.
        """

        async for output in self.geminiclient.generate_content_stream(
            prompt=prompt,
            files=files,
            model=self.model,
            gem=self.gem,
            chat=self,
            **kwargs,
        ):
            yield output

    def choose_candidate(self, index: int) -> ModelOutput:
        """
        Choose a candidate from the last `ModelOutput` to control the ongoing conversation flow.

        Parameters
        ----------
        index: `int`
            Index of the candidate to choose, starting from 0.

        Returns
        -------
        :class:`ModelOutput`
            Output data of the chosen candidate.

        Raises
        ------
        `ValueError`
            If no previous output data found in this chat session, or if index exceeds the number of candidates in last model output.
        """

        if not self.last_output:
            raise ValueError("No previous output data found in this chat session.")

        if index >= len(self.last_output.candidates):
            raise ValueError(
                f"Index {index} exceeds the number of candidates in last model output."
            )

        self.last_output.chosen = index
        self.rcid = self.last_output.rcid
        return self.last_output

    @property
    def metadata(self):
        return self.__metadata

    @metadata.setter
    def metadata(self, value: list[str]):
        if not isinstance(value, list):
            return

        # Update only non-None elements to preserve existing CID/RID/RCID/Context
        for i, val in enumerate(value):
            if i < 10 and val is not None:
                self.__metadata[i] = val

    @property
    def cid(self):
        return self.__metadata[0]

    @cid.setter
    def cid(self, value: str):
        self.__metadata[0] = value

    @property
    def rcid(self):
        return self.__metadata[2]

    @rcid.setter
    def rcid(self, value: str):
        self.__metadata[2] = value

    @property
    def rid(self):
        return self.__metadata[1]

    @rid.setter
    def rid(self, value: str):
        self.__metadata[1] = value
