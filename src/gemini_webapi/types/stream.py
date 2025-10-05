from typing import AsyncIterator, Any, Optional
from pydantic import BaseModel

from .candidate import Candidate
from .modeloutput import ModelOutput
from ..utils import logger


class StreamChunk(BaseModel):
    """
    A single chunk of streamed response data.

    Parameters
    ----------
    text: `str`
        Incremental text content in this chunk.
    is_final: `bool`
        Whether this is the final chunk in the stream.
    metadata: `list[str | None]`, optional
        Chat metadata if available. Format: [cid, rid, rcid, None*6, token]
        where cid=chat_id, rid=reply_id, rcid=reply_candidate_id, token=auth_token.
    candidates: `list[Candidate]`, optional
        Partial candidates data if available.
    delta_text: `str`, optional
        Text delta that was added in this chunk (may be different from text which is cumulative).
    thoughts: `str`, optional
        Model's thought process if available.
    """

    text: str = ""
    is_final: bool = False
    metadata: list[str | None] = []  # Allow None values in metadata array
    candidates: list[Candidate] = []
    delta_text: str = ""
    thoughts: str | None = None
    delta_thoughts: str = ""

    def __str__(self):
        return self.text

    def __repr__(self):
        return f"StreamChunk(text='{len(self.text) <= 20 and self.text or self.text[:20] + '...'}', is_final={self.is_final}, delta='{self.delta_text}')"


