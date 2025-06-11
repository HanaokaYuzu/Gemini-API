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


class GemJar(list):
    """
    Helper class for handling a collection of `Gem` objects.
    This class extends `list` to allow retrieving gems with extra filtering options.
    """

    def get(
        self, id: str = None, name: str = None, default: Gem | None = None
    ) -> Gem | None:
        """
        Retrieves a gem by its id and/or name.
        If both id and name are provided, returns the gem that matches both id and name.

        Parameters
        ----------
        id: `str`, optional
            The unique identifier of the gem to retrieve.
        name: `str`, optional
            The user-friendly name of the gem to retrieve.
        default: `Gem`, optional
            The default value to return if no matching gem is found.
        """

        assert not (
            id is None and name is None
        ), "At least one of gem id or name must be provided."

        for gem in self:
            if id is not None and gem.id != id:
                continue
            if name is not None and gem.name != name:
                continue
            return gem

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
            If provided, filters gems by their name.
        """

        filtered_gems = GemJar()
        for gem in self:
            if predefined is not None and gem.predefined != predefined:
                continue
            if name is not None and gem.name != name:
                continue
            filtered_gems.append(gem)

        return filtered_gems
