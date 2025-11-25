import itertools

import orjson as json

from ..constants import GRPC
from ..exceptions import APIError
from ..types import Gem, GemJar, RPCData
from ..utils import running, logger


class GemMixin:
    """
    Mixin class providing gem-related functionality for GeminiClient.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._gems: GemJar | None = None

    @property
    def gems(self) -> GemJar:
        """
        Returns a `GemJar` object containing cached gems.
        Only available after calling `GeminiClient.fetch_gems()`.

        Returns
        -------
        :class:`GemJar`
            Refer to `gemini_webapi.types.GemJar`.

        Raises
        ------
        `RuntimeError`
            If `GeminiClient.fetch_gems()` has not been called before accessing this property.
        """

        if self._gems is None:
            raise RuntimeError(
                "Gems not fetched yet. Call `GeminiClient.fetch_gems()` method to fetch gems from gemini.google.com."
            )

        return self._gems

    @running(retry=2)
    async def fetch_gems(self, include_hidden: bool = False, **kwargs) -> GemJar:
        """
        Get a list of available gems from gemini, including system predefined gems and user-created custom gems.

        Note that network request will be sent every time this method is called.
        Once the gems are fetched, they will be cached and accessible via `GeminiClient.gems` property.

        Parameters
        ----------
        include_hidden: `bool`, optional
            There are some predefined gems that by default are not shown to users (and therefore may not work properly).
            Set this parameter to `True` to include them in the fetched gem list.

        Returns
        -------
        :class:`GemJar`
            Refer to `gemini_webapi.types.GemJar`.
        """

        response = await self._batch_execute(
            [
                RPCData(
                    rpcid=GRPC.LIST_GEMS,
                    payload="[4]" if include_hidden else "[3]",
                    identifier="system",
                ),
                RPCData(
                    rpcid=GRPC.LIST_GEMS,
                    payload="[2]",
                    identifier="custom",
                ),
            ],
            **kwargs,
        )

        try:
            response_json = json.loads(response.text.split("\n")[2])

            predefined_gems, custom_gems = [], []

            for part in response_json:
                if part[-1] == "system":
                    predefined_gems = json.loads(part[2])[2]
                elif part[-1] == "custom":
                    if custom_gems_container := json.loads(part[2]):
                        custom_gems = custom_gems_container[2]

            if not predefined_gems and not custom_gems:
                raise Exception
        except Exception:
            await self.close()
            logger.debug(f"Invalid response: {response.text}")
            raise APIError(
                "Failed to fetch gems. Invalid response data received. Client will try to re-initialize on next request."
            )

        self._gems = GemJar(
            itertools.chain(
                (
                    (
                        gem[0],
                        Gem(
                            id=gem[0],
                            name=gem[1][0],
                            description=gem[1][1],
                            prompt=gem[2] and gem[2][0] or None,
                            predefined=True,
                        ),
                    )
                    for gem in predefined_gems
                ),
                (
                    (
                        gem[0],
                        Gem(
                            id=gem[0],
                            name=gem[1][0],
                            description=gem[1][1],
                            prompt=gem[2] and gem[2][0] or None,
                            predefined=False,
                        ),
                    )
                    for gem in custom_gems
                ),
            )
        )

        return self._gems

    @running(retry=2)
    async def create_gem(self, name: str, prompt: str, description: str = "") -> Gem:
        """
        Create a new custom gem.

        Parameters
        ----------
        name: `str`
            Name of the custom gem.
        prompt: `str`
            System instructions for the custom gem.
        description: `str`, optional
            Description of the custom gem (has no effect on the model's behavior).

        Returns
        -------
        :class:`Gem`
            The created gem.
        """

        response = await self._batch_execute(
            [
                RPCData(
                    rpcid=GRPC.CREATE_GEM,
                    payload=json.dumps(
                        [
                            [
                                name,
                                description,
                                prompt,
                                None,
                                None,
                                None,
                                None,
                                None,
                                0,
                                None,
                                1,
                                None,
                                None,
                                None,
                                [],
                            ]
                        ]
                    ).decode(),
                )
            ]
        )

        try:
            response_json = json.loads(response.text.split("\n")[2])
            gem_id = json.loads(response_json[0][2])[0]
        except Exception:
            await self.close()
            logger.debug(f"Invalid response: {response.text}")
            raise APIError(
                "Failed to create gem. Invalid response data received. Client will try to re-initialize on next request."
            )

        return Gem(
            id=gem_id,
            name=name,
            description=description,
            prompt=prompt,
            predefined=False,
        )

    @running(retry=2)
    async def update_gem(
        self, gem: Gem | str, name: str, prompt: str, description: str = ""
    ) -> Gem:
        """
        Update an existing custom gem.

        Parameters
        ----------
        gem: `Gem | str`
            Gem to update, can be either a `gemini_webapi.types.Gem` object or a gem id string.
        name: `str`
            New name for the custom gem.
        prompt: `str`
            New system instructions for the custom gem.
        description: `str`, optional
            New description of the custom gem (has no effect on the model's behavior).

        Returns
        -------
        :class:`Gem`
            The updated gem.
        """

        if isinstance(gem, Gem):
            gem_id = gem.id
        else:
            gem_id = gem

        await self._batch_execute(
            [
                RPCData(
                    rpcid=GRPC.UPDATE_GEM,
                    payload=json.dumps(
                        [
                            gem_id,
                            [
                                name,
                                description,
                                prompt,
                                None,
                                None,
                                None,
                                None,
                                None,
                                0,
                                None,
                                1,
                                None,
                                None,
                                None,
                                [],
                                0,
                            ],
                        ]
                    ).decode(),
                )
            ]
        )

        return Gem(
            id=gem_id,
            name=name,
            description=description,
            prompt=prompt,
            predefined=False,
        )

    @running(retry=2)
    async def delete_gem(self, gem: Gem | str, **kwargs) -> None:
        """
        Delete a custom gem.

        Parameters
        ----------
        gem: `Gem | str`
            Gem to delete, can be either a `gemini_webapi.types.Gem` object or a gem id string.
        """

        if isinstance(gem, Gem):
            gem_id = gem.id
        else:
            gem_id = gem

        await self._batch_execute(
            [RPCData(rpcid=GRPC.DELETE_GEM, payload=json.dumps([gem_id]).decode())],
            **kwargs,
        )