class StreamedResponse:
    """
    Handler for processing streamed response data from Gemini.
    
    Parameters
    ----------
    response_iterator: `AsyncIterator[bytes]`
        The async iterator of response chunks from httpx.
    proxy: `str`, optional
        Proxy URL for image downloads.
    cookies: `dict`, optional
        Cookies for image downloads.
    """

    def __init__(
        self,
        response_iterator: AsyncIterator[bytes],
        proxy: str | None = None,
        cookies: dict | None = None,
    ):
        self.response_iterator = response_iterator
        self.proxy = proxy
        self.cookies = cookies or {}
        self._accumulated_text = ""
        self._last_chunk_text = ""
        self._metadata = []
        self._candidates = []
        self._is_complete = False
        self._thoughts = None
        self._rcid = None  # Track reply candidate id separately
        self._cid = None   # Track chat id
        self._rid = None   # Track reply id

    @classmethod
    def create_stream(
        cls,
        client,
        method: str,
        url: str,
        headers: dict,
        data: dict,
        proxy: str | None = None,
        cookies: dict | None = None,
        **kwargs
    ):
        """
        Create a StreamedResponse that manages the HTTP stream internally.
        """
        return _StreamManager(
            client=client,
            method=method,
            url=url,
            headers=headers,
            data=data,
            proxy=proxy,
            cookies=cookies,
            **kwargs
        )

    async def __aiter__(self) -> AsyncIterator[StreamChunk]:
        """
        Async iterator that yields StreamChunk objects as they arrive.
        """
        async for chunk in self._process_chunks():
            yield chunk

    async def _process_chunks(self) -> AsyncIterator[StreamChunk]:
        """
        Process raw response chunks and yield StreamChunk objects.
        使用[["wrb.fr"作为分割标记来识别完整的JSON对象。
        """
        import orjson as json
        import re
        from .image import WebImage, GeneratedImage
        from .candidate import Candidate

        xssi_removed = False

        delimiter = '["wrb.fr"'
        buffer = ""

        async for raw_chunk in self.response_iterator:
            buffer += raw_chunk.decode('utf-8', errors='ignore')
            # 移除XSSI前缀
            if not xssi_removed and buffer.startswith(")]}'"):
                buffer = buffer[5:].lstrip('\n')
                xssi_removed = True

            # 查找所有分隔块
            while True:
                start = buffer.find(delimiter)
                buffer = buffer.lstrip()
                if start == -1:
                    break
                next_start = buffer.find(delimiter, start + len(delimiter))
                if next_start == -1:
                    # 等更多数据
                    break

                json_str = buffer[start:next_start-1].strip()
                buffer = buffer[next_start:]  # 下次循环处理剩余内容
                if json_str and json_str.startswith('['):
                    try:
                        response_data = json.loads('['+json_str+']')
                        async for chunk_result in self._parse_response_chunk(response_data):
                            yield chunk_result
                    except Exception as e:
                        logger.error(f"Failed to parse JSON chunk: {e}")
                        pass

        # 最后buffer剩余处理
        buffer = buffer.strip()
        if buffer and not buffer[0].isdigit() and buffer.startswith('['):
            try:
                response_data = json.loads(buffer)
                # 在处理最后的buffer时，尝试提取token并更新metadata
                # 最后一个响应块通常只包含 [null, [cid, rid], null*22, token]
                if isinstance(response_data, list) and len(response_data) > 0:
                    for item in response_data:
                        if isinstance(item, list) and len(item) >= 3 and item[0] == "wrb.fr":
                            try:
                                inner_data = json.loads(item[2])
                                if isinstance(inner_data, list):
                                    # 提取 token（位置 25）
                                    if len(inner_data) > 25 and inner_data[25]:
                                        token = inner_data[25]
                                        # 更新已有metadata中的token
                                        if self._metadata and len(self._metadata) >= 10:
                                            self._metadata[9] = token
                                        elif self._cid and self._rid:
                                            # 如果还没有metadata，现在构建完整的
                                            self._metadata = [
                                                self._cid,
                                                self._rid,
                                                self._rcid,
                                                None, None, None, None, None, None,
                                                token
                                            ]
                            except:
                                pass
                
                async for chunk_result in self._parse_response_chunk(response_data, is_final=True):
                    yield chunk_result
            except:
                pass

        # 确保发送最终块，包含最终的metadata
        if self._accumulated_text and not self._is_complete:
            self._is_complete = True
            yield StreamChunk(
                text=self._accumulated_text,
                is_final=True,
                metadata=self._metadata,
                candidates=self._candidates,
                delta_text="",
                thoughts=self._thoughts,
                delta_thoughts=""
            )

    async def _parse_response_chunk(self, response_data: Any, is_final: bool = False) -> AsyncIterator[StreamChunk]:
        """
        Parse a single response chunk and extract streaming data.
        """
        import orjson as json
        import re
        from . import WebImage, GeneratedImage, Candidate

        try:
            # Google's response format: [["wrb.fr", null, JSON_STRING], ...]
            if isinstance(response_data, list) and len(response_data) > 0:
                for item in response_data:
                    if isinstance(item, list) and len(item) >= 3:
                        # Check if this is a content response
                        if item[0] == "wrb.fr" and isinstance(item[2], str):
                            try:
                                # Parse the inner JSON string
                                inner_data = json.loads(item[2])
                                
                                # Extract content from the response structure
                                # Format: [null, [chat_id, response_id], null, null, [[candidate_id, [text], ...]], ...]
                                if isinstance(inner_data, list) and len(inner_data) > 4:
                                    candidates_data = inner_data[4]
                                    
                                    if isinstance(candidates_data, list) and len(candidates_data) > 0:
                                        for candidate_item in candidates_data:
                                            if isinstance(candidate_item, list) and len(candidate_item) >= 2:
                                                candidate_id = candidate_item[0]  # This is rcid
                                                candidate_content = candidate_item[1]
                                                delta_thoughts = ""
                                                # Extract thoughts if available (same position as in generate_content)
                                                try:
                                                    if len(candidate_item) > 37 and candidate_item[37]:
                                                        new_thoughts = candidate_item[37][0][0]
                                                        if self._thoughts is None or self._thoughts == "":
                                                            # First time encountering thoughts
                                                            delta_thoughts = new_thoughts
                                                            self._thoughts = new_thoughts
                                                        elif len(new_thoughts) > len(self._thoughts):
                                                            # Thoughts have grown, calculate delta
                                                            delta_thoughts = new_thoughts[len(self._thoughts):]
                                                            self._thoughts = new_thoughts
                                                except (TypeError, IndexError):
                                                    pass
                                                
                                                if isinstance(candidate_content, list) and len(candidate_content) > 0:
                                                    text_content = candidate_content[0]
                                                    
                                                    if isinstance(text_content, str):
                                                        # Calculate delta text
                                                        delta_text = ""
                                                        if len(text_content) > len(self._accumulated_text):
                                                            delta_text = text_content[len(self._accumulated_text):]
                                                        self._accumulated_text = text_content
                                                        
                                                        # Extract metadata components
                                                        # First block has: [null, [cid, rid], null, null, [[rcid, [text], ...]], ...]
                                                        # Later block has: [null, [cid, rid], null*22, token_at_position_25]
                                                        
                                                        # Extract cid and rid from position 1
                                                        if len(inner_data) > 1 and isinstance(inner_data[1], list) and len(inner_data[1]) >= 2:
                                                            self._cid = inner_data[1][0]
                                                            self._rid = inner_data[1][1]
                                                        
                                                        # Extract rcid from candidate_id (first block)
                                                        if candidate_id:
                                                            self._rcid = candidate_id
                                                        
                                                        # Extract token from position 25 if available (later blocks)
                                                        token = inner_data[25] if len(inner_data) > 25 else None
                                                        
                                                        # Construct full metadata array with 10 elements
                                                        # Use stored values, update with token if found
                                                        if self._cid and self._rid:
                                                            self._metadata = [
                                                                self._cid,
                                                                self._rid, 
                                                                self._rcid,
                                                                None, None, None, None, None, None,
                                                                token if token else (self._metadata[9] if len(self._metadata) > 9 else None)
                                                            ]
                                                        
                                                        # 当有delta文本或delta思考过程时，都要输出chunk
                                                        if delta_text or delta_thoughts:
                                                            chunk = StreamChunk(
                                                                text=text_content,
                                                                is_final=False,
                                                                metadata=self._metadata,
                                                                candidates=self._candidates,
                                                                delta_text=delta_text,
                                                                thoughts=self._thoughts,
                                                                delta_thoughts=delta_thoughts
                                                            )
                                                            yield chunk
                                                        elif is_final and self._accumulated_text:
                                                            # 最终块，即使没有新delta也返回
                                                            chunk = StreamChunk(
                                                                text=text_content,
                                                                is_final=True,
                                                                metadata=self._metadata,
                                                                candidates=self._candidates,
                                                                delta_text="",
                                                                thoughts=self._thoughts,
                                                                delta_thoughts=""
                                                            )
                                                            yield chunk
                                                        
                            except (json.JSONDecodeError, KeyError, IndexError) as e:
                                # Skip parsing errors silently
                                continue
                                
        except Exception as e:
            # Skip response parsing errors silently
            pass

    async def collect(self) -> ModelOutput:
        """
        Collect all streamed chunks and return a complete ModelOutput.
        """
        final_text = ""
        final_metadata = []
        
        async for chunk in self:
            final_text = chunk.text
            if chunk.metadata:
                final_metadata = chunk.metadata
            if chunk.is_final:
                break
        
        # Create a basic candidate with the collected text
        from . import Candidate, ModelOutput
        
        candidate = Candidate(
            rcid="stream_final",
            text=final_text,
            thoughts=None,
            web_images=[],
            generated_images=[]
        )
        
        return ModelOutput(
            metadata=final_metadata,
            candidates=[candidate],
            chosen=0
        )


