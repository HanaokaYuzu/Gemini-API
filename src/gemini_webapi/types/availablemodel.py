import orjson as json
from pydantic import BaseModel, Field

from ..constants import build_model_header, MODEL_HEADER_KEY, Model
from ..utils import get_nested_value


class AvailableModel(BaseModel):
    """
    Available model resolved dynamically from the Gemini RPC API.

    Combines model identity, display info, and request header building
    into a single class.  Headers are constructed at runtime from
    `model_id` and internal capacity attributes so the library stays
    up-to-date with new models without code changes.

    Note: `capacity` and `capacity_field` are internal attributes
    and are excluded from public fields/serialization.

    Parameters
    ----------
    model_id: `str`
        Hex identifier of the model (e.g. "9d8ca3786ebdfbea").
    model_name: `str`
        User-friendly name of the model (e.g. "gemini-3-pro").
    display_name: `str`
        Localised display name shown in the Gemini web UI (e.g. "Fast/Thinking/Pro").
    description: `str`
        Brief description of the model's capabilities.
    capacity: `int`
        Internal tier/capacity value.
    capacity_field: `int`
        Internal proto field number.
    """

    model_id: str
    model_name: str
    display_name: str
    description: str
    capacity: int = Field(exclude=True, repr=False)
    capacity_field: int = Field(default=12, exclude=True, repr=False)

    def __str__(self) -> str:
        return self.model_name or self.display_name

    def __repr__(self) -> str:
        return (
            f"AvailableModel(model_id={self.model_id!r}, "
            f"model_name={self.model_name!r}, description={self.description!r})"
        )

    @property
    def model_header(self) -> dict[str, str]:
        """Dynamically build the request header from model_id and capacity."""

        if self.capacity_field == 13:
            tail = f"null,{self.capacity}"
        else:
            tail = str(self.capacity)

        return build_model_header(self.model_id, tail)

    @property
    def advanced_only(self) -> bool:
        """Basic tier has capacity=1 and capacity_field=12 exclusively."""

        return not (self.capacity == 1 and self.capacity_field == 12)

    @staticmethod
    def compute_capacity(tier_flags: list, capability_flags: list) -> tuple[int, int]:
        """
        Derive (capacity, capacity_field) from account flags.

        Parameters
        ----------
        tier_flags : list
            part_body[16] — account tier flags.
        capability_flags : list
            part_body[17] — account capabilities.

        Returns
        -------
        tuple[int, int]
            (capacity, capacity_field)
        """

        # highest priority: override capacity_field = 13
        if 21 in tier_flags:
            return 1, 13
        if 22 in tier_flags:
            return 2, 13

        # priority order: capacity_field = 12
        if 115 in capability_flags:
            return 4, 12
        if 16 in tier_flags or 106 in capability_flags:
            return 3, 12
        if 8 in tier_flags or (106 not in capability_flags and 19 in capability_flags):
            return 2, 12

        return 1, 12

    @staticmethod
    def build_model_id_name_mapping() -> dict[str, str]:
        """Build a `model_id` to `model_name` mapping from the :class:`Model` enum."""

        result: dict[str, str] = {}
        for member in Model:
            if member is Model.UNSPECIFIED:
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
                # Use basic model name without tier suffix regardless of the actual tier
                base_key = "BASIC_" + member.name.split("_", 1)[-1]
                base_member = getattr(Model, base_key, member)
                result[model_id] = base_member.model_name

        return result
