import asyncio
import io
import random
import re
from asyncio import Task
from pathlib import Path
from typing import Any, Optional

import orjson as json
from httpx import AsyncClient, ReadTimeout, Response

from .components import GemMixin
from .constants import Endpoint, ErrorCode, Headers, Model
from .exceptions import (
    APIError,
    AuthError,
    GeminiError,
    ImageGenerationError,
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
    extract_json_from_response,
    get_access_token,
    get_nested_value,
    logger,
    parse_file_name,
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
        __Secure-1PSIDTS cookie value, some google accounts don't require this value, provide only if it's in the cookie list.
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
        "cfb2h",
        "timeout",
        "auto_close",
        "close_delay",
        "close_task",
        "auto_refresh",
        "refresh_interval",
        "refresh_task",
        "verbose",
        "_lock",
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
        self.cookies = {}
        self.proxy = proxy
        self._running: bool = False
        self.client: AsyncClient | None = None
        self.access_token: str | None = None
        self.cfb2h: str | None = None
        self.timeout: float = 300
        self.auto_close: bool = False
        self.close_delay: float = 300
        self.close_task: Task | None = None
        self.auto_refresh: bool = True
        self.refresh_interval: float = 540
        self.refresh_task: Task | None = None
        self.verbose: bool = True
        self._lock = asyncio.Lock()
        self.kwargs = kwargs

        if secure_1psid:
            self.cookies["__Secure-1PSID"] = secure_1psid
            if secure_1psidts:
                self.cookies["__Secure-1PSIDTS"] = secure_1psidts

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
                access_token, valid_cookies, cfb2h = await get_access_token(
                    base_cookies=self.cookies, proxy=self.proxy, verbose=self.verbose
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
                self.cfb2h = cfb2h
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
        Start the background task to automatically refresh cookies and access token.
        """
        if self.refresh_interval < 60:
            self.refresh_interval = 60

        while self._running:
            await asyncio.sleep(self.refresh_interval)

            if not self._running:
                break

            try:
                async with self._lock:
                    new_1psidts = await rotate_1psidts(self.cookies, self.proxy)

                    temp_cookies = self.cookies.copy()
                    if new_1psidts:
                        temp_cookies["__Secure-1PSIDTS"] = new_1psidts

                    access_token, valid_cookies, cfb2h = await get_access_token(
                        base_cookies=temp_cookies,
                        proxy=self.proxy,
                        verbose=self.verbose,
                    )

                    self.access_token = access_token
                    self.cookies = valid_cookies
                    self.cfb2h = cfb2h
                    if self._running and self.client:
                        self.client.cookies = valid_cookies

                    logger.debug("Cookies and access_token refreshed.")
            except asyncio.CancelledError:
                raise
            except AuthError:
                logger.warning(
                    "AuthError: Failed to refresh cookies. Retrying in next interval."
                )
            except Exception as e:
                logger.warning(f"Unexpected error while refreshing cookies: {e}")

    @running(retry=5)
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

        if isinstance(gem, Gem):
            gem_id = gem.id
        else:
            gem_id = gem

        if self.auto_close:
            await self.reset_close_task()

        try:
            message_content = [prompt]
            if files:
                semaphore = asyncio.Semaphore(3)  # Limit concurrent uploads to 3

                async def _upload_bounded(item):
                    async with semaphore:
                        url = await upload_file(item, self.proxy)
                        if isinstance(item, io.BytesIO):
                            item.close()
                        return url

                uploaded_urls = await asyncio.gather(
                    *(_upload_bounded(file) for file in files)
                )
                file_data = [
                    [[url], parse_file_name(file)]
                    for url, file in zip(uploaded_urls, files)
                ]
                message_content = [prompt, 0, None, file_data]

            params = {"_reqid": random.randint(1000000, 9999999), "rt": "c"}
            if self.cfb2h:
                params["bl"] = self.cfb2h

            response = await self.client.post(
                Endpoint.GENERATE.value,
                params=params,
                headers=model.model_header,
                data={
                    "at": self.access_token,
                    "f.req": json.dumps(
                        [
                            None,
                            json.dumps(
                                [
                                    message_content,
                                    None,
                                    chat and chat.metadata,
                                ]
                                + (gem_id and [None] * 16 + [gem_id] or [])
                            ).decode(),
                        ]
                    ).decode(),
                },
                **kwargs,
            )
        except ReadTimeout:
            raise TimeoutError(
                "Generate content request timed out, please try again. If the problem persists, "
                "consider setting a higher `timeout` value when initializing GeminiClient."
            )

        if response.status_code != 200:
            await self.close()
            raise APIError(
                f"Failed to generate contents. Request failed with status code {response.status_code}"
            )
        else:
            response_json: list[Any] = []
            body: list[Any] = []
            body_index = 0

            try:
                response_json = extract_json_from_response(response.text)

                for part_index, part in enumerate(response_json):
                    try:
                        part_body_str = get_nested_value(part, [2])
                        if not part_body_str:
                            continue

                        part_json = json.loads(part_body_str)

                        # Update chat metadata if available in any chunk to support follow-up polls
                        if m_data := get_nested_value(part_json, [1]):
                            if isinstance(chat, ChatSession):
                                chat.metadata = m_data

                        if get_nested_value(part_json, [4]):
                            body_index, body = part_index, part_json
                            break
                    except json.JSONDecodeError:
                        continue

                if not body:
                    # Detect if model is busy analyzing data or in a waiting state
                    # Patterns at index 5 often indicate background processing or queueing.
                    is_busy = False
                    for part in response_json:
                        if "data_analysis_tool" in str(part):
                            is_busy = True
                            break

                        status = get_nested_value(part, [5])
                        if isinstance(status, list) and status:
                            is_busy = True
                            break

                    if is_busy:
                        logger.debug(
                            "Model is busy or queueing. Polling again via decorator retry..."
                        )
                        raise APIError("Model is busy. Polling again...")

                    await self.close()

                    try:
                        error_code = get_nested_value(
                            response_json, [0, 5, 2, 0, 1, 0], -1, verbose=True
                        )
                        match error_code:
                            case ErrorCode.USAGE_LIMIT_EXCEEDED:
                                raise UsageLimitExceeded(
                                    f"Failed to generate contents. Usage limit of {model.model_name} model has exceeded. Please try switching to another model."
                                )
                            case ErrorCode.MODEL_INCONSISTENT:
                                raise ModelInvalid(
                                    "Failed to generate contents. The specified model is inconsistent with the chat history. Please make sure to pass the same "
                                    "`model` parameter when starting a chat session with previous metadata."
                                )
                            case ErrorCode.MODEL_HEADER_INVALID:
                                raise ModelInvalid(
                                    "Failed to generate contents. The specified model is not available. Please update gemini_webapi to the latest version. "
                                    "If the error persists and is caused by the package, please report it on GitHub."
                                )
                            case ErrorCode.IP_TEMPORARILY_BLOCKED:
                                raise TemporarilyBlocked(
                                    "Failed to generate contents. Your IP address is temporarily blocked by Google. Please try using a proxy or waiting for a while."
                                )
                            case _:
                                raise Exception(
                                    "No candidate body found in response stream"
                                )
                    except GeminiError:
                        raise
                    except Exception as e:
                        logger.debug(
                            f"Unexpected response structure: {e}. Response: {response.text}"
                        )
                        raise APIError(
                            "Failed to generate contents. Unexpected response data structure. Client will try to re-initialize on next request."
                        )

            except (GeminiError, APIError):
                raise
            except Exception as e:
                logger.debug(f"Parsing error or busy: {e}. Retrying via decorator...")
                raise APIError(f"Failed to parse response body: {e}")

            try:
                candidate_list: list[Any] = get_nested_value(
                    body, [4], [], verbose=True
                )
                output_candidates: list[Candidate] = []

                for candidate_index, candidate in enumerate(candidate_list):
                    rcid = get_nested_value(candidate, [0])
                    if not rcid:
                        continue  # Skip candidate if it has no rcid

                    # Text output and thoughts
                    text = get_nested_value(candidate, [1, 0], "")
                    if re.match(
                        r"^http://googleusercontent\.com/card_content/\d+", text
                    ):
                        text = get_nested_value(candidate, [22, 0]) or text

                    thoughts = get_nested_value(candidate, [37, 0, 0])

                    # Web images
                    web_images = []
                    for web_img_data in get_nested_value(candidate, [12, 1], []):
                        url = get_nested_value(web_img_data, [0, 0, 0])
                        if not url:
                            continue

                        web_images.append(
                            WebImage(
                                url=url,
                                title=get_nested_value(web_img_data, [7, 0], ""),
                                alt=get_nested_value(web_img_data, [0, 4], ""),
                                proxy=self.proxy,
                            )
                        )

                    # Generated images
                    generated_images = []
                    if get_nested_value(candidate, [12, 7, 0]):
                        img_body = None
                        for img_part_index, part in enumerate(response_json):
                            if img_part_index < body_index:
                                continue
                            try:
                                img_part_body_str = get_nested_value(part, [2])
                                if not img_part_body_str:
                                    continue

                                img_part_json = json.loads(img_part_body_str)
                                if get_nested_value(
                                    img_part_json, [4, candidate_index, 12, 7, 0]
                                ):
                                    img_body = img_part_json
                                    break
                            except json.JSONDecodeError:
                                continue

                        if not img_body:
                            raise ImageGenerationError(
                                "Failed to parse generated images. Please update gemini_webapi to the latest version. "
                                "If the error persists and is caused by the package, please report it on GitHub."
                            )

                        img_candidate = get_nested_value(
                            img_body, [4, candidate_index], [], verbose=True
                        )

                        if (
                            finished_text := get_nested_value(img_candidate, [1, 0])
                        ):  # Only overwrite if new text is returned after image generation
                            text = re.sub(
                                r"http://googleusercontent\.com/image_generation_content/\d+",
                                "",
                                finished_text,
                            ).rstrip()

                        for img_index, gen_img_data in enumerate(
                            get_nested_value(img_candidate, [12, 7, 0], [])
                        ):
                            url = get_nested_value(gen_img_data, [0, 3, 3])
                            if not url:
                                continue

                            img_num = get_nested_value(gen_img_data, [3, 6])
                            title = (
                                f"[Generated Image {img_num}]"
                                if img_num
                                else "[Generated Image]"
                            )

                            alt_list = get_nested_value(gen_img_data, [3, 5], [])
                            alt = (
                                get_nested_value(alt_list, [img_index])
                                or get_nested_value(alt_list, [0])
                                or ""
                            )

                            generated_images.append(
                                GeneratedImage(
                                    url=url,
                                    title=title,
                                    alt=alt,
                                    proxy=self.proxy,
                                    cookies=self.cookies,
                                )
                            )

                    output_candidates.append(
                        Candidate(
                            rcid=rcid,
                            text=text,
                            thoughts=thoughts,
                            web_images=web_images,
                            generated_images=generated_images,
                        )
                    )

                if not output_candidates:
                    raise GeminiError(
                        "Failed to generate contents. No output data found in response."
                    )

                output = ModelOutput(
                    metadata=get_nested_value(body, [1], [], verbose=True),
                    candidates=output_candidates,
                )
            except (TypeError, IndexError) as e:
                logger.debug(
                    f"{type(e).__name__}: {e}; Unexpected data structure: {response.text}"
                )
                raise APIError(
                    "Failed to parse response body. Data structure is invalid."
                )

            if isinstance(chat, ChatSession):
                chat.last_output = output

            return output

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

    @running(retry=5)
    async def _batch_execute(self, payloads: list[RPCData], **kwargs) -> Response:
        """
        Execute a batch of requests to Gemini API.

        Parameters
        ----------
        payloads: `list[GRPC]`
            List of `gemini_webapi.types.GRPC` objects to be executed.
        kwargs: `dict`, optional
            Additional arguments which will be passed to the post request.
            Refer to `httpx.AsyncClient.request` for more information.

        Returns
        -------
        :class:`httpx.Response`
            Response object containing the result of the batch execution.
        """

        try:
            response = await self.client.post(
                Endpoint.BATCH_EXEC,
                data={
                    "at": self.access_token,
                    "f.req": json.dumps(
                        [[payload.serialize() for payload in payloads]]
                    ).decode(),
                },
                **kwargs,
            )
        except ReadTimeout:
            raise TimeoutError(
                "Batch execute request timed out, please try again. If the problem persists, "
                "consider setting a higher `timeout` value when initializing GeminiClient."
            )

        # ? Seems like batch execution will immediately invalidate the current access token,
        # ? causing the next request to fail with 401 Unauthorized.
        if response.status_code != 200:
            await self.close()
            raise APIError(
                f"Batch execution failed with status code {response.status_code}"
            )

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
        self.__metadata: list[str | None] = [None, None, None]
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
        if len(value) > 3:
            raise ValueError("metadata cannot exceed 3 elements")
        self.__metadata[: len(value)] = value

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