class _StreamManager:
    """
    Internal class to manage HTTP streaming with proper resource cleanup.
    """
    
    def __init__(
        self,
        client,
        method: str,
        url: str,
        headers: dict,
        data: dict,
        proxy: str | None = None,
        cookies: dict | None = None,
        **kwargs
    ):
        self.client = client
        self.method = method
        self.url = url
        self.headers = headers
        self.data = data
        self.proxy = proxy
        self.cookies = cookies or {}
        self.kwargs = kwargs
        
    async def __aiter__(self):
        """
        Create the stream and yield chunks.
        """
        from httpx import ReadTimeout
        from ..exceptions import TimeoutError, APIError
        
        logger.debug("Starting HTTP stream...")
        try:
            async with self.client.stream(
                method=self.method,
                url=self.url,
                headers=self.headers,
                data=self.data,
                **self.kwargs,
            ) as response:
                logger.debug(f"Response Status Code: {response.status_code}")
                if response.status_code != 200:
                    raise APIError(
                        f"Failed to generate streamed contents. Request failed with status code {response.status_code}"
                    )
                
                # Create the actual StreamedResponse to handle parsing
                streamed_response = StreamedResponse(
                    response_iterator=response.aiter_bytes(chunk_size=1024),
                    proxy=self.proxy,
                    cookies=self.cookies,
                )
                
                # Yield chunks from the actual response handler
                async for chunk in streamed_response:
                    yield chunk
                    
        except ReadTimeout:
            raise TimeoutError(
                "Generate content stream request timed out, please try again. If the problem persists, "
                "consider setting a higher `timeout` value when initializing GeminiClient."
            )