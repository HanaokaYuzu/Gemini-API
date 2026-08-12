from collections.abc import ItemsView, Iterable, Iterator, KeysView, Mapping, ValuesView
from textwrap import shorten

from pydantic import BaseModel


class Gem(BaseModel):
    """Reusable Gemini Gem object working as a system prompt, providing additional context to the model.
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
        return f"Gem(id={self.id!r}, name={self.name!r}, predefined={self.predefined!r})"

    def __repr__(self) -> str:
        desc = shorten(self.description, width=100) if self.description else "No description"
        prompt = shorten(self.prompt, width=100) if self.prompt else "No prompt"
        return (
            f"Gem(id={self.id!r}, name={self.name!r}, description={desc!r}, "
            f"prompt={prompt!r}, predefined={self.predefined})"
        )


class GemJar:
    """Helper class for handling a collection of `Gem` objects, stored by their ID.

    Behaves like a read-mostly mapping of gem id to `Gem`, with two deliberate
    differences that are why this is not a `dict` subclass: iterating a jar yields
    the gems themselves rather than their ids, and `get()` looks gems up by id
    and/or name instead of taking a key and a default.

    Parameters
    ----------
    gems: `Iterable[tuple[str, Gem]] | Mapping[str, Gem]`, optional
        Initial gems, given either as (id, gem) pairs or as a mapping of id to gem.

    """

    def __init__(self, gems: Iterable[tuple[str, Gem]] | Mapping[str, Gem] | None = None):
        self._gems: dict[str, Gem] = dict(gems) if gems is not None else {}

    def __iter__(self) -> Iterator[Gem]:
        """Iter over the gems in the jar."""
        return iter(self._gems.values())

    def __len__(self) -> int:
        return len(self._gems)

    def __contains__(self, id: object) -> bool:
        return id in self._gems

    def __getitem__(self, id: str) -> Gem:
        return self._gems[id]

    def __setitem__(self, id: str, gem: Gem) -> None:
        self._gems[id] = gem

    def __delitem__(self, id: str) -> None:
        del self._gems[id]

    def __eq__(self, other: object) -> bool:
        if isinstance(other, GemJar):
            return self._gems == other._gems
        return NotImplemented

    def __repr__(self) -> str:
        return f"GemJar({self._gems!r})"

    def keys(self) -> KeysView[str]:
        """Returns a view of the gem ids in the jar."""
        return self._gems.keys()

    def values(self) -> ValuesView[Gem]:
        """Returns a view of the gems in the jar."""
        return self._gems.values()

    def items(self) -> ItemsView[str, Gem]:
        """Returns a view of the (gem id, gem) pairs in the jar."""
        return self._gems.items()

    def get(
        self, id: str | None = None, name: str | None = None, default: Gem | None = None
    ) -> Gem | None:
        """Retrieves a gem by its id and/or name.
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
        assert id is not None or name is not None, (
            "At least one of gem id or name must be provided."
        )

        if id is not None:
            gem_candidate = self._gems.get(id)
            if gem_candidate:
                if (name is not None and gem_candidate.name == name) or name is None:
                    return gem_candidate
                return default
            return default
        if name is not None:
            return next(
                (gem_obj for gem_obj in self.values() if gem_obj.name == name),
                default,
            )
        # Should be unreachable due to the assertion.
        return default

    def filter(self, predefined: bool | None = None, name: str | None = None) -> "GemJar":
        """Returns a new `GemJar` containing gems that match the given filters.

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

        return filtered_gems
