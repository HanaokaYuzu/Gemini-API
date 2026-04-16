import orjson as json
from pydantic import BaseModel

from ..constants import build_model_header, MODEL_HEADER_KEY, Model
from ..utils import get_nested_value


class AvailableModel(BaseModel):
    """
    Available model resolved dynamically from the Gemini RPC API.

    Combines model identity, display info, and request header building
    into a single class.  Headers are constructed at runtime from
    `model_id` and internal capacity attributes so the library stays
    up-to-date with new models without code changes.

    Parameters
    ----------
    model_id: `str`
        Hex identifier of the model (e.g. "9d8ca3786ebdfbea").
    model_name: `str`
        User-friendly name of the model (e.g. "gemini-3-pro").
    display_name: `str`
        Localised display name shown in the Gemini web UI (e.g. "Fast", "Thinking", "Pro").
    description: `str`
        Brief description of the model's capabilities.
    capacity: `int`
        Internal tier/capacity value.
    capacity_field: `int`
        Internal proto field number.
    is_available: `bool`, optional
        Whether the model is available for use based on account status. Defaults to `True`.
    """

    model_id: str
    model_name: str
    display_name: str
    description: str
    capacity: int
    capacity_field: int = 12
    is_available: bool = True

    def __str__(self) -> str:
        return self.model_name or self.display_name

    def __repr__(self) -> str:
        return (
            f"AvailableModel(model_id={self.model_id!r}, "
            f"model_name={self.model_name!r}, description={self.description!r})"
        )

    @property
    def model_header(self) -> dict[str, str]:
        """
        Dynamically build the request header for this model.

        Returns
        -------
        `dict[str, str]`
            A dictionary containing the required headers for model selection.
        """

        if self.capacity_field == 13:
            tail = f"null,{self.capacity}"
        else:
            tail = str(self.capacity)

        return build_model_header(self.model_id, tail)

    @property
    def advanced_only(self) -> bool:
        """
        Check if the model is restricted to Gemini Advanced/Plus tiers.
        """

        return not (self.capacity == 1 and self.capacity_field == 12)

    @staticmethod
    def compute_capacity(tier_flags: list, capability_flags: list) -> tuple[int, int]:
        """
        Derive (capacity, capacity_field) from account flags.

        Parameters
        ----------
        tier_flags : `list`
            Account tier flags from `part_body[16]`.
        capability_flags : `list`
            Account capabilities from `part_body[17]`.

        Returns
        -------
        `tuple[int, int]`
            A tuple of (capacity, capacity_field) for header construction.
        """

        # Highest priority: override capacity_field = 13
        if 21 in tier_flags:
            return 1, 13  # Not yet observed
        if 22 in tier_flags:
            return 2, 13  # Not yet observed

        # Priority order: capacity_field = 12
        if 115 in capability_flags:
            return 4, 12  # Plus accounts
        if 16 in tier_flags or 106 in capability_flags:
            return 3, 12  # Pro accounts (uncommon)
        if 8 in tier_flags or (106 not in capability_flags and 19 in capability_flags):
            return 2, 12  # Pro accounts

        return 1, 12  # Free accounts

    @staticmethod
    def build_model_id_name_mapping(
        capacity: int = 1,
        capacity_field: int = 12,
    ) -> dict[str, str]:
        """
        Build a mapping from `model_id` to `model_name` for all registered models,
        picking the canonical name that matches the caller's account tier.

        PLUS and ADVANCED tiers share `model_id` values with each other
        (differentiated only by the `capacity` header), so the target tier is
        chosen by the supplied `(capacity, capacity_field)` and the enum is
        walked in tier-priority order. Any `model_id` not found in the primary
        tier falls through to the next tier so the mapping stays complete.

        Parameters
        ----------
        capacity : `int`, optional
            Account capacity as returned by :meth:`compute_capacity`. Defaults
            to ``1`` (free tier) for backwards compatibility with callers that
            do not yet pass tier info.
        capacity_field : `int`, optional
            Account capacity proto field. Defaults to ``12``.

        Returns
        -------
        `dict[str, str]`
            Mapping of internal hex `model_id` to canonical `model_name`
            (e.g. ``"gemini-3-pro-plus"`` for a Plus-tier account).
        """

        # Tier priority order — which `Model` family's name we prefer for a
        # given (capacity, capacity_field). The primary tier matches the enum
        # family whose header was built with this same capacity value, so the
        # returned name is consistent with the header the account actually sends.
        # Fallback tiers fill any `model_id` the primary does not cover (e.g.
        # the `BASIC_*` ids that PLUS/ADVANCED do not share).
        if capacity == 4 and capacity_field == 12:
            tier_order = ("PLUS", "ADVANCED", "BASIC")
        elif capacity == 2 and capacity_field in (12, 13):
            tier_order = ("ADVANCED", "PLUS", "BASIC")
        elif capacity == 1 and capacity_field == 13:
            tier_order = ("PLUS", "ADVANCED", "BASIC")
        else:
            # capacity=1/field=12 — free tier — keeps the existing behaviour.
            tier_order = ("BASIC", "PLUS", "ADVANCED")

        result: dict[str, str] = {}
        for tier_prefix in tier_order:
            for member in Model:
                if member is Model.UNSPECIFIED:
                    continue
                if not member.name.startswith(f"{tier_prefix}_"):
                    continue

                header_value = member.model_header.get(MODEL_HEADER_KEY, "")
                if not header_value:
                    continue

                try:
                    parsed = json.loads(header_value)
                    model_id = get_nested_value(parsed, [4])
                except json.JSONDecodeError:
                    continue

                if model_id and model_id not in result:
                    result[model_id] = member.model_name

        return result
