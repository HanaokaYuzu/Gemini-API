import asyncio
import re
from asyncio import Task
from pathlib import Path
from typing import Any, Optional

import orjson as json
from httpx import AsyncClient, ReadTimeout, Response

from .components import GemMixin
from .constants import Endpoint, ErrorCode, Headers, Model
from .exceptions import (
    AuthError,
    APIError,
    ImageGenerationError,
    TimeoutError,
    GeminiError,
    UsageLimitExceeded,
    ModelInvalid,
    TemporarilyBlocked,
)
from .types import (
    WebImage,
    GeneratedImage,
    Candidate,
    ModelOutput,
    Gem,
    RPCData,
)
from .utils import (
    upload_file,
    parse_file_name,
    rotate_1psidts,
    get_access_token,
    running,
    rotate_tasks,
    logger,
)


class GeminiClient(GemMixin):
    """
    Async httpx client interface for gemini.google.com.

    `secure_1psid` must be provided unless the optional dependency `browser-cookie3` is installed and
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
        "running",
        "client",
        "access_token",
        "timeout",
        "auto_close",
        "close_delay",
        "close_task",
        "auto_refresh",
        "refresh_interval",
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
        self.running: bool = False
        self.client: AsyncClient | None = None
        self.access_token: str | None = None
        self.timeout: float = 300
        self.auto_close: bool = False
        self.close_delay: float = 300
        self.close_task: Task | None = None
        self.auto_refresh: bool = True
        self.refresh_interval: float = 540
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
            If `True`, will schedule a task to automatically refresh cookies in the background.
        refresh_interval: `float`, optional
            Time interval for background cookie refresh in seconds. Effective only if `auto_refresh` is `True`.
        verbose: `bool`, optional
            If `True`, will print more infomation in logs.
        """

        try:
            access_token, valid_cookies = await get_access_token(
                base_cookies=self.cookies, proxy=self.proxy, verbose=verbose
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
            self.running = True

            self.timeout = timeout
            self.auto_close = auto_close
            self.close_delay = close_delay
            if self.auto_close:
                await self.reset_close_task()

            self.auto_refresh = auto_refresh
            self.refresh_interval = refresh_interval
            if task := rotate_tasks.get(self.cookies["__Secure-1PSID"]):
                task.cancel()
            if self.auto_refresh:
                rotate_tasks[self.cookies["__Secure-1PSID"]] = asyncio.create_task(
                    self.start_auto_refresh()
                )

            if verbose:
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

        self.running = False

        if self.close_task:
            self.close_task.cancel()
            self.close_task = None

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

        while True:
            new_1psidts: str | None = None
            try:
                new_1psidts = await rotate_1psidts(self.cookies, self.proxy)
            except AuthError:
                if task := rotate_tasks.get(self.cookies.get("__Secure-1PSID", "")):
                    task.cancel()
                logger.warning(
                    "Failed to refresh cookies (AuthError). Auto refresh task canceled."
                )
                return
            except Exception as exc:
                logger.warning(f"Unexpected error while refreshing cookies: {exc}")

            if new_1psidts:
                self.cookies["__Secure-1PSIDTS"] = new_1psidts
                self._sync_httpx_cookie("__Secure-1PSIDTS", new_1psidts)
                logger.debug("Cookies refreshed. New __Secure-1PSIDTS applied.")
            await asyncio.sleep(self.refresh_interval)

    def _sync_httpx_cookie(self, name: str, value: str) -> None:
        """
        Ensure the underlying httpx client uses the refreshed cookie value.
        """
        if not self.client:
            return

        jar = self.client.cookies.jar
        matched = False
        for cookie in jar:
            if cookie.name == name:
                cookie.value = value
                matched = True
        if not matched:
            # Fall back to setting the cookie with default scope if we did not find an existing entry.
            self.client.cookies.set(name, value)

    @staticmethod
    def _safe_get(data: list, path: list[int], default: Any = None) -> Any:
        """
        Safely get a value from a nested list.
        """
        current = data
        for i, key in enumerate(path):
            try:
                current = current[key]
            except (IndexError, TypeError, KeyError) as e:
                current_repr = repr(current)
                if len(current_repr) > 150:
                    current_repr = current_repr[:150] + "..."

                logger.debug(
                    f"safe_get failed at path {path} (index {i}, key '{key}'). "
                    f"Reason: {type(e).__name__}. "
                    f"Attempted to access key on: {current_repr}"
                )
                return default
        if current is None and default is not None:
            return default
        return current

    @running(retry=2)
    async def generate_content(
        self,
        prompt: str,
        files: list[str | Path] | None = None,
        model: Model | str = Model.UNSPECIFIED,
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
        model: `Model` | `str`, optional
            Specify the model to use for generation.
            Pass either a `gemini_webapi.constants.Model` enum or a model name string.
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

        if not isinstance(model, Model):
            model = Model.from_name(model)

        if isinstance(gem, Gem):
            gem_id = gem.id
        else:
            gem_id = gem

        if self.auto_close:
            await self.reset_close_task()

        try:
            response = await self.client.post(
                Endpoint.GENERATE.value,
                headers=model.model_header,
                data={
                    "at": self.access_token,
                    "f.req": json.dumps(
                        [
                            None,
                            json.dumps(
                                [
                                    files
                                    and [
                                        prompt,
                                        0,
                                        None,
                                        [
                                            [
                                                [await upload_file(file, self.proxy)],
                                                parse_file_name(file),
                                            ]
                                            for file in files
                                        ],
                                    ]
                                    or [prompt],
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
            try:
                response_text = response.text
                if response_text.startswith(")]}'\n"):
                    response_text = response_text[5:]
                elif response_text.startswith(")]}'"):
                    response_text = response_text[4:]

                json_str = ""
                for line in response_text.splitlines():
                    stripped_line = line.strip()
                    if stripped_line.startswith("[") or stripped_line.startswith("{"):
                        json_str = stripped_line
                        break

                if not json_str:
                    json_str = response_text.strip()

                response_json = json.loads(json_str)

                body = None
                body_index = 0
                for part_index, part in enumerate(response_json):
                    try:
                        part_str = self._safe_get(part, [2])
                        if not part_str:
                            continue

                        main_part = json.loads(part_str)
                        if self._safe_get(main_part, [4]):
                            body_index, body = part_index, main_part
                            break
                    except (TypeError, ValueError):
                        continue

                if not body:
                    raise Exception
            except Exception:
                await self.close()

                try:
                    error_code = self._safe_get(response_json, [0, 5, 2, 0, 1, 0], -1)
                    match ErrorCode(error_code):
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
                            raise Exception
                except GeminiError:
                    raise
                except Exception:
                    logger.debug(f"Invalid response: {response.text}")
                    raise APIError(
                        "Failed to generate contents. Invalid response data received. Client will try to re-initialize on next request."
                    )

            try:
                candidates = []
                # Safely get the list of candidates from the response body
                candidate_list = self._safe_get(body, [4], [])

                for candidate_index, candidate in enumerate(candidate_list):
                    # Safely extract data for each candidate
                    rcid = self._safe_get(candidate, [0])
                    if not rcid:
                        continue  # Skip candidate if it has no rcid

                    text = self._safe_get(candidate, [1, 0], "")
                    if re.match(
                        r"^http://googleusercontent\.com/card_content/\d+", text or ""
                    ):
                        text = self._safe_get(candidate, [22, 0]) or text

                    thoughts = self._safe_get(candidate, [37, 0, 0])

                    # Safely extract web images
                    web_images = []
                    for web_image_data in self._safe_get(candidate, [12, 1], []):
                        url = self._safe_get(web_image_data, [0, 0, 0])
                        if not url:
                            continue
                        web_images.append(
                            WebImage(
                                url=url,
                                title=self._safe_get(web_image_data, [7, 0], ""),
                                alt=self._safe_get(web_image_data, [0, 4], ""),
                                proxy=self.proxy,
                            )
                        )

                    # Safely extract generated images
                    generated_images = []
                    if self._safe_get(candidate, [12, 7, 0]):
                        img_body = None
                        for img_part_index, part in enumerate(response_json):
                            if img_part_index < body_index:
                                continue
                            try:
                                img_part = json.loads(part[2])
                                if self._safe_get(
                                    img_part, [4, candidate_index, 12, 7, 0]
                                ):
                                    img_body = img_part
                                    break
                            except (IndexError, TypeError, ValueError):
                                continue

                        if not img_body:
                            raise ImageGenerationError(
                                "Failed to parse generated images. Please update gemini_webapi to the latest version. "
                                "If the error persists and is caused by the package, please report it on GitHub."
                            )

                        img_candidate = self._safe_get(
                            img_body, [4, candidate_index], []
                        )

                        img_text = self._safe_get(
                            img_candidate, [1, 0]
                        )  # Get text, could be None
                        if (
                            img_text is not None
                        ):  # Only overwrite if text is found in the image candidate
                            text = re.sub(
                                r"http://googleusercontent\.com/image_generation_content/\d+",
                                "",
                                img_text,
                            ).rstrip()

                        for image_index, gen_img_data in enumerate(
                            self._safe_get(img_candidate, [12, 7, 0], [])
                        ):
                            url = self._safe_get(gen_img_data, [0, 3, 3])
                            if not url:
                                continue

                            img_num = self._safe_get(gen_img_data, [3, 6])
                            title = (
                                f"[Generated Image {img_num}]"
                                if img_num
                                else "[Generated Image]"
                            )

                            alt_list = self._safe_get(gen_img_data, [3, 5], [])
                            alt = (
                                self._safe_get(alt_list, [image_index])
                                or self._safe_get(alt_list, [0])
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

                    candidates.append(
                        Candidate(
                            rcid=rcid,
                            text=text,
                            thoughts=thoughts,
                            web_images=web_images,
                            generated_images=generated_images,
                        )
                    )

                if not candidates:
                    raise GeminiError(
                        "Failed to generate contents. No output data found in response."
                    )

                output = ModelOutput(
                    metadata=self._safe_get(body, [1], []), candidates=candidates
                )
            except (TypeError, IndexError) as e:
                logger.debug(f"Invalid response structure: {response.text}, error: {e}")
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
    model: `Model` | `str`, optional
        Specify the model to use for generation.
        Pass either a `gemini_webapi.constants.Model` enum or a model name string.
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
        model: Model | str = Model.UNSPECIFIED,
        gem: Gem | str | None = None,
    ):
        self.__metadata: list[str | None] = [None, None, None]
        self.geminiclient: GeminiClient = geminiclient
        self.last_output: ModelOutput | None = None
        self.model: Model | str = model
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
    def rid(self):
        return self.__metadata[1]

    @rid.setter
    def rid(self, value: str):
        self.__metadata[1] = value

    @property
    def rcid(self):
        return self.__metadata[2]

    @rcid.setter
    def rcid(self, value: str):
        self.__metadata[2] = value
