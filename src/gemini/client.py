import re
import json
import asyncio
from asyncio import Task
from typing import Any, Optional

from httpx import AsyncClient, ReadTimeout
from loguru import logger

from .consts import HEADERS
from .types import (
    WebImage,
    GeneratedImage,
    Candidate,
    ModelOutput,
    AuthError,
    APIError,
    GeminiError,
    TimeoutError,
)


def running(func) -> callable:
    """
    Decorator to check if client is running before making a request.
    """

    async def wrapper(self: "GeminiClient", *args, **kwargs):
        if not self.running:
            await self.init(auto_close=self.auto_close, close_delay=self.close_delay)
            if self.running:
                return await func(self, *args, **kwargs)

            raise Exception(
                f"Invalid function call: GeminiClient.{func.__name__}. Client initialization failed."
            )
        else:
            return await func(self, *args, **kwargs)

    return wrapper


class GeminiClient:
    """
    Async httpx client interface for gemini.google.com

    Parameters
    ----------
    secure_1psid: `str`
        __Secure-1PSID cookie value
    secure_1psidts: `str`, optional
        __Secure-1PSIDTS cookie value, some google accounts don't require this value, provide only if it's in the cookie list
    proxy: `dict`, optional
        Dict of proxies
    """

    __slots__ = [
        "cookies",
        "proxy",
        "client",
        "access_token",
        "running",
        "auto_close",
        "close_delay",
        "close_task",
    ]

    def __init__(
        self,
        secure_1psid: str,
        secure_1psidts: Optional[str] = None,
        proxy: Optional[dict] = None,
    ):
        self.cookies = {
            "__Secure-1PSID": secure_1psid,
            "__Secure-1PSIDTS": secure_1psidts,
        }
        self.proxy = proxy
        self.client: AsyncClient | None = None
        self.access_token: Optional[str] = None
        self.running: bool = False
        self.auto_close: bool = False
        self.close_delay: int = 0
        self.close_task: Task | None = None

    async def init(
        self, timeout: float = 30, auto_close: bool = False, close_delay: int = 300
    ) -> None:
        """
        Get SNlM0e value as access token. Without this token posting will fail with 400 bad request.

        Parameters
        ----------
        timeout: `int`, optional
            Request timeout of the client in seconds. Used to limit the max waiting time when sending a request
        auto_close: `bool`, optional
            If `True`, the client will close connections and clear resource usage after a certain period
            of inactivity. Useful for keep-alive services
        close_delay: `int`, optional
            Time to wait before auto-closing the client in seconds. Effective only if `auto_close` is `True`
        """
        try:
            self.client = AsyncClient(
                timeout=timeout,
                proxies=self.proxy,
                follow_redirects=True,
                headers=HEADERS,
                cookies=self.cookies,
            )

            response = await self.client.get("https://gemini.google.com/app")

            if response.status_code != 200:
                raise APIError(
                    f"Failed to initiate client. Request failed with status code {response.status_code}"
                )
            else:
                match = re.search(r'"SNlM0e":"(.*?)"', response.text)
                if match:
                    self.access_token = match.group(1)
                    self.running = True
                    logger.success("Gemini client initiated successfully.")
                else:
                    raise AuthError(
                        "Failed to initiate client. SECURE_1PSIDTS could get expired frequently, please make sure cookie values are up to date."
                    )

            self.auto_close = auto_close
            self.close_delay = close_delay
            if self.auto_close:
                await self.reset_close_task()
        except Exception:
            await self.close(0)
            raise

    async def close(self, wait: int | None = None) -> None:
        """
        Close the client after a certain period of inactivity, or call manually to close immediately.

        Parameters
        ----------
        wait: `int`, optional
            Time to wait before closing the client in seconds
        """
        await asyncio.sleep(wait is not None and wait or self.close_delay)
        await self.client.aclose()
        self.running = False

    async def reset_close_task(self) -> None:
        """
        Reset the timer for closing the client when a new request is made.
        """
        if self.close_task:
            self.close_task.cancel()
            self.close_task = None
        self.close_task = asyncio.create_task(self.close())

    @running
    async def generate_content(
        self, prompt: str, chat: Optional["ChatSession"] = None
    ) -> ModelOutput:
        """
        Generates contents with prompt.

        Parameters
        ----------
        prompt: `str`
            Prompt provided by user
        chat: `ChatSession`, optional
            Chat data to retrieve conversation history. If None, will automatically generate a new chat id when sending post request

        Returns
        -------
        :class:`ModelOutput`
            Output data from gemini.google.com, use `ModelOutput.text` to get the default text reply, `ModelOutput.images` to get a list
            of images in the default reply, `ModelOutput.candidates` to get a list of all answer candidates in the output
        """
        assert prompt, "Prompt cannot be empty."

        if self.auto_close:
            await self.reset_close_task()

        try:
            response = await self.client.post(
                "https://gemini.google.com/_/BardChatUi/data/assistant.lamda.BardFrontendService/StreamGenerate",
                data={
                    "at": self.access_token,
                    "f.req": json.dumps(
                        [None, json.dumps([[prompt], None, chat and chat.metadata])]
                    ),
                },
            )
        except ReadTimeout:
            raise TimeoutError(
                "Request timed out, please try again. If the problem persists, consider setting a higher `timeout` value when initiating GeminiClient."
            )

        if response.status_code != 200:
            await self.close(0)
            raise APIError(
                f"Failed to generate contents. Request failed with status code {response.status_code}"
            )
        else:
            try:
                body = json.loads(json.loads(response.text.split("\n")[2])[0][2])
            except (TypeError, json.JSONDecodeError):
                await self.close(0)
                raise APIError(
                    "Failed to generate contents. Invalid response data received. Client will try to re-initiate on next request."
                )

            candidates = []
            for candidate in body[4]:
                web_images = (
                    candidate[4]
                    and [
                        WebImage(url=image[0][0][0], title=image[2], alt=image[0][4])
                        for image in candidate[4]
                    ]
                    or []
                )
                generated_images = (
                    candidate[12]
                    and candidate[12][7]
                    and candidate[12][7][0]
                    and [
                        GeneratedImage(
                            url=image[0][3][3],
                            title=f"[Generated Image {image[3][6]}]",
                            alt=image[3][5][i],
                            cookies=self.cookies,
                        )
                        for i, image in enumerate(candidate[12][7][0])
                    ]
                    or []
                )
                candidates.append(
                    Candidate(
                        rcid=candidate[0],
                        text=candidate[1][0],
                        web_images=web_images,
                        generated_images=generated_images,
                    )
                )
            if not candidates:
                raise GeminiError(
                    "Failed to generate contents. No output data found in response."
                )

            output = ModelOutput(metadata=body[1], candidates=candidates)

            if isinstance(chat, ChatSession):
                chat.last_output = output

            return output

    def start_chat(self, **kwargs) -> "ChatSession":
        """
        Returns a `ChatSession` object attached to this model.

        Returns
        -------
        :class:`ChatSession`
            Empty chat object for retrieving conversation history
        """
        return ChatSession(geminiclient=self, **kwargs)


