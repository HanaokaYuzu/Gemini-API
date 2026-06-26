import asyncio
import hashlib
import mimetypes
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from curl_cffi.requests import AsyncSession
from curl_cffi.requests.exceptions import HTTPError
from pydantic import BaseModel, ConfigDict

from ..constants import Headers
from ..utils import logger


class Video(BaseModel):
    """
    A single video object returned from Gemini.

    Parameters
    ----------
    url: `str`
        URL of the video.
    title: `str`, optional
        Title of the video. Defaults to "[Video]".
    proxy: `str`, optional
        Proxy used when saving video.
    client: `AsyncSession`, optional
        Used for saving file with authentication if needed.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    url: str
    title: str = "[Video]"
    proxy: str | None = None
    client: AsyncSession | None = None
    _default_filename_suffix: str = "video"

    def _get_url_for_hash(self) -> str:
        return self.url

    def __repr__(self) -> str:
        return f"Video(title={self.title!r}, url={self.url!r})"

    async def save(
        self,
        path: str = "temp",
        filename: str | None = None,
        verbose: bool = False,
        client: AsyncSession | None = None,
        **kwargs,
    ) -> Any:
        """
        Saves the video to disk.

        Parameters
        ----------
        path: `str`, optional
            Path to save the video. Defaults to "./temp".
        filename: `str | None`, optional
            File name to save the video. Defaults to a unique generated name.
        verbose: `bool`, optional
            If True, will print the path of the saved file.
        client: `AsyncSession | None`, optional
            Client used for requests.
        kwargs: `dict`, optional
            Additional arguments passed to the specific media's `_perform_save` implementation.
            For example, `GeneratedMedia` accepts `download_type (Literal["audio", "video", "both"])`.

        Returns
        -------
        dict[str, str | None]
            The result of the `_perform_save` method (usually a dict of paths).
        """

        if not filename or not Path(filename).suffix:
            timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
            url_hash = hashlib.sha256(self._get_url_for_hash().encode()).hexdigest()[
                :10
            ]
            base_name = (
                Path(filename).stem if filename else self._default_filename_suffix
            )
            filename = f"{timestamp}_{url_hash}_{base_name}"

        close_client = False
        req_client = client or self.client
        if not req_client:
            client_ref = getattr(self, "client_ref", None)
            cookies = getattr(client_ref, "cookies", None) if client_ref else None
            req_client = AsyncSession(
                impersonate="chrome",
                allow_redirects=True,
                cookies=cookies,
                proxy=self.proxy,
            )
            close_client = True

        try:
            path_obj = Path(path)
            path_obj.mkdir(parents=True, exist_ok=True)
            return await self._perform_save(
                req_client, path_obj, filename, verbose, **kwargs
            )
        finally:
            if close_client:
                await req_client.close()

    async def _perform_save(
        self, req_client: AsyncSession, path_obj: Path, filename: str, verbose: bool
    ) -> dict[str, str | None]:
        """
        Base implementation: simple download.
        """

        path = await self._download_file(
            req_client, self.url, path_obj, filename, ".mp4", verbose
        )
        return {"video": path, "video_thumbnail": None}

    @staticmethod
    async def _download_file(
        req_client: AsyncSession,
        url: str,
        path_obj: Path,
        filename: str,
        default_ext: str = ".mp4",
        verbose: bool = False,
    ) -> str | None:
        """
        Internal helper to download a file and determine its extension.
        """

        response = await req_client.get(url, headers=Headers.REFERER.value)
        if verbose:
            logger.debug(f"HTTP Request: GET {url} [{response.status_code}]")

        if response.status_code == 200:
            path_obj_file = Path(filename)
            if not path_obj_file.suffix:
                content_type = (
                    response.headers.get("content-type", "")
                    .split(";")[0]
                    .strip()
                    .lower()
                )
                ext = mimetypes.guess_extension(content_type) or default_ext
                filename = f"{filename}{ext}"

            dest = path_obj / filename
            dest.write_bytes(response.content)

            if verbose:
                logger.info(f"File saved as {dest.resolve()}")

            return str(dest.resolve())
        elif response.status_code == 206:
            return "206"
        else:
            raise HTTPError(
                f"Error downloading file: {response.status_code} {response.reason}"
            )


class GeneratedVideo(Video):
    """
    Video generated by Gemini.

    Parameters
    ----------
    client_ref: `GeminiClient`, optional
        Reference to the GeminiClient instance.
    thumbnail: `str`, optional
        URL of the video thumbnail.
    cid: `str`, optional
        Chat ID.
    rid: `str`, optional
        Reply ID.
    rcid: `str`, optional
        Reply candidate ID.
    """

    client_ref: Any = None
    thumbnail: str = ""
    cid: str = ""
    rid: str = ""
    rcid: str = ""

    # @override
    async def _perform_save(
        self, req_client: AsyncSession, path_obj: Path, filename: str, verbose: bool
    ) -> dict[str, str | None]:
        """
        Internal method for GeneratedVideo, handling thumbnails and polling.
        """

        thumb_path = None
        if self.thumbnail:
            thumb_base = Path(filename).stem
            try:
                thumb_path = await self._download_file(
                    req_client, self.thumbnail, path_obj, thumb_base, ".jpg", verbose
                )
            except Exception as e:
                if verbose:
                    logger.warning(f"Failed to save thumbnail: {e}")

        while True:
            video_path = await self._download_file(
                req_client, self.url, path_obj, filename, ".mp4", verbose
            )

            if video_path == "206":
                if verbose:
                    logger.info("Video still generating (206), retrying in 10s...")
                await asyncio.sleep(10)
            else:
                return {"video": video_path, "video_thumbnail": thumb_path}


class GeneratedMedia(GeneratedVideo):
    """
    Media (audio/video) generated by Google's AI.

    Parameters
    ----------
    mp3_url: `str`, optional
        URL of the audio (mp3).
    mp3_thumbnail: `str`, optional
        URL of the audio thumbnail.
    title: `str`, optional
        Title. Defaults to "[Media]".

    Refers to `GeneratedVideo` for inherited attributes and saving logic.
    """

    mp3_url: str = ""
    mp3_thumbnail: str = ""
    title: str = "[Media]"
    _default_filename_suffix: str = "media"

    def _get_url_for_hash(self) -> str:
        return self.url or self.mp3_url

    @property
    def mp4_url(self) -> str:
        return self.url

    @mp4_url.setter
    def mp4_url(self, value: str):
        self.url = value

    @property
    def mp4_thumbnail(self) -> str:
        return self.thumbnail

    @mp4_thumbnail.setter
    def mp4_thumbnail(self, value: str):
        self.thumbnail = value

    def __repr__(self) -> str:
        urls = []
        if self.url:
            urls.append(f"mp4={self.url!r}")
        if self.mp3_url:
            urls.append(f"mp3={self.mp3_url!r}")
        return f"GeneratedMedia(title={self.title!r}, urls={', '.join(urls)!r})"

    # @override
    async def _perform_save(
        self,
        req_client: AsyncSession,
        path_obj: Path,
        filename: str,
        verbose: bool,
        download_type: Literal["audio", "video", "both"] = "both",
    ) -> dict[str, str | None]:
        """
        Internal method for GeneratedMedia, handling audio/video downloads and polling.

        Parameters
        ----------
        req_client: `AsyncSession`
            Client used for requests.
        path_obj: `Path`
            Destination path object.
        filename: `str`
            Base filename.
        verbose: `bool`
            Prints status if True.
        download_type: `Literal["audio", "video", "both"]`, optional
            Specifies which media type(s) to download. Defaults to "both".

        Returns
        -------
        `dict[str, str | None]`
            A dictionary containing absolute paths of the downloaded files
            (e.g., {"audio": ..., "video": ..., "audio_thumbnail": ..., "video_thumbnail": ...}).
        """

        results: dict[str, str | None] = {}
        tasks = []

        if download_type in ["audio", "both"] and self.mp3_url:
            tasks.append(
                self._download_with_polling(
                    req_client,
                    self.mp3_url,
                    path_obj,
                    filename,
                    ".mp3",
                    verbose,
                    "audio",
                )
            )
            if self.mp3_thumbnail:
                tasks.append(
                    self._download_thumbnail(
                        req_client,
                        self.mp3_thumbnail,
                        path_obj,
                        filename + "_audio_thumb",
                        verbose,
                        "audio_thumbnail",
                    )
                )

        if download_type in ["video", "both"] and self.url:
            tasks.append(
                self._download_with_polling(
                    req_client,
                    self.url,
                    path_obj,
                    filename,
                    ".mp4",
                    verbose,
                    "video",
                )
            )
            if self.thumbnail:
                tasks.append(
                    self._download_thumbnail(
                        req_client,
                        self.thumbnail,
                        path_obj,
                        filename + "_video_thumb",
                        verbose,
                        "video_thumbnail",
                    )
                )

        downloaded = await asyncio.gather(*tasks)
        for key, file_path in downloaded:
            results[key] = file_path

        return results

    @staticmethod
    async def _download_with_polling(
        req_client: AsyncSession,
        url: str,
        path_obj: Path,
        filename: str,
        ext: str,
        verbose: bool,
        key: str,
    ) -> tuple[str, str | None]:
        while True:
            path = await Video._download_file(
                req_client, url, path_obj, filename, ext, verbose
            )
            if path == "206":
                if verbose:
                    logger.info(
                        f"Media ({key}) still generating (206), retrying in 10s..."
                    )
                await asyncio.sleep(10)
            else:
                return key, path

    @staticmethod
    async def _download_thumbnail(
        req_client: AsyncSession,
        url: str,
        path_obj: Path,
        filename: str,
        verbose: bool,
        key: str,
    ) -> tuple[str, str | None]:
        try:
            path = await Video._download_file(
                req_client, url, path_obj, filename, ".jpg", verbose
            )
            return key, path
        except Exception as e:
            if verbose:
                logger.warning(f"Failed to save thumbnail ({key}): {e}")
            return key, None
