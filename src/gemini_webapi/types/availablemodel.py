import contextlib
import re
from typing import Any

import orjson as json
from pydantic import BaseModel

from gemini_webapi.constants import GRPC, MODEL_HEADER_KEY, build_model_header
from gemini_webapi.utils.parsing import extract_json_from_response, get_nested_value

_VERSION_RE = re.compile(r"(\d+)(?:\.\d+)?")


class AvailableModel(BaseModel):
    """Available model resolved dynamically from the Gemini RPC API.

    Combines model identity, display info, and request header building
    into a single class. Headers are constructed at runtime from
    `model_id` and internal capacity attributes so the library stays
    up-to-date with new models without code changes.

    Parameters
    ----------
    model_id: `str`
        Hex identifier of the model.
    model_name: `str`
        User-friendly name of the model.
    display_name: `str`
        Localised display name shown in the Gemini web UI.
    description: `str`
        Brief description of the model's capabilities.
    capacity: `int`
        Internal tier/capacity value.
    capacity_field: `int`
        Internal proto field number.
    model_number: `int`
        Internal model number mirrored into generation request payloads.
    is_available: `bool`, optional
        Whether this session may select the model. True for every model an account is shown;
        false for all but the default model of a guest session. Defaults to `True`.
    aliases: `list[str]`, optional
        Alternative names and identifiers matching this model.

    """

    model_id: str
    model_name: str
    display_name: str
    description: str
    capacity: int
    capacity_field: int = 12
    model_number: int = 1
    is_available: bool = True
    aliases: list[str] = []

    def __str__(self) -> str:
        return self.model_name or self.display_name

    def __repr__(self) -> str:
        return (
            f"AvailableModel(model_id={self.model_id!r}, "
            f"model_name={self.model_name!r}, description={self.description!r})"
        )

    @property
    def model_header(self) -> dict[str, str]:
        """Dynamically build the request header for this model.

        Returns
        -------
        `dict[str, str]`
            A dictionary containing the required headers for model selection.

        """
        tail = f"null,{self.capacity}" if self.capacity_field == 13 else str(self.capacity)

        return build_model_header(self.model_id, tail, self.model_number)

    @property
    def advanced_only(self) -> bool:
        """Check if the model is restricted to Gemini Advanced/Plus tiers."""
        return self.capacity != 1 or self.capacity_field != 12

    @staticmethod
    def compute_capacity(tier_flags: list, capability_flags: list) -> tuple[int, int]:
        """Derive (capacity, capacity_field) from account flags.

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
        return (
            (2, 12) if 8 in tier_flags or 19 in capability_flags else (1, 12)
        )  # Pro accounts else Free accounts

    @classmethod
    def _derive_name_and_aliases(
        cls,
        model_id: str,
        category_name: str,
        display_name: str,
    ) -> tuple[str, list[str]]:
        """Derive canonical `model_name` and lookup `aliases` dynamically and generically
        without hardcoded model or category names.
        """
        aliases_set: set[str] = set()

        if model_id:
            aliases_set.add(model_id.lower())

        cat_clean = category_name.strip()
        disp_clean = display_name.strip()

        match = _VERSION_RE.search(disp_clean)
        major_ver = match.group(1) if match else None
        if cat_clean:
            cat_slug = cat_clean.lower().replace(" ", "-")
            aliases_set.add(cat_clean.lower())
            aliases_set.add(cat_slug)
            aliases_set.add(f"gemini-{cat_slug}")
            if major_ver:
                aliases_set.add(f"gemini-{major_ver}-{cat_slug}")

        if disp_clean:
            disp_slug = disp_clean.lower().replace(" ", "-")
            aliases_set.add(disp_clean.lower())
            aliases_set.add(disp_slug)
            aliases_set.add(f"gemini-{disp_slug}")

        if cat_clean:
            cat_slug = cat_clean.lower().replace(" ", "-")
            primary_name = f"gemini-{cat_slug}"
        elif disp_clean:
            disp_slug = disp_clean.lower().replace(" ", "-")
            primary_name = f"gemini-{disp_slug}"
        else:
            primary_name = f"gemini-{model_id}"

        aliases_set.add(primary_name)
        return primary_name, sorted(aliases_set)

    @classmethod
    def from_rpc(
        cls,
        model_data: list,
        capacity: int = 1,
        capacity_field: int = 12,
        unavailable: bool = False,
    ) -> "AvailableModel | None":
        """Dynamically construct an :class:`AvailableModel` instance from a single model list item in RPC part_body[15].

        Pass `unavailable` for a model this session may not select - every model but the first
        for a guest. It is the only thing that clears `is_available`.
        """
        if not isinstance(model_data, list) or not model_data:
            return None

        model_id = get_nested_value(model_data, [0], "")
        if not model_id or not isinstance(model_id, str):
            return None

        category_name = str(
            get_nested_value(model_data, [1], "") or get_nested_value(model_data, [10], "")
        )
        display_name = str(
            get_nested_value(model_data, [11], "")
            or get_nested_value(model_data, [19], "")
            or get_nested_value(model_data, [1], "")
        )
        description = str(
            get_nested_value(model_data, [12], "") or get_nested_value(model_data, [2], "")
        )

        raw_number = get_nested_value(model_data, [17])
        if isinstance(raw_number, int):
            model_number = raw_number
        else:
            raw_secondary = get_nested_value(model_data, [9])
            model_number = raw_secondary if isinstance(raw_secondary, int) else 1

        # Only the session decides - an account may use every model it is shown, a guest may
        # only use the default one.
        is_available = not unavailable

        model_name, aliases = cls._derive_name_and_aliases(
            model_id=model_id,
            category_name=category_name,
            display_name=display_name,
        )

        return cls(
            model_id=model_id,
            model_name=model_name,
            display_name=display_name or category_name or model_id,
            description=description,
            capacity=capacity,
            capacity_field=capacity_field,
            model_number=model_number,
            is_available=is_available,
            aliases=aliases,
        )

    @classmethod
    def from_dict(cls, model_dict: dict) -> "AvailableModel":
        """Construct an :class:`AvailableModel` from a custom dictionary."""
        if "model_name" not in model_dict or "model_header" not in model_dict:
            raise ValueError(
                "When passing a custom model as a dictionary, 'model_name' and 'model_header' keys must be provided."
            )

        model_header = model_dict["model_header"]
        if not isinstance(model_header, dict):
            raise ValueError(
                "When passing a custom model as a dictionary, 'model_header' must be a dictionary containing valid header strings."
            )

        model_name = str(model_dict["model_name"])
        header_val = model_header.get(MODEL_HEADER_KEY, "")
        model_id = ""
        model_number = 1
        if header_val:
            with contextlib.suppress(Exception):
                parsed = json.loads(header_val)
                model_id = get_nested_value(parsed, [4], "")
                if parsed and isinstance(parsed[-1], int):
                    model_number = parsed[-1]
        return cls(
            model_id=model_id or "custom",
            model_name=model_name,
            display_name=str(model_dict.get("display_name", model_name)),
            description=str(model_dict.get("description", "Custom model")),
            capacity=int(model_dict.get("capacity", 1)),
            capacity_field=int(model_dict.get("capacity_field", 12)),
            model_number=model_number,
            is_available=True,
            aliases=[model_name.lower()],
        )

    @classmethod
    def parse_models_from_rpc(
        cls,
        payload_data: Any,
        target_id: str = GRPC.GET_USER_STATUS,
        unauthenticated: bool = False,
    ) -> list["AvailableModel"]:
        """Parse all available models from an RPC response (raw string or nested JSON structure)."""
        if isinstance(payload_data, str):
            frames = extract_json_from_response(payload_data)
        elif isinstance(payload_data, list):
            frames = payload_data
        else:
            return []

        models: list[AvailableModel] = []
        for part in frames:
            part_body = None
            if isinstance(part, list) and len(part) >= 3:
                rpc_id = get_nested_value(part, [1])
                if target_id and rpc_id and rpc_id != target_id:
                    continue

                body_str = get_nested_value(part, [2])
                if isinstance(body_str, str):
                    try:
                        part_body = json.loads(body_str)
                    except Exception:
                        part_body = None
                elif isinstance(body_str, list):
                    part_body = body_str

            if part_body is None and isinstance(part, list):
                part_body = part

            if isinstance(part_body, list):
                models_list = get_nested_value(part_body, [15])
                if isinstance(models_list, list):
                    tier_flags = get_nested_value(part_body, [16], [])
                    tier_flags = tier_flags if isinstance(tier_flags, list) else []
                    capability_flags = get_nested_value(part_body, [17], [])
                    capability_flags = (
                        capability_flags if isinstance(capability_flags, list) else []
                    )
                    capacity, capacity_field = cls.compute_capacity(tier_flags, capability_flags)

                    for m_data in models_list:
                        if m_instance := cls.from_rpc(
                            model_data=m_data,
                            capacity=capacity,
                            capacity_field=capacity_field,
                            # Guest sessions may only use the default model, listed first
                            unavailable=unauthenticated and bool(models),
                        ):
                            models.append(m_instance)
                    if models:
                        break
        return models
