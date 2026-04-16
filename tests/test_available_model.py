import unittest

from gemini_webapi.constants import Model, MODEL_HEADER_KEY
from gemini_webapi.types import AvailableModel
from gemini_webapi.utils import get_nested_value

import orjson as json


def _id_for(member: Model) -> str:
    header = member.model_header.get(MODEL_HEADER_KEY, "")
    return get_nested_value(json.loads(header), [4], "")


class TestBuildModelIdNameMapping(unittest.TestCase):
    """The mapping must return names whose tier matches the account's capacity,
    because the caller uses the returned name to construct headers, and using a
    wrong-tier name produces requests Google may reject or silently re-tier."""

    def test_free_tier_primary_ids_resolve_to_basic_names(self):
        mapping = AvailableModel.build_model_id_name_mapping(
            capacity=1, capacity_field=12
        )
        self.assertEqual(mapping[_id_for(Model.BASIC_PRO)], "gemini-3-pro")
        self.assertEqual(mapping[_id_for(Model.BASIC_FLASH)], "gemini-3-flash")
        self.assertEqual(
            mapping[_id_for(Model.BASIC_THINKING)], "gemini-3-flash-thinking"
        )

    def test_plus_tier_primary_ids_resolve_to_plus_names(self):
        mapping = AvailableModel.build_model_id_name_mapping(
            capacity=4, capacity_field=12
        )
        self.assertEqual(mapping[_id_for(Model.PLUS_PRO)], "gemini-3-pro-plus")
        self.assertEqual(mapping[_id_for(Model.PLUS_FLASH)], "gemini-3-flash-plus")
        self.assertEqual(
            mapping[_id_for(Model.PLUS_THINKING)], "gemini-3-flash-thinking-plus"
        )

    def test_advanced_tier_primary_ids_resolve_to_advanced_names(self):
        # Capacity 2 (field 12 or 13) is the "Advanced" capability — its
        # model_ids happen to be shared with the Plus tier but the account's
        # header uses capacity=2, so names must reflect that.
        for field in (12, 13):
            with self.subTest(capacity_field=field):
                mapping = AvailableModel.build_model_id_name_mapping(
                    capacity=2, capacity_field=field
                )
                self.assertEqual(
                    mapping[_id_for(Model.ADVANCED_PRO)], "gemini-3-pro-advanced"
                )
                self.assertEqual(
                    mapping[_id_for(Model.ADVANCED_FLASH)], "gemini-3-flash-advanced"
                )
                self.assertEqual(
                    mapping[_id_for(Model.ADVANCED_THINKING)],
                    "gemini-3-flash-thinking-advanced",
                )

    def test_basic_only_ids_still_resolve_on_higher_tiers(self):
        # BASIC_* have unique model_ids — if Google surfaces them to a Plus
        # account (defensive case), the mapping must still cover them.
        for capacity in (2, 4):
            with self.subTest(capacity=capacity):
                mapping = AvailableModel.build_model_id_name_mapping(
                    capacity=capacity, capacity_field=12
                )
                self.assertIn(_id_for(Model.BASIC_PRO), mapping)
                self.assertIn(_id_for(Model.BASIC_FLASH), mapping)
                self.assertIn(_id_for(Model.BASIC_THINKING), mapping)

    def test_default_args_preserve_legacy_basic_mapping(self):
        default = AvailableModel.build_model_id_name_mapping()
        explicit = AvailableModel.build_model_id_name_mapping(
            capacity=1, capacity_field=12
        )
        self.assertEqual(default, explicit)


if __name__ == "__main__":
    unittest.main()
