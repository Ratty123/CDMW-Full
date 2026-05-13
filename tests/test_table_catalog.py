from __future__ import annotations

import unittest

from cdmw.core.table_catalog import (
    TABLE_CATALOG_SIGNATURE,
    TABLE_CATALOG_VERSION,
    build_item_table_evidence,
    build_table_compatibility_warning,
    compatibility_tags_for_catalog_row,
    extract_table_asset_reference_evidence,
    get_table_spec,
    infer_table_texture_role,
    recognized_table_for_path,
    serialize_table_evidence,
    summarize_table_evidence,
    table_catalog_cache_metadata,
    table_catalog_cache_metadata_matches,
)


class TableCatalogTests(unittest.TestCase):
    def test_curated_catalog_has_high_value_schema_fields(self) -> None:
        item_info = get_table_spec("ItemInfo")
        self.assertIsNotNone(item_info)
        fields = {field.source_field for field in item_info.fields} if item_info else set()

        self.assertIn("_itemName", fields)
        self.assertIn("_defaultTexturePath", fields)
        self.assertIn("_prefabDataList", fields)
        self.assertFalse(item_info.runtime_usable if item_info else True)

    def test_cache_metadata_uses_catalog_signature(self) -> None:
        metadata = table_catalog_cache_metadata(row_counts={"ItemInfo": 3})

        self.assertEqual(metadata["version"], TABLE_CATALOG_VERSION)
        self.assertEqual(metadata["signature"], TABLE_CATALOG_SIGNATURE)
        self.assertTrue(table_catalog_cache_metadata_matches(metadata))

        stale = dict(metadata)
        stale["signature"] = "old"
        self.assertFalse(table_catalog_cache_metadata_matches(stale))

    def test_item_evidence_serializes_labels(self) -> None:
        evidence = build_item_table_evidence(
            item_id=1234,
            internal_name="Item_OneHandSword_0166",
            display_name="Sword of the Lord",
            prefab_hashes=(42,),
            model_stems=("cd_phm_01_sword_0166",),
            icon_paths=("ui/itemicon/itemicon_prefab_cd_phm_01_sword_0166.dds",),
        )

        summary = summarize_table_evidence(evidence)
        serialized = serialize_table_evidence(evidence)

        self.assertIn("ItemInfo._itemName", summary)
        self.assertIn("ItemInfo._prefabDataList", summary)
        self.assertTrue(any(row.get("label") == "ItemInfo._itemIconList" for row in serialized))

    def test_table_asset_reference_extraction_infers_fields_and_texture_roles(self) -> None:
        evidence = extract_table_asset_reference_evidence(
            "PartPrefabDyeTextureSet",
            ("character/texture/cd_phm_00_ub_0001_o.dds",),
        )

        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0].source_field, "_baseColorTexturePath")
        self.assertEqual(evidence[0].texture_role, "base_color")
        self.assertEqual(infer_table_texture_role("_defaultTexturePath"), "visible_default")

    def test_path_recognition_and_compatibility_warning_are_conservative(self) -> None:
        self.assertEqual(
            recognized_table_for_path("gamedata/binary__/client/bin/uimaptextureinfo.pabgb").source_table,
            "UIMapTextureInfo",
        )

        weapon_tags = compatibility_tags_for_catalog_row("Weapon", "Sword")
        armor_tags = compatibility_tags_for_catalog_row("Armor", "Head")

        self.assertIn("equip_family:weapon", weapon_tags)
        self.assertIn("equip_slot:head", armor_tags)
        self.assertIn("families differ", build_table_compatibility_warning(armor_tags, weapon_tags))


if __name__ == "__main__":
    unittest.main()
