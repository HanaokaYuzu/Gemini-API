from pydantic import BaseModel


class Gem(BaseModel):
    """
    Reusable Gemini Gem object working as a system prompt, providing additional context to the model.
    Gemini provides a set of predefined gems, and users can create custom gems as well.

    Parameters
    ----------
    id: `str`
        Unique identifier for the gem.
    name: `str`
        User-friendly name of the gem.
    description: `str`, optional
        Brief description of the gem's purpose or content.
    prompt: `str`, optional
        The system prompt text that the gem provides to the model.
    predefined: `bool`
        Indicates whether the gem is predefined by Gemini or created by the user.
    """

    id: str
    name: str
    description: str | None = None
    prompt: str | None = None
    predefined: bool

    def __str__(self) -> str:
        return (
            f"Gem(id='{self.id}', name='{self.name}', description='{self.description}', "
            f"prompt='{self.prompt}', predefined={self.predefined})"
        )


class GemJar(dict[str, Gem]):
    """
    Helper class for handling a collection of `Gem` objects, stored by their ID.
    This class extends `dict` to allows retrieving gems with extra filtering options.
    """

    def __iter__(self):
        """
        Iter over the gems in the jar.
        """

        return self.values().__iter__()

    def get(
        self, id: str | None = None, name: str | None = None, default: Gem | None = None
    ) -> Gem | None:
        """
        Retrieves a gem by its id and/or name.
        If both id and name are provided, returns the gem that matches both id and name.
        If only id is provided, it's a direct lookup.
        If only name is provided, it searches through the gems.

        Parameters
        ----------
        id: `str`, optional
            The unique identifier of the gem to retrieve.
        name: `str`, optional
            The user-friendly name of the gem to retrieve.
        default: `Gem`, optional
            The default value to return if no matching gem is found.

        Returns
        -------
        `Gem` | None
            The matching gem if found, otherwise return the default value.

        Raises
        ------
        `AssertionError`
            If neither id nor name is provided.
        """

        assert not (
            id is None and name is None
        ), "At least one of gem id or name must be provided."

        if id is not None:
            gem_candidate = super().get(id)
            if gem_candidate:
                if name is not None:
                    if gem_candidate.name == name:
                        return gem_candidate
                    else:
                        return default
                else:
                    return gem_candidate
            else:
                return default
        elif name is not None:
            for gem_obj in self.values():
                if gem_obj.name == name:
                    return gem_obj
            return default

        # Should be unreachable due to the assertion.
        return default

    def filter(
        self, predefined: bool | None = None, name: str | None = None
    ) -> "GemJar":
        """
        Returns a new `GemJar` containing gems that match the given filters.

        Parameters
        ----------
        predefined: `bool`, optional
            If provided, filters gems by whether they are predefined (True) or user-created (False).
        name: `str`, optional
            If provided, filters gems by their name (exact match).

        Returns
        -------
        `GemJar`
            A new `GemJar` containing the filtered gems. Can be empty if no gems match the criteria.
        """

        filtered_gems = GemJar()

        for gem_id, gem in self.items():
            if predefined is not None and gem.predefined != predefined:
                continue
            if name is not None and gem.name != name:
                continue

            filtered_gems[gem_id] = gem

        return GemJar(filtered_gems)
