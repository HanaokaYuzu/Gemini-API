import hashlib
import mimetypes
from datetime import datetime
from pathlib import Path
from textwrap import shorten
from typing import Any

from curl_cffi.requests import AsyncSession
from curl_cffi.requests.exceptions import HTTPError
from pydantic import BaseModel, ConfigDict

from ..constants import Headers
from ..utils import logger


class Image(BaseModel):
    """
    A single image object returned from Gemini.

    Parameters
    ----------
    url: `str`
        URL of the image.
    title: `str`, optional
        Title of the image, defaults to "[Image]".
    alt: `str`, optional
        Optional description of the image.
    proxy: `str`, optional
        Proxy used when saving image.
    client: `AsyncSession`, optional
        Used for saving file with authentication if needed.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    url: str
    title: str = "[Image]"
    alt: str = ""
    proxy: str | None = None
    client: AsyncSession | None = None
    _default_filename_suffix: str = "image"

    def _get_url_for_hash(self) -> str:
        return self.url

    def __str__(self):
        return f"Image(title={self.title!r}, alt={shorten(self.alt, width=100)!r}, url={self.url!r})"

    async def save(
        self,
        path: str = "temp",
        filename: str | None = None,
        verbose: bool = False,
        client: AsyncSession | None = None,
        **kwargs,
    ) -> str:
        """
        Saves the image to disk.

        Parameters
        ----------
        path: `str`, optional
            Directory path to save the image, defaults to "./temp".
        filename: `str | None`, optional
            File name to save the image. Defaults to a unique generated name.
        verbose: `bool`, optional
            If True, will print the path of the saved file or warning for invalid file name. Defaults to False.
        client: `AsyncSession | None`, optional
            Client used for requests.
        kwargs: `dict`, optional
            Additional arguments passed to the specific image's `_perform_save` implementation.
            For example, `GeneratedImage` accepts `full_size (bool)`.

        Returns
        -------
        `str`
            Absolute path of the saved image if successful.

        Raises
        ------
        `curl_cffi.requests.exceptions.HTTPError`
            If the network request failed.
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
    ) -> str:
        """
        Base implementation: simple download.
        """

        response = await req_client.get(self.url, headers=Headers.REFERER.value)
        if verbose:
            logger.debug(f"HTTP Request: GET {self.url} [{response.status_code}]")

        if response.status_code == 200:
            path_obj_file = Path(filename)
            if not path_obj_file.suffix:
                content_type = (
                    response.headers.get("content-type", "")
                    .split(";")[0]
                    .strip()
                    .lower()
                )
                ext = mimetypes.guess_extension(content_type) or ".png"
                filename = f"{filename}{ext}"

            dest = path_obj / filename
            dest.write_bytes(response.content)

            if verbose:
                logger.info(f"Image saved as {dest.resolve()}")

            return str(dest.resolve())
        else:
            raise HTTPError(
                f"Error downloading image: {response.status_code} {response.reason}"
            )


class WebImage(Image):
    """
    Image retrieved from web.

    Returned when asking Gemini to "SEND an image of [something]".
    """

    pass


class GeneratedImage(Image):
    """
    Image generated by Gemini.

    Returned when asking Gemini to "GENERATE an image of [something]".

    Parameters
    ----------
    client_ref: `GeminiClient`, optional
        Reference to the GeminiClient instance.
    cid: `str`, optional
        Chat ID.
    rid: `str`, optional
        Reply ID.
    rcid: `str`, optional
        Reply candidate ID.
    image_id: `str`, optional
        Image ID generated.
    """

    client_ref: Any = None
    cid: str = ""
    rid: str = ""
    rcid: str = ""
    image_id: str = ""

    # @override
    async def _perform_save(
        self,
        req_client: AsyncSession,
        path_obj: Path,
        filename: str,
        verbose: bool,
        full_size: bool = True,
    ) -> str:
        """
        Internal method for saving GeneratedImage, handling full size resolution.

        Parameters
        ----------
        req_client: `AsyncSession`
             Client used for requests.
        path_obj: `Path`
            Path to save the image.
        filename: `str`
            Base filename.
        verbose: `bool`
            Prints status if True.
        full_size: `bool`, optional
            Modifies preview URLs to fetch full-size images. Defaults to True.

        Returns
        -------
        `str`
            Absolute path of the saved image if successfully saved.
        """

        if full_size:
            if all([self.client_ref, self.cid, self.rid, self.rcid, self.image_id]):
                try:
                    original_url = await self.client_ref._get_full_size_image(
                        cid=self.cid,
                        rid=self.rid,
                        rcid=self.rcid,
                        image_id=self.image_id,
                    )
                    if original_url:
                        req_url = f"{original_url}=d-I?alr=yes"

                        response = await req_client.get(
                            req_url, headers=Headers.REFERER.value
                        )
                        response.raise_for_status()
                        url_text = response.text

                        response = await req_client.get(
                            url_text, headers=Headers.REFERER.value
                        )
                        response.raise_for_status()
                        self.url = response.text

                        return await super()._perform_save(
                            req_client, path_obj, filename, verbose
                        )

                except Exception as e:
                    logger.debug(
                        f"Failed to fetch full size image URL via RPC: {e}, falling back to default URL suffix."
                    )

            if "=s1024-rj" in self.url:
                self.url = self.url.replace("=s1024-rj", "=s2048-rj")
            elif "=s2048-rj" not in self.url:
                self.url += "=s2048-rj"
        else:
            if "=s2048-rj" in self.url:
                self.url = self.url.replace("=s2048-rj", "=s1024-rj")
            elif "=s1024-rj" not in self.url:
                self.url += "=s1024-rj"

        return await super()._perform_save(req_client, path_obj, filename, verbose)
