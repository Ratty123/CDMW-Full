from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cdmw.core import archive as archive_core
from cdmw.models import ArchiveEntry


def _entry(path: str, *, package: str = "0009", offset: int = 0, size: int = 100) -> ArchiveEntry:
    return ArchiveEntry(
        path=path,
        pamt_path=Path(f"C:/game/{package}/0.pamt"),
        paz_file=Path(f"C:/game/{package}/0.paz"),
        offset=offset,
        comp_size=size,
        orig_size=size,
        flags=0,
        paz_index=0,
    )


def _filter(
    entries: list[ArchiveEntry],
    text: str,
    *,
    index: archive_core.ArchiveNameSearchIndex | None = None,
    extension: str = "*",
    aliases: dict[str, str] | None = None,
) -> list[str]:
    return [
        entry.path
        for entry in archive_core.filter_archive_entries(
            entries,
            filter_text=text,
            exclude_filter_text="",
            extension_filter=extension,
            package_filter_text="",
            structure_filter="",
            role_filter="all",
            exclude_common_technical_suffixes=False,
            min_size_kb=0,
            previewable_only=False,
            item_search_aliases=aliases,
            archive_name_search_index=index,
        )
    ]


class ArchiveNameSearchIndexTests(unittest.TestCase):
    def test_indexed_filter_matches_full_scan_for_simple_terms(self) -> None:
        entries = [
            _entry("object/tools/cd_t0000_lantern_ring_0001.prefab", offset=1),
            _entry("character/model/weapon/cd_phw_01_sword_0027.pac", offset=2),
            _entry("character/model/armor/cd_phw_00_armor_0007.pac", offset=3),
            _entry("object/interior/cd_in_dff_chair_10.prefab", offset=4),
        ]
        index = archive_core.build_archive_name_search_index(entries)

        for query in ("lantern", "sword", "armor"):
            self.assertEqual(_filter(entries, query), _filter(entries, query, index=index))

    def test_common_spelling_and_compound_aliases_match_with_and_without_index(self) -> None:
        entries = [
            _entry("character/model/armor/cd_phw_00_armor_0007.pac", offset=1),
            _entry("character/model/tools/cd_t0000_pickaxe_0001.pac", offset=2),
            _entry("character/model/weapon/cd_r0020_00_fixedcrossbow.pac", offset=3),
            _entry("object/interior/cd_lamp_stand_candlestick_01.prefab", offset=4),
            _entry("character/model/weapon/cd_phm_04_bow_0007.pac", offset=5),
        ]
        index = archive_core.build_archive_name_search_index(entries)

        expectations = {
            "armour": ["character/model/armor/cd_phw_00_armor_0007.pac"],
            "axe": ["character/model/tools/cd_t0000_pickaxe_0001.pac"],
            "bow": [
                "character/model/weapon/cd_phm_04_bow_0007.pac",
                "character/model/weapon/cd_r0020_00_fixedcrossbow.pac",
            ],
            "crossbow": ["character/model/weapon/cd_r0020_00_fixedcrossbow.pac"],
            "candle": ["object/interior/cd_lamp_stand_candlestick_01.prefab"],
        }
        for query, expected in expectations.items():
            self.assertEqual(_filter(entries, query), expected)
            self.assertEqual(_filter(entries, query, index=index), expected)

    def test_indexed_filter_matches_full_scan_for_query_operators(self) -> None:
        entries = [
            _entry("object/props/iron_sword_wall.prefab", offset=1),
            _entry("object/props/lantern_hanging.prefab", offset=2),
            _entry("object/props/lantern_broken.prefab", offset=3),
            _entry("object/props/sword_lantern.prefab", offset=4),
            _entry("object/props/wooden_chair.prefab", offset=5),
        ]
        index = archive_core.build_archive_name_search_index(entries)

        for query in ('"iron sword"', "sword OR lantern", "sword lantern", "lantern -broken"):
            self.assertEqual(_filter(entries, query), _filter(entries, query, index=index))

    def test_indexed_filter_preserves_extension_filtering(self) -> None:
        entries = [
            _entry("character/model/weapon/cd_phw_01_sword_0027.pac", offset=1),
            _entry("character/havokphysics/weapon/cd_phw_01_sword_0027.hkx", offset=2),
            _entry("character/model/weapon/cd_phw_01_axe_0001.pac", offset=3),
        ]
        index = archive_core.build_archive_name_search_index(entries)

        self.assertEqual(
            _filter(entries, "sword", index=index, extension=".pac"),
            ["character/model/weapon/cd_phw_01_sword_0027.pac"],
        )

    def test_indexed_filter_preserves_item_name_alias_search(self) -> None:
        entries = [
            _entry("character/model/cd_weapon_king_halberd.pac", offset=1),
            _entry("character/model/cd_unrelated_sword.pac", offset=2),
        ]
        aliases = {
            "cd_weapon_king_halberd": "vow of the dead king item_halberd_001 cd_weapon_king_halberd.pac",
        }
        index = archive_core.build_archive_name_search_index(entries, item_search_aliases=aliases)

        self.assertEqual(_filter(entries, "Vow of the Dead King", aliases=aliases), _filter(entries, "Vow of the Dead King", index=index, aliases=aliases))
        self.assertEqual(_filter(entries, "Vow of the Dead King", index=index, aliases=aliases), ["character/model/cd_weapon_king_halberd.pac"])

    def test_index_reduces_candidate_scan_for_name_queries(self) -> None:
        entries = [_entry(f"object/filler/filler_{index:04d}.pami", offset=index) for index in range(500)]
        entries.append(_entry("object/tools/cd_t0000_pickaxe_0001.pac", offset=999))
        index = archive_core.build_archive_name_search_index(entries)
        call_count = 0
        original = archive_core._archive_search_query_matches_entry

        def counted_match(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return original(*args, **kwargs)

        with mock.patch("cdmw.core.archive._archive_search_query_matches_entry", side_effect=counted_match):
            result = _filter(entries, "axe", index=index)

        self.assertEqual(result, ["object/tools/cd_t0000_pickaxe_0001.pac"])
        self.assertLess(call_count, len(entries) // 10)

    def test_derived_cache_persists_name_search_index(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache_root = root / "cache"
            pamt_path = root / "0009" / "0.pamt"
            paz_path = root / "0009" / "0.paz"
            pamt_path.parent.mkdir(parents=True)
            pamt_path.write_bytes(b"pamt")
            paz_path.write_bytes(b"payload")
            entries = [
                ArchiveEntry(
                    path="object/tools/cd_t0000_lantern_ring_0001.prefab",
                    pamt_path=pamt_path,
                    paz_file=paz_path,
                    offset=0,
                    comp_size=7,
                    orig_size=7,
                    flags=0,
                    paz_index=0,
                )
            ]
            name_index = archive_core.build_archive_name_search_index(entries)
            archive_core.save_archive_derived_index_cache(
                root,
                cache_root,
                entries,
                item_search_aliases={},
                item_display_names={},
                item_exact_display_names={},
                item_related_display_names={},
                item_asset_catalog=[],
                path_index=archive_core.build_archive_entry_path_index(entries),
                basename_index=archive_core.build_archive_entry_basename_index(entries),
                extension_index=archive_core.build_archive_entry_extension_index(entries),
                archive_name_search_index=name_index,
            )

            payload = archive_core._deserialize_archive_derived_index_cache_payload_from_path(
                archive_core.resolve_archive_derived_index_cache_path(root, cache_root)
            )
            loaded = archive_core.load_archive_derived_index_cache(root, cache_root, entries)

        self.assertIn("name_search_index", payload)
        self.assertNotIn("token_rows", payload)
        self.assertIsInstance(loaded, dict)
        self.assertIsInstance(loaded.get("name_search_index"), archive_core.ArchiveNameSearchIndex)

    def test_native_name_search_path_is_guarded_for_large_indexes(self) -> None:
        source_text = Path("cdmw/core/archive.py").read_text(encoding="utf-8")
        native_text = Path("native/cdmw_preview_core/src/main.cpp").read_text(encoding="utf-8")

        self.assertIn("_try_build_archive_name_search_index_native", source_text)
        self.assertIn("CDMW_DISABLE_NATIVE_NAME_SEARCH", source_text)
        self.assertIn("CDMW_NATIVE_NAME_SEARCH_MIN_ENTRIES", source_text)
        self.assertIn("resolve_archive_name_search_index_cache_path", source_text)
        self.assertIn("_write_native_name_search_index_binary", source_text)
        self.assertIn("name-index-job", native_text)
        self.assertIn("'C', 'D', 'N', 'I', 'D', 'X', '1'", native_text)


if __name__ == "__main__":
    unittest.main()