class ChatSession:
    """
    Chat data to retrieve conversation history. Only if all 3 ids are provided will the conversation history be retrieved.

    Parameters
    ----------
    geminiclient: `GeminiClient`
        Async httpx client interface for gemini.google.com
    metadata: `list[str]`, optional
        List of chat metadata `[cid, rid, rcid]`, can be shorter than 3 elements, like `[cid, rid]` or `[cid]` only
    cid: `str`, optional
        Chat id, if provided together with metadata, will override the first value in it
    rid: `str`, optional
        Reply id, if provided together with metadata, will override the second value in it
    rcid: `str`, optional
        Reply candidate id, if provided together with metadata, will override the third value in it
    """

    # @properties needn't have their slots pre-defined
    __slots__ = ["__metadata", "geminiclient", "last_output"]

    def __init__(
        self,
        geminiclient: GeminiClient,
        metadata: Optional[list[str]] = None,
        cid: Optional[str] = None,  # chat id
        rid: Optional[str] = None,  # reply id
        rcid: Optional[str] = None,  # reply candidate id
    ):
        self.__metadata: list[Optional[str]] = [None, None, None]
        self.geminiclient: GeminiClient = geminiclient
        self.last_output: Optional[ModelOutput] = None

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

    async def send_message(self, prompt: str) -> ModelOutput:
        """
        Generates contents with prompt.
        Use as a shortcut for `GeminiClient.generate_content(prompt, self)`.

        Parameters
        ----------
        prompt: `str`
            Prompt provided by user

        Returns
        -------
        :class:`ModelOutput`
            Output data from gemini.google.com, use `ModelOutput.text` to get the default text reply, `ModelOutput.images` to get a list
            of images in the default reply, `ModelOutput.candidates` to get a list of all answer candidates in the output
        """
        return await self.geminiclient.generate_content(prompt, self)

    def choose_candidate(self, index: int) -> ModelOutput:
        """
        Choose a candidate from the last `ModelOutput` to control the ongoing conversation flow.

        Parameters
        ----------
        index: `int`
            Index of the candidate to choose, starting from 0
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
