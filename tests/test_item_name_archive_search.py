from __future__ import annotations

import tempfile
import struct
import unittest
from pathlib import Path
from unittest import mock

from cdmw.core.archive import (
    active_archive_entry_for_virtual_path,
    archive_entry_item_name_match,
    archive_entry_is_mod_package,
    crypt_chacha20_filename,
    filter_archive_entries,
    hashlittle,
    order_archive_entries_by_active_overrides,
    try_decrypt_archive_entry_data,
)
from cdmw.core.item_index import (
    ArchiveItemRecord,
    _ITEMINFO_MARKER,
    _build_archive_item_icon_path_index,
    _build_archive_item_search_index_from_records,
    _build_archive_model_hash_table_from_entries,
    _collect_archive_item_index_sources,
    _parse_archive_iteminfo_data,
    _parse_part_prefab_dye_slot_material_index_data,
    _parse_stringinfo_model_icon_hashes_from_data,
    _strip_archive_model_variant_suffix,
)
from cdmw.core.table_catalog import summarize_table_evidence
from cdmw.models import ArchiveEntry


REPO_ROOT = Path(__file__).resolve().parents[1]


def _entry(path: str) -> ArchiveEntry:
    return ArchiveEntry(
        path=path,
        pamt_path=Path("C:/game/0009/0.pamt"),
        paz_file=Path("C:/game/0009/0.paz"),
        offset=0,
        comp_size=100,
        orig_size=100,
        flags=0,
        paz_index=0,
    )


def _package_entry(path: str, package: str, *, offset: int = 0) -> ArchiveEntry:
    return ArchiveEntry(
        path=path,
        pamt_path=Path(f"C:/game/{package}/0.pamt"),
        paz_file=Path(f"C:/game/{package}/0.paz"),
        offset=offset,
        comp_size=100,
        orig_size=100,
        flags=0,
        paz_index=0,
    )


def _encrypted_entry(path: str) -> ArchiveEntry:
    entry = _entry(path)
    entry.flags = 3 << 4
    return entry


def _entries_with_payloads(payloads):
    tempdir = tempfile.TemporaryDirectory()
    root = Path(tempdir.name)
    paz_path = root / "0.paz"
    pamt_path = root / "0.pamt"
    entries = []
    offset = 0
    with paz_path.open("wb") as handle:
        for path, payload in payloads:
            data = payload if isinstance(payload, bytes) else str(payload).encode("utf-8")
            handle.write(data)
            entries.append(
                ArchiveEntry(
                    path=path,
                    pamt_path=pamt_path,
                    paz_file=paz_path,
                    offset=offset,
                    comp_size=len(data),
                    orig_size=len(data),
                    flags=0,
                    paz_index=0,
                )
            )
            offset += len(data)
    return tempdir, tuple(entries)


class ItemNameArchiveSearchTests(unittest.TestCase):
    def test_native_item_index_job_is_wired_with_python_fallback(self) -> None:
        item_index_source = (REPO_ROOT / "cdmw" / "core" / "item_index.py").read_text(encoding="utf-8")
        native_source = (REPO_ROOT / "native" / "cdmw_archive_accelerator" / "src" / "main.cpp").read_text(encoding="utf-8")

        self.assertIn("def _try_build_archive_item_search_index_native", item_index_source)
        self.assertIn('"item-index-job"', item_index_source)
        self.assertIn("CDMW_DISABLE_NATIVE_ITEM_INDEX", item_index_source)
        self.assertIn("return None", item_index_source)
        self.assertIn("run_item_index_job", native_source)
        self.assertIn("parse_iteminfo_bin", native_source)
        self.assertIn("parse_localization_bin", native_source)
        self.assertIn("build_model_hash_table", native_source)

    def test_dmm_duplicate_archive_entry_is_grouped_and_marked_active(self) -> None:
        virtual_path = "character/model/1_pc/1_phm/weapon/1_onehandweapon/cd_phm_01_sword_0278.pac"
        original = _package_entry(virtual_path, "0009", offset=10)
        modded = _package_entry(virtual_path, "dmmsa", offset=20)
        unrelated = _package_entry(
            "character/model/1_pc/1_phm/weapon/2_twohandweapon/cd_phm_02_sword_0009.pac",
            "0009",
            offset=30,
        )

        self.assertTrue(archive_entry_is_mod_package(modded))
        self.assertIs(active_archive_entry_for_virtual_path([original, modded]), modded)
        self.assertEqual(
            [entry.package_label for entry in order_archive_entries_by_active_overrides([original, unrelated, modded])],
            ["dmmsa/0.pamt", "0009/0.pamt", "0009/0.pamt"],
        )

        filtered = filter_archive_entries(
            [original, unrelated, modded],
            filter_text="cd_phm_01_sword_0278",
            exclude_filter_text="",
            extension_filter="*",
            package_filter_text="",
            structure_filter="",
            role_filter="all",
            exclude_common_technical_suffixes=False,
            min_size_kb=0,
            previewable_only=False,
        )
        self.assertEqual([entry.package_label for entry in filtered], ["dmmsa/0.pamt", "0009/0.pamt"])

    def test_paloc_binary_payload_passes_chacha20_validation(self) -> None:
        payload = (
            (b"123456", "Vow of the Dead King".encode("utf-8")),
            (b"123457", "Todtenkonigs Schwur".encode("utf-8")),
        )
        data = bytearray()
        for loc_id, text in payload:
            data.extend(len(loc_id).to_bytes(4, "little"))
            data.extend(loc_id)
            data.extend(len(text).to_bytes(4, "little"))
            data.extend(text)

        entry = _encrypted_entry("gamedata/stringtable/binary__/localizationstring_eng.paloc")
        encrypted = crypt_chacha20_filename(bytes(data), entry.basename)

        decrypted, note = try_decrypt_archive_entry_data(entry, encrypted)

        self.assertEqual(decrypted, bytes(data))
        self.assertEqual(note, "ChaCha20")

    def test_archive_filter_matches_item_display_name_alias(self) -> None:
        entries = [
            _entry("character/model/cd_weapon_king_halberd.pac"),
            _entry("character/model/cd_unrelated_sword.pac"),
        ]

        filtered = filter_archive_entries(
            entries,
            filter_text="Vow of the Dead King",
            exclude_filter_text="",
            extension_filter="*",
            package_filter_text="",
            structure_filter="",
            role_filter="all",
            exclude_common_technical_suffixes=False,
            min_size_kb=0,
            previewable_only=False,
            item_search_aliases={
                "cd_weapon_king_halberd": "vow of the dead king item_halberd_001 cd_weapon_king_halberd.pac",
            },
        )

        self.assertEqual([entry.path for entry in filtered], ["character/model/cd_weapon_king_halberd.pac"])

    def test_archive_filter_matches_alias_after_variant_suffix_strip(self) -> None:
        entries = [_entry("character/model/cd_weapon_king_halberd_l.pami")]

        filtered = filter_archive_entries(
            entries,
            filter_text="dead king",
            exclude_filter_text="",
            extension_filter="*",
            package_filter_text="",
            structure_filter="",
            role_filter="all",
            exclude_common_technical_suffixes=False,
            min_size_kb=0,
            previewable_only=False,
            item_search_aliases={
                "cd_weapon_king_halberd": "vow of the dead king item_halberd_001 cd_weapon_king_halberd.pac",
            },
        )

        self.assertEqual([entry.path for entry in filtered], ["character/model/cd_weapon_king_halberd_l.pami"])

    def test_archive_filter_matches_alias_after_d_variant_suffix_strip(self) -> None:
        entries = [
            _entry("character/model/cd_m0001_00_crowman_hel_0001_d.prefab"),
            _entry("character/model/cd_unrelated_hel_0001_d.prefab"),
        ]

        filtered = filter_archive_entries(
            entries,
            filter_text="Blackwing Mask",
            exclude_filter_text="",
            extension_filter="*",
            package_filter_text="",
            structure_filter="",
            role_filter="all",
            exclude_common_technical_suffixes=False,
            min_size_kb=0,
            previewable_only=False,
            item_search_aliases={
                "cd_m0001_00_crowman_hel_0001": (
                    "blackwing mask item_hel_blackwing cd_m0001_00_crowman_hel_0001.pac"
                ),
            },
        )

        self.assertEqual(
            [entry.path for entry in filtered],
            ["character/model/cd_m0001_00_crowman_hel_0001_d.prefab"],
        )

    def test_archive_filter_matches_item_alias_for_texture_family_suffixes(self) -> None:
        entries = [
            _entry("character/texture/cd_m0001_00_crowman_hel_0001_o.dds"),
            _entry("character/texture/cd_m0001_00_crowman_hel_0001_ma.dds"),
            _entry("character/texture/cd_unrelated_hel_0001_o.dds"),
        ]

        filtered = filter_archive_entries(
            entries,
            filter_text="Blackwing Mask",
            exclude_filter_text="",
            extension_filter="*",
            package_filter_text="",
            structure_filter="",
            role_filter="all",
            exclude_common_technical_suffixes=False,
            min_size_kb=0,
            previewable_only=False,
            item_search_aliases={
                "cd_m0001_00_crowman_hel_0001": (
                    "blackwing mask item_hel_blackwing cd_m0001_00_crowman_hel_0001.pac"
                ),
            },
        )

        self.assertEqual(
            [entry.path for entry in filtered],
            [
                "character/texture/cd_m0001_00_crowman_hel_0001_o.dds",
                "character/texture/cd_m0001_00_crowman_hel_0001_ma.dds",
            ],
        )

    def test_archive_filter_expands_item_alias_model_match_to_same_stem_companions(self) -> None:
        entries = [
            _entry("character/model/cd_m0001_00_carta_hel_0001.pac"),
            _entry("character/modelproperty/cd_m0001_00_carta_hel_0001.pac_xml"),
            _entry("character/model/cd_unrelated_hel_0001.pac_xml"),
        ]

        filtered = filter_archive_entries(
            entries,
            filter_text="Carta Plate Helm",
            exclude_filter_text="",
            extension_filter="*",
            package_filter_text="",
            structure_filter="",
            role_filter="all",
            exclude_common_technical_suffixes=False,
            min_size_kb=0,
            previewable_only=False,
            item_search_aliases={
                "cd_m0001_00_carta_hel_0001": (
                    "carta plate helm item_hel_carta cd_m0001_00_carta_hel_0001.pac"
                ),
            },
        )

        self.assertEqual(
            [entry.path for entry in filtered],
            [
                "character/model/cd_m0001_00_carta_hel_0001.pac",
                "character/modelproperty/cd_m0001_00_carta_hel_0001.pac_xml",
            ],
        )

    def test_archive_filter_keeps_extension_filter_for_item_alias_related_entries(self) -> None:
        entries = [
            _entry("character/model/cd_m0001_00_skullknight_ub_0003.pac"),
            _entry("character/modelproperty/cd_m0001_00_skullknight_ub_0003.pac_xml"),
            _entry("character/texture/cd_m0001_00_skullknight_vest_0003_n.dds"),
        ]

        with mock.patch(
            "cdmw.core.archive_references.build_archive_relationship_references",
            side_effect=AssertionError("PAC-only item search should not expand relationships"),
        ):
            filtered = filter_archive_entries(
                entries,
                filter_text="Righteous Virtue",
                exclude_filter_text="",
                extension_filter=".pac",
                package_filter_text="",
                structure_filter="",
                role_filter="all",
                exclude_common_technical_suffixes=False,
                min_size_kb=0,
                previewable_only=False,
                item_search_aliases={
                    "cd_m0001_00_skullknight_ub_0003": (
                        "righteous virtue frost curse cd_m0001_00_skullknight_ub_0003.pac"
                    ),
                },
            )

        self.assertEqual(
            [entry.path for entry in filtered],
            ["character/model/cd_m0001_00_skullknight_ub_0003.pac"],
        )

    def test_archive_filter_matches_character_equipment_root_item_alias(self) -> None:
        entries = [
            _entry("character/model/cd_m0001_00_skullknight_ub_0003.pac"),
            _entry("character/modelproperty/cd_m0001_00_skullknight_ub_0003.pac_xml"),
            _entry("character/model/cd_m0001_00_other_ub_0003.pac"),
        ]

        filtered = filter_archive_entries(
            entries,
            filter_text="Righteous Virtue",
            exclude_filter_text="",
            extension_filter=".pac",
            package_filter_text="",
            structure_filter="",
            role_filter="all",
            exclude_common_technical_suffixes=False,
            min_size_kb=0,
            previewable_only=False,
            item_search_aliases={
                "cd_m0001_00_skullknight": "righteous virtue frost curse cd_m0001_00_skullknight",
            },
        )

        self.assertEqual(
            [entry.path for entry in filtered],
            ["character/model/cd_m0001_00_skullknight_ub_0003.pac"],
        )

    def test_archive_filter_orders_exact_model_alias_before_related_sidecar(self) -> None:
        entries = [
            _entry("character/modelproperty/cd_m0001_00_skullknight_ub_0003.pac_xml"),
            _entry("character/model/cd_m0001_00_skullknight_ub_0003.pac"),
        ]

        filtered = filter_archive_entries(
            entries,
            filter_text="Righteous Virtue",
            exclude_filter_text="",
            extension_filter="*",
            package_filter_text="",
            structure_filter="",
            role_filter="all",
            exclude_common_technical_suffixes=False,
            min_size_kb=0,
            previewable_only=False,
            item_search_aliases={
                "cd_m0001_00_skullknight_ub_0003": (
                    "righteous virtue frost curse cd_m0001_00_skullknight_ub_0003.pac"
                ),
            },
        )

        self.assertEqual(
            [entry.path for entry in filtered],
            [
                "character/model/cd_m0001_00_skullknight_ub_0003.pac",
                "character/modelproperty/cd_m0001_00_skullknight_ub_0003.pac_xml",
            ],
        )

    def test_archive_filter_excluded_alias_source_does_not_expand_related_files(self) -> None:
        entries = [
            _entry("character/model/cd_m0001_00_skullknight_ub_0003.pac"),
            _entry("character/modelproperty/cd_m0001_00_skullknight_ub_0003.pac.xml"),
        ]

        filtered = filter_archive_entries(
            entries,
            filter_text="Righteous Virtue",
            exclude_filter_text="character/model/cd_m0001_00_skullknight_ub_0003.pac",
            extension_filter="*",
            package_filter_text="",
            structure_filter="",
            role_filter="all",
            exclude_common_technical_suffixes=False,
            min_size_kb=0,
            previewable_only=False,
            item_search_aliases={
                "cd_m0001_00_skullknight_ub_0003": (
                    "righteous virtue frost curse cd_m0001_00_skullknight_ub_0003.pac"
                ),
            },
        )

        self.assertEqual([entry.path for entry in filtered], [])

    def test_archive_filter_dds_extension_uses_hidden_item_alias_graph_source(self) -> None:
        tempdir, entries = _entries_with_payloads(
            (
                ("character/model/cd_m0001_00_skullknight_ub_0003.pac", b"PAR "),
                (
                    "character/modelproperty/cd_m0001_00_skullknight_ub_0003.pac_xml",
                    '<MaterialParameterTexture _name="_baseColorTexture">'
                    '<ResourceReferencePath_ITexture value="character/texture/skull_base.dds"/>'
                    "</MaterialParameterTexture>",
                ),
                ("character/texture/skull_base.dds", b"DDS "),
            )
        )
        self.addCleanup(tempdir.cleanup)

        filtered = filter_archive_entries(
            entries,
            filter_text="Righteous Virtue",
            exclude_filter_text="",
            extension_filter=".dds",
            package_filter_text="",
            structure_filter="",
            role_filter="all",
            exclude_common_technical_suffixes=False,
            min_size_kb=0,
            previewable_only=False,
            item_search_aliases={
                "cd_m0001_00_skullknight_ub_0003": (
                    "righteous virtue frost curse cd_m0001_00_skullknight_ub_0003.pac"
                ),
            },
        )

        self.assertEqual([entry.path for entry in filtered], ["character/texture/skull_base.dds"])

    def test_archive_filter_orders_exact_model_alias_before_sidecar_for_multi_pattern_search(self) -> None:
        entries = [
            _entry("character/modelproperty/cd_m0001_00_skullknight_ub_0003.pac_xml"),
            _entry("character/model/cd_m0001_00_skullknight_ub_0003.pac"),
        ]

        filtered = filter_archive_entries(
            entries,
            filter_text="not-present;Righteous Virtue",
            exclude_filter_text="",
            extension_filter="*",
            package_filter_text="",
            structure_filter="",
            role_filter="all",
            exclude_common_technical_suffixes=False,
            min_size_kb=0,
            previewable_only=False,
            item_search_aliases={
                "cd_m0001_00_skullknight_ub_0003": (
                    "righteous virtue frost curse cd_m0001_00_skullknight_ub_0003.pac"
                ),
            },
        )

        self.assertEqual(
            [entry.path for entry in filtered],
            [
                "character/model/cd_m0001_00_skullknight_ub_0003.pac",
                "character/modelproperty/cd_m0001_00_skullknight_ub_0003.pac_xml",
            ],
        )

    def test_archive_filter_expands_item_alias_prefab_helm_descriptor_to_model_family(self) -> None:
        entries = [
            _entry("character/bin/_prefab/1_pc/01/cd_phm_00_hel_0013_05_c.prefab"),
            _entry("character/model/1_pc/14_ptm/armor/13_hel/cd_ptm_01_hel_0013_05.pac"),
            _entry("character/modelproperty/1_pc/14_ptm/armor/13_hel/cd_ptm_01_hel_0013_05.pac_xml"),
            _entry("character/texture/cd_ptm_01_hel_0013_05_n.dds"),
            _entry("character/texture/cd_phm_00_hel_0013_05_mg.dds"),
            _entry("character/model/1_pc/14_ptm/armor/13_hel/cd_ptm_01_hel_0099.pac"),
        ]

        filtered = filter_archive_entries(
            entries,
            filter_text="Canta Plate Helm",
            exclude_filter_text="",
            extension_filter="*",
            package_filter_text="",
            structure_filter="",
            role_filter="all",
            exclude_common_technical_suffixes=False,
            min_size_kb=0,
            previewable_only=False,
            item_search_aliases={
                "cd_phm_00_hel_0013_05": "canta plate helm item_hel_canta",
            },
        )

        self.assertEqual(
            filtered[0].path,
            "character/bin/_prefab/1_pc/01/cd_phm_00_hel_0013_05_c.prefab",
        )
        self.assertCountEqual(
            [entry.path for entry in filtered[1:]],
            [
                "character/model/1_pc/14_ptm/armor/13_hel/cd_ptm_01_hel_0013_05.pac",
                "character/modelproperty/1_pc/14_ptm/armor/13_hel/cd_ptm_01_hel_0013_05.pac_xml",
                "character/texture/cd_phm_00_hel_0013_05_mg.dds",
                "character/texture/cd_ptm_01_hel_0013_05_n.dds",
            ],
        )

    def test_archive_filter_expands_item_alias_prefab_set_helm_to_model_family(self) -> None:
        entries = [
            _entry("character/bin/_prefab/1_pc/01/cd_phm_00_hel_set_0106_c.prefab"),
            _entry("character/model/1_pc/14_ptm/armor/13_hel/cd_ptm_01_hel_0106.pac"),
            _entry("character/modelproperty/1_pc/14_ptm/armor/13_hel/cd_ptm_01_hel_0106.pac_xml"),
            _entry("character/texture/cd_ptm_01_hel_0106_o.dds"),
            _entry("character/model/1_pc/14_ptm/armor/13_hel/cd_ptm_01_hel_0107.pac"),
        ]

        filtered = filter_archive_entries(
            entries,
            filter_text="Carta Plate Helm",
            exclude_filter_text="",
            extension_filter="*",
            package_filter_text="",
            structure_filter="",
            role_filter="all",
            exclude_common_technical_suffixes=False,
            min_size_kb=0,
            previewable_only=False,
            item_search_aliases={
                "cd_phm_00_hel_set_0106": "carta plate helm item_hel_carta",
            },
        )

        self.assertEqual(
            [entry.path for entry in filtered],
            [
                "character/bin/_prefab/1_pc/01/cd_phm_00_hel_set_0106_c.prefab",
                "character/model/1_pc/14_ptm/armor/13_hel/cd_ptm_01_hel_0106.pac",
                "character/modelproperty/1_pc/14_ptm/armor/13_hel/cd_ptm_01_hel_0106.pac_xml",
                "character/texture/cd_ptm_01_hel_0106_o.dds",
            ],
        )

    def test_archive_filter_matches_plate_helm_model_through_prefab_descriptor_alias(self) -> None:
        entries = [
            _entry("character/model/1_pc/14_ptm/armor/13_hel/cd_ptm_01_hel_0013_05.pac"),
            _entry("character/model/1_pc/14_ptm/armor/13_hel/cd_ptm_01_hel_0106.pac"),
            _entry("character/model/1_pc/14_ptm/armor/13_hel/cd_ptm_01_hel_0099.pac"),
        ]

        canta_filtered = filter_archive_entries(
            entries,
            filter_text="Canta Plate Helm",
            exclude_filter_text="",
            extension_filter="*",
            package_filter_text="",
            structure_filter="",
            role_filter="all",
            exclude_common_technical_suffixes=False,
            min_size_kb=0,
            previewable_only=False,
            item_search_aliases={
                "cd_phm_00_hel_0013_05_c": "canta plate helm item_hel_canta",
                "cd_phm_00_hel_set_0106_c": "carta plate helm item_hel_carta",
            },
        )
        carta_filtered = filter_archive_entries(
            entries,
            filter_text="Carta Plate Helm",
            exclude_filter_text="",
            extension_filter="*",
            package_filter_text="",
            structure_filter="",
            role_filter="all",
            exclude_common_technical_suffixes=False,
            min_size_kb=0,
            previewable_only=False,
            item_search_aliases={
                "cd_phm_00_hel_0013_05_c": "canta plate helm item_hel_canta",
                "cd_phm_00_hel_set_0106_c": "carta plate helm item_hel_carta",
            },
        )

        self.assertEqual(
            [entry.path for entry in canta_filtered],
            ["character/model/1_pc/14_ptm/armor/13_hel/cd_ptm_01_hel_0013_05.pac"],
        )
        self.assertEqual(
            [entry.path for entry in carta_filtered],
            ["character/model/1_pc/14_ptm/armor/13_hel/cd_ptm_01_hel_0106.pac"],
        )

    def test_model_hash_table_indexes_stripped_variant_base(self) -> None:
        table = _build_archive_model_hash_table_from_entries(
            [
                _entry("character/model/cd_m0001_00_crowman_hel_0000_c.prefab"),
                _entry("character/model/cd_m0001_00_crowman_hel_0001_d.prefab"),
                _entry("character/model/cd_m0001_00_crowman_hel_0002d.prefab"),
            ]
        )

        self.assertEqual(
            table.get(hashlittle(b"cd_m0001_00_crowman_hel_0000", 0xC5EDE)),
            "cd_m0001_00_crowman_hel_0000",
        )
        self.assertEqual(
            table.get(hashlittle(b"cd_m0001_00_crowman_hel_0001", 0xC5EDE)),
            "cd_m0001_00_crowman_hel_0001",
        )
        self.assertEqual(
            table.get(hashlittle(b"cd_m0001_00_crowman_hel_0001_d", 0xC5EDE)),
            "cd_m0001_00_crowman_hel_0001_d",
        )
        self.assertEqual(
            table.get(hashlittle(b"cd_m0001_00_crowman_hel_0002", 0xC5EDE)),
            "cd_m0001_00_crowman_hel_0002",
        )

    def test_model_hash_table_indexes_compound_index_variants(self) -> None:
        table = _build_archive_model_hash_table_from_entries(
            [_entry("character/model/cd_phm_01_sword_0166.pac")]
        )

        self.assertEqual(
            table.get(hashlittle(b"cd_phm_01_sword_0166_index01_r", 0xC5EDE)),
            "cd_phm_01_sword_0166_index01_r",
        )
        self.assertEqual(
            _strip_archive_model_variant_suffix("cd_phm_01_sword_0166_index01_r"),
            "cd_phm_01_sword_0166",
        )

    def test_archive_filter_matches_alias_after_subpart_suffix_strip(self) -> None:
        entries = [_entry("character/model/cd_phm_01_sword_0279_sub01.pac")]

        filtered = filter_archive_entries(
            entries,
            filter_text="Tree Branch",
            exclude_filter_text="",
            extension_filter="*",
            package_filter_text="",
            structure_filter="",
            role_filter="all",
            exclude_common_technical_suffixes=False,
            min_size_kb=0,
            previewable_only=False,
            item_search_aliases={
                "cd_phm_01_sword_0279": "tree branch wood_branch_01 cd_phm_01_sword_0279.pac",
            },
        )

        self.assertEqual([entry.path for entry in filtered], ["character/model/cd_phm_01_sword_0279_sub01.pac"])

    def test_archive_filter_matches_item_alias_for_weapon_in_companion_suffix(self) -> None:
        entries = [
            _entry("character/model/1_pc/1_phm/weapon/2_twohandweapon/cd_phm_02_sword_0036.pac"),
            _entry("character/model/1_pc/1_phm/weapon/2_twohandweapon/cd_phm_02_sword_0036_in.pac"),
            _entry("character/model/1_pc/1_phm/weapon/2_twohandweapon/cd_phm_02_sword_0099_in.pac"),
        ]

        filtered = filter_archive_entries(
            entries,
            filter_text="Hwando",
            exclude_filter_text="",
            extension_filter="*",
            package_filter_text="",
            structure_filter="",
            role_filter="all",
            exclude_common_technical_suffixes=False,
            min_size_kb=0,
            previewable_only=False,
            item_search_aliases={
                "cd_phm_02_sword_0036": "hwando hwando_twohandsword cd_phm_02_sword_0036.pac",
            },
        )

        self.assertEqual(
            [entry.basename for entry in filtered],
            ["cd_phm_02_sword_0036.pac", "cd_phm_02_sword_0036_in.pac"],
        )

    def test_item_name_match_uses_weapon_in_companion_as_related_hint(self) -> None:
        exact_name, name_hint, reason = archive_entry_item_name_match(
            _entry("character/model/1_pc/1_phm/weapon/2_twohandweapon/cd_phm_02_sword_0036_in.pac"),
            item_display_names={"cd_phm_02_sword_0036": "Hwando"},
            item_exact_display_names={"cd_phm_02_sword_0036": "Hwando"},
        )

        self.assertEqual(exact_name, "")
        self.assertEqual(name_hint, "Name hint: Hwando")
        self.assertIn("Possible related item name", reason)

    def test_stringinfo_icon_hashes_can_supply_compatible_model_stems(self) -> None:
        icon_name = b"ItemIcon_Prefab_cd_phm_01_sword_0166_index01_r"
        icon_hash = hashlittle(icon_name, 0xC5EDE)
        stringinfo_data = (
            len(icon_name).to_bytes(4, "little")
            + icon_name
            + icon_hash.to_bytes(4, "little")
            + b"\x00\x00\x00\x00"
        )
        icon_hashes = _parse_stringinfo_model_icon_hashes_from_data(stringinfo_data)

        item_id = 1234
        internal_name = b"AbyssReward_Mysterm_OneHandSword"
        loc_id = b"4301512826159216"
        iteminfo_data = (
            item_id.to_bytes(4, "little")
            + (len(internal_name) + 1).to_bytes(4, "little")
            + internal_name
            + _ITEMINFO_MARKER
            + b"\x00" * (18 - len(_ITEMINFO_MARKER))
            + len(loc_id).to_bytes(4, "little")
            + loc_id
            + b"\x00" * 32
            + icon_hash.to_bytes(4, "little")
            + b"\x00" * 32
        )

        records = _parse_archive_iteminfo_data(
            iteminfo_data,
            {"eng": {loc_id.decode("ascii"): "Sword of the Lord"}},
            icon_model_hashes=icon_hashes,
        )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].display_name, "Sword of the Lord")
        self.assertEqual(records[0].model_stems, ["cd_phm_01_sword_0166_index01_r"])
        self.assertIn("ItemInfo._itemName", summarize_table_evidence(records[0].table_evidence))
        self.assertIn("ItemInfo._itemIconList", summarize_table_evidence(records[0].table_evidence))

    def test_iteminfo_prefab_hash_parser_accepts_new_delimiter_byte(self) -> None:
        prefab_hash = hashlittle(b"cd_phm_01_sword_0166", 0xC5EDE)
        internal_name = b"Item_OneHandSword_0166"
        iteminfo_data = (
            (1234).to_bytes(4, "little")
            + (len(internal_name) + 1).to_bytes(4, "little")
            + internal_name
            + _ITEMINFO_MARKER
            + b"\x0f\x00\x00"
            + (1).to_bytes(4, "little")
            + (1).to_bytes(4, "little")
            + prefab_hash.to_bytes(4, "little")
            + b"\x00" * 32
        )

        records = _parse_archive_iteminfo_data(iteminfo_data, {"eng": {}})

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].prefab_hashes, [prefab_hash])
        self.assertIn("ItemInfo._prefabDataList", summarize_table_evidence(records[0].table_evidence))

    def test_iteminfo_prefab_hash_parser_accepts_prefab_list_marker_byte_10(self) -> None:
        prefab_hash = hashlittle(b"cd_phm_02_sword_0036", 0xC5EDE)
        sheath_hash = hashlittle(b"cd_phm_02_sword_0036_in", 0xC5EDE)
        internal_name = b"Hwando_TwoHandSword"
        loc_id = b"4295310893383792"
        iteminfo_data = (
            (1000080).to_bytes(4, "little")
            + (len(internal_name) + 1).to_bytes(4, "little")
            + internal_name
            + _ITEMINFO_MARKER
            + b"\x00" * (18 - len(_ITEMINFO_MARKER))
            + len(loc_id).to_bytes(4, "little")
            + loc_id
            + b"\x00" * 360
            + b"\x10\x03\x01"
            + (1).to_bytes(4, "little")
            + (2).to_bytes(4, "little")
            + prefab_hash.to_bytes(4, "little")
            + sheath_hash.to_bytes(4, "little")
        )

        records = _parse_archive_iteminfo_data(
            iteminfo_data,
            {"eng": {loc_id.decode("ascii"): "Hwando"}},
        )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].prefab_hashes, [prefab_hash, sheath_hash])
        index = _build_archive_item_search_index_from_records(
            records,
            [
                _entry("character/model/1_pc/1_phm/weapon/2_twohandweapon/cd_phm_02_sword_0036.pac"),
                _entry("character/model/1_pc/1_phm/weapon/2_twohandweapon/cd_phm_02_sword_0036_in.pac"),
            ],
        )
        self.assertEqual(index.model_base_exact_display_names["cd_phm_02_sword_0036"], "Hwando")
        self.assertEqual(index.model_base_exact_display_names["cd_phm_02_sword_0036_in"], "Hwando")

    def test_item_records_can_carry_multilingual_names(self) -> None:
        record = ArchiveItemRecord(
            item_id=1000,
            internal_name="Item_Halberd_001",
            display_name="Vow of the Dead King",
            localized_names=(
                "Vow of the Dead King",
                "Todtenkonigs Schwur",
                "誓約",
            ),
        )

        alias = " ".join(
            token
            for token in (
                record.display_name.lower(),
                " ".join(name.lower() for name in record.localized_names),
                record.internal_name.lower(),
                "cd_weapon_king_halberd",
                "cd_weapon_king_halberd.pac",
            )
            if token
        )

        filtered = filter_archive_entries(
            [_entry("character/model/cd_weapon_king_halberd.pac")],
            filter_text="todtenkonigs",
            exclude_filter_text="",
            extension_filter="*",
            package_filter_text="",
            structure_filter="",
            role_filter="all",
            exclude_common_technical_suffixes=False,
            min_size_kb=0,
            previewable_only=False,
            item_search_aliases={"cd_weapon_king_halberd": alias},
        )

        self.assertEqual([entry.path for entry in filtered], ["character/model/cd_weapon_king_halberd.pac"])

    def test_item_index_separates_exact_and_related_display_names(self) -> None:
        exact_hash = hashlittle(b"cd_phm_01_sword_0166", 0xC5EDE)
        exact_record = ArchiveItemRecord(
            item_id=1000,
            internal_name="Item_OneHandSword_Exact",
            display_name="Sword of the Lord",
            prefab_hashes=[exact_hash],
        )
        related_record = ArchiveItemRecord(
            item_id=1001,
            internal_name="Item_OneHandSword_Related",
            display_name="Icon Linked Sword",
            model_stems=["cd_phm_01_sword_0279"],
        )

        index = _build_archive_item_search_index_from_records(
            [exact_record, related_record],
            [
                _entry("character/model/cd_phm_01_sword_0166.pac"),
                _entry("character/model/cd_phm_01_sword_0279.pac"),
            ],
        )

        self.assertEqual(index.model_base_exact_display_names, {"cd_phm_01_sword_0166": "Sword of the Lord"})
        self.assertEqual(index.model_base_related_display_names, {"cd_phm_01_sword_0279": "Icon Linked Sword"})
        self.assertEqual(index.model_base_display_names["cd_phm_01_sword_0166"], "Sword of the Lord")
        self.assertEqual(index.model_base_display_names["cd_phm_01_sword_0279"], "Icon Linked Sword")

    def test_exact_display_name_stays_on_hash_resolved_variant_stem(self) -> None:
        exact_hash = hashlittle(b"cd_phm_01_sword_0166_index01_r", 0xC5EDE)
        record = ArchiveItemRecord(
            item_id=1000,
            internal_name="Item_OneHandSword_Exact",
            display_name="Sword of the Lord",
            prefab_hashes=[exact_hash],
        )

        index = _build_archive_item_search_index_from_records(
            [record],
            [_entry("character/model/cd_phm_01_sword_0166.pac")],
        )

        self.assertEqual(index.model_base_exact_display_names, {"cd_phm_01_sword_0166_index01_r": "Sword of the Lord"})
        self.assertEqual(index.model_base_display_names, {"cd_phm_01_sword_0166": "Sword of the Lord"})

    def test_item_index_adds_character_equipment_root_aliases(self) -> None:
        record = ArchiveItemRecord(
            item_id=1000,
            internal_name="Item_Righteous_Virtue",
            display_name="Righteous Virtue",
            model_stems=["cd_m0001_00_skullknight_ub_0003"],
        )

        index = _build_archive_item_search_index_from_records(
            [record],
            [_entry("character/model/cd_m0001_00_skullknight_ub_0003.pac")],
        )

        self.assertIn("cd_m0001_00_skullknight", index.model_base_aliases)
        self.assertIn("righteous virtue", index.model_base_aliases["cd_m0001_00_skullknight"])

    def test_asset_catalog_dedupes_upgrade_variants_and_carries_icon_paths(self) -> None:
        icon_index = _build_archive_item_icon_path_index(
            [_entry("ui/itemicon/itemicon_prefab_cd_phm_01_sword_0166.dds")]
        )
        records = [
            ArchiveItemRecord(
                item_id=1000,
                internal_name="Item_OneHandSword_0166",
                display_name="Sword of the Lord",
                model_stems=["cd_phm_01_sword_0166"],
            ),
            ArchiveItemRecord(
                item_id=1001,
                internal_name="Item_OneHandSword_0166_level1",
                display_name="Sword of the Lord (+1)",
                model_stems=["cd_phm_01_sword_0166"],
            ),
        ]

        index = _build_archive_item_search_index_from_records(
            records,
            [_entry("character/model/cd_phm_01_sword_0166.pac")],
            icon_path_index=icon_index,
        )

        self.assertEqual(len(index.asset_catalog), 1)
        catalog_row = index.asset_catalog[0]
        self.assertEqual(catalog_row.display_name, "Sword of the Lord")
        self.assertEqual(catalog_row.category, "Weapon")
        self.assertEqual(catalog_row.group, "Sword")
        self.assertEqual(catalog_row.variant_count, 2)
        self.assertIn("ui/itemicon/itemicon_prefab_cd_phm_01_sword_0166.dds", catalog_row.icon_paths)
        self.assertIn("*cd_phm_01_sword_0166*", catalog_row.scope_filter)
        self.assertIn("table fields:", catalog_row.evidence)
        self.assertTrue(any(record.source_field == "_itemIconList" for record in catalog_row.table_evidence))
        self.assertIn("equip_family:weapon", catalog_row.compatibility_tags)
        cache_row = catalog_row.to_cache_dict()
        self.assertTrue(any(row.get("label") == "ItemInfo._itemIconList" for row in cache_row["table_evidence"]))
        self.assertIn("equip_slot:sword", cache_row["compatibility_tags"])

    def test_part_prefab_dye_slot_material_tags_enrich_asset_catalog(self) -> None:
        def lp(value: str) -> bytes:
            data = value.encode("ascii")
            return struct.pack("<I", len(data)) + data

        material_index = _parse_part_prefab_dye_slot_material_index_data(
            b"\x00\x01\x02"
            + lp("cd_demo_armor_0001")
            + b"\x02\x00\x01"
            + lp("cloth")
            + lp("leather")
            + lp("metal")
            + b"\x01\x00\x00"
            + lp("character/model/1_pc/1_phm/armor/9_upperbody/cd_demo_armor_0001.pac")
        )
        index = _build_archive_item_search_index_from_records(
            [
                ArchiveItemRecord(
                    item_id=901,
                    internal_name="Item_Demo_Armor",
                    display_name="Demo Armor",
                    model_stems=["cd_demo_armor_0001"],
                )
            ],
            [],
            material_tag_index=material_index,
        )

        row = index.asset_catalog[0]
        self.assertEqual(row.material_tags, ("cloth", "leather", "metal"))
        self.assertIn("material slot tags: cloth, leather, metal", row.evidence)
        cache_row = row.to_cache_dict()
        self.assertEqual(cache_row["material_tags"], ["cloth", "leather", "metal"])
        self.assertTrue(
            any(
                evidence.get("label") == "PartPrefabDyeSlotInfo._subMeshList"
                for evidence in cache_row["table_evidence"]
            )
        )
        self.assertIn("cloth", index.model_base_aliases["cd_demo_armor_0001"])

    def test_item_icon_path_index_accepts_icon_prefab_and_icon_prefixes(self) -> None:
        sources = _collect_archive_item_index_sources(
            [
                _entry("ui/itemicon/icon_prefab_cd_phm_01_sword_0166.dds"),
                _entry("ui/itemicon/icon_cd_phm_01_sword_0279.dds"),
                _entry("ui/itemicon/icon_cd_phm_01_sword_0999.png"),
            ]
        )

        self.assertEqual(
            [
                "ui/itemicon/icon_prefab_cd_phm_01_sword_0166.dds",
                "ui/itemicon/icon_cd_phm_01_sword_0279.dds",
            ],
            [entry.path for entry in sources.icon_entries],
        )

        icon_index = _build_archive_item_icon_path_index(sources.icon_entries)

        self.assertIn("ui/itemicon/icon_prefab_cd_phm_01_sword_0166.dds", icon_index["cd_phm_01_sword_0166"])
        self.assertIn("ui/itemicon/icon_cd_phm_01_sword_0279.dds", icon_index["cd_phm_01_sword_0279"])

    def test_asset_catalog_builds_friendly_name_when_localization_is_missing(self) -> None:
        index = _build_archive_item_search_index_from_records(
            [
                ArchiveItemRecord(
                    item_id=1000,
                    internal_name="Item_Armor_Cloak_0001_level1",
                    model_stems=["cd_phm_00_cloak_0001"],
                )
            ],
            [_entry("character/model/cd_phm_00_cloak_0001.pac")],
        )

        self.assertEqual(len(index.asset_catalog), 1)
        self.assertEqual(index.asset_catalog[0].display_name, "Armor Cloak 0001")
        self.assertEqual(index.asset_catalog[0].category, "Armor")
        self.assertEqual(index.asset_catalog[0].group, "Back / Cloak")
        self.assertIn("generated friendly name", index.asset_catalog[0].evidence)

    def test_asset_catalog_classifies_obvious_display_name_categories(self) -> None:
        records = [
            ArchiveItemRecord(
                item_id=1000,
                internal_name="Item_Furious_Waves",
                display_name="Furious Waves Gauntlet",
                model_stems=["cd_phm_00_hand_0001"],
            ),
            ArchiveItemRecord(
                item_id=1001,
                internal_name="Bilibili_Earring",
                display_name="Bilibili Earring",
                model_stems=["cd_phm_earring_0001"],
            ),
            ArchiveItemRecord(
                item_id=1002,
                internal_name="Tower_Key",
                display_name="Tower Key",
                model_stems=["tower_key"],
            ),
            ArchiveItemRecord(
                item_id=1003,
                internal_name="Item_bookcase_0001",
                display_name="Bookcase 0001",
                model_stems=["bookcase_0001"],
            ),
            ArchiveItemRecord(
                item_id=1004,
                internal_name="Archaia_OneHandMace",
                display_name="Archaia Onehandmace",
                model_stems=["archaia_onehandmace"],
            ),
            ArchiveItemRecord(
                item_id=1005,
                internal_name="Aggro_Backpack",
                display_name="Aggro Backpack",
                model_stems=["aggro_backpack"],
            ),
            ArchiveItemRecord(
                item_id=1006,
                internal_name="CharacterCustomize_Damian_TieHair",
                display_name="Charactercustomize Damian Tiehair",
                model_stems=["damian_tiehair"],
            ),
            ArchiveItemRecord(
                item_id=1007,
                internal_name="Lance_Onehandlance",
                display_name="Lance Onehandlance",
                model_stems=["lance_onehandlance"],
            ),
            ArchiveItemRecord(
                item_id=1008,
                internal_name="Sungrovemanor_Homekey",
                display_name="Sungrovemanor Homekey",
                model_stems=["sungrovemanor_homekey"],
            ),
            ArchiveItemRecord(
                item_id=1009,
                internal_name="Nahabvillage_Pendant",
                display_name="Nahabvillage Pendant",
                model_stems=["nahabvillage_pendant"],
            ),
            ArchiveItemRecord(
                item_id=1010,
                internal_name="Goblin_Pot",
                display_name="Goblin Pot",
                model_stems=["goblin_pot"],
            ),
            ArchiveItemRecord(
                item_id=1011,
                internal_name="Guardiantree_Pear",
                display_name="Guardiantree Pear",
                model_stems=["guardiantree_pear"],
            ),
            ArchiveItemRecord(
                item_id=1012,
                internal_name="Grace_Blueprint",
                display_name="Grace Blueprint",
                model_stems=["grace_blueprint"],
            ),
            ArchiveItemRecord(
                item_id=1013,
                internal_name="Warrobot_Repairtool_01_L",
                display_name="Warrobot Repairtool 01 L",
                model_stems=["warrobot_repairtool_01_l"],
            ),
            ArchiveItemRecord(
                item_id=1014,
                internal_name="Invisible_Twohandgiantbastard",
                display_name="Invisible Twohandgiantbastard",
                model_stems=["invisible_twohandgiantbastard"],
            ),
            ArchiveItemRecord(
                item_id=1015,
                internal_name="PriestWand_Big_III",
                display_name="Priestwand Big III",
                model_stems=["priestwand_big_iii"],
            ),
            ArchiveItemRecord(
                item_id=1016,
                internal_name="Kliff_Glasses",
                display_name="Kliff Glasses",
                model_stems=["kliff_glasses"],
            ),
            ArchiveItemRecord(
                item_id=1017,
                internal_name="TestNeck_1_1",
                display_name="Testneck 1 1",
                model_stems=["testneck_1_1"],
            ),
            ArchiveItemRecord(
                item_id=1018,
                internal_name="Letter_Wolfmolar_Mountain_WifeLetter",
                display_name="A Wife's Letter",
                model_stems=["letter_wolfmolar_mountain_wifeletter"],
            ),
            ArchiveItemRecord(
                item_id=1019,
                internal_name="Saddler_Note",
                display_name="Saddler's Note",
                model_stems=["saddler_note"],
            ),
            ArchiveItemRecord(
                item_id=1020,
                internal_name="FoodSupplyContract_Calphade",
                display_name="Food Supply Contract - Calphade",
                model_stems=["food_supply_contract_calphade"],
            ),
            ArchiveItemRecord(
                item_id=1021,
                internal_name="Sighting_Camora",
                display_name="Sighting of Camora",
                model_stems=["sighting_camora"],
            ),
            ArchiveItemRecord(
                item_id=1022,
                internal_name="News_WhiteHorn_Defeat",
                display_name="News of White Horn's Defeat",
                model_stems=["news_whitehorn_defeat"],
            ),
            ArchiveItemRecord(
                item_id=1023,
                internal_name="ItemCatch_FishingRod",
                display_name="The Claw",
                model_stems=["cd_t0000_fishingrod_0003"],
            ),
            ArchiveItemRecord(
                item_id=1024,
                internal_name="Mysterious_Elixir",
                display_name="Mysterious Elixir",
                model_stems=["mysterious_elixir"],
            ),
            ArchiveItemRecord(
                item_id=1025,
                internal_name="Recipe_Book_FishingRod_II",
                display_name="Recipe Book FishingRod II",
                model_stems=["recipe_book_fishingrod_ii"],
            ),
            ArchiveItemRecord(
                item_id=1026,
                internal_name="NoticePaper_Finale_WhiteHorn",
                display_name="Notice Paper Finale WhiteHorn",
                model_stems=["noticepaper_finale_whitehorn"],
            ),
            ArchiveItemRecord(
                item_id=1027,
                internal_name="LostLetter_Food_Trader_1",
                display_name="Lost Letter Food Trader 1",
                model_stems=["lostletter_food_trader_1"],
            ),
            ArchiveItemRecord(
                item_id=1028,
                internal_name="PetArmor_Cat_Musket_Uniform",
                display_name="Uniform Cat Outfit",
                model_stems=["petarmor_cat_musket_uniform"],
            ),
            ArchiveItemRecord(
                item_id=1029,
                internal_name="PetArmor_Dog_Rescue",
                display_name="Rescue Puppy Outfit",
                model_stems=["petarmor_dog_rescue"],
            ),
            ArchiveItemRecord(
                item_id=1030,
                internal_name="Item_Marni_Laser_Helm",
                display_name="Marni Laser Helm",
                model_stems=["cd_marni_laser_hel_0001"],
                pac_files=["character/model/1_pc/1_phm/armor/13_hel/cd_marni_laser_hel_0001.pac"],
            ),
            ArchiveItemRecord(
                item_id=1031,
                internal_name="Item_Musket_Border_Guard_Standard_Armor",
                display_name="Musket Border Guard Standard Armor",
                model_stems=["cd_musket_border_guard_ub_0001"],
                pac_files=["character/model/1_pc/1_phm/armor/00_ub/cd_musket_border_guard_ub_0001.pac"],
            ),
            ArchiveItemRecord(
                item_id=1032,
                internal_name="Item_Musket_Border_Guard_Standard_Helm",
                display_name="Musket Border Guard Standard Helm",
                model_stems=["cd_musket_border_guard_hel_0001"],
                pac_files=["character/model/1_pc/1_phm/armor/13_hel/cd_musket_border_guard_hel_0001.pac"],
            ),
            ArchiveItemRecord(
                item_id=1033,
                internal_name="Item_Weaponsmith_Pack",
                display_name="Weaponsmith's Pack",
                model_stems=["weaponsmith_pack"],
                pac_files=["character/model/1_pc/1_phm/weapon/tools/weaponsmith_pack.pac"],
            ),
            ArchiveItemRecord(
                item_id=1034,
                internal_name="Item_Dark_Fog_Lantern",
                display_name="Dark Fog Lantern",
                model_stems=["dark_fog_lantern"],
            ),
            ArchiveItemRecord(
                item_id=1035,
                internal_name="Item_Fancy_Flame_Patterned_Lantern",
                display_name="Fancy Flame-Patterned Lantern",
                model_stems=["fancy_flame_patterned_lantern"],
            ),
            ArchiveItemRecord(
                item_id=1036,
                internal_name="Item_Firefly_Lantern",
                display_name="Firefly Lantern",
                model_stems=["firefly_lantern"],
            ),
            ArchiveItemRecord(
                item_id=1037,
                internal_name="Item_Flame_Lantern",
                display_name="Flame Lantern",
                model_stems=["flame_lantern"],
            ),
            ArchiveItemRecord(
                item_id=1038,
                internal_name="Item_Lantern",
                display_name="Lantern",
                model_stems=["lantern"],
            ),
            ArchiveItemRecord(
                item_id=1039,
                internal_name="Item_Shiny_Blue_Sea_Lantern",
                display_name="Shiny Blue Sea Lantern",
                model_stems=["shiny_blue_sea_lantern"],
            ),
            ArchiveItemRecord(
                item_id=1040,
                internal_name="Item_Wooden_Lantern",
                display_name="Wooden Lantern",
                model_stems=["wooden_lantern"],
            ),
            ArchiveItemRecord(
                item_id=1041,
                internal_name="Item_Blue_Scout_Lantern",
                display_name="Blue Scout Lantern",
                model_stems=["blue_scout_lantern"],
            ),
            ArchiveItemRecord(
                item_id=1042,
                internal_name="Item_Purple_Scout_Lantern",
                display_name="Purple Scout Lantern",
                model_stems=["purple_scout_lantern"],
            ),
            ArchiveItemRecord(
                item_id=1043,
                internal_name="Item_Shroud_Lantern",
                display_name="Shroud Lantern",
                model_stems=["shroud_lantern"],
            ),
            ArchiveItemRecord(
                item_id=1044,
                internal_name="Item_Torch",
                display_name="Torch",
                model_stems=["torch"],
            ),
            ArchiveItemRecord(
                item_id=1045,
                internal_name="Item_Miners_Lantern_Hat",
                display_name="Miner's Lantern Hat",
                model_stems=["miners_lantern_hat"],
            ),
            ArchiveItemRecord(
                item_id=1046,
                internal_name="Item_Tommaso_Guard_Dagger_Tipped_Spear",
                display_name="Tommaso Guard's Dagger-Tipped Spear",
                model_stems=["tommaso_guard_dagger_tipped_spear"],
            ),
            ArchiveItemRecord(
                item_id=1047,
                internal_name="Item_Veil_Leather_Gloves",
                display_name="Veile Leather Gloves",
                model_stems=["veile_leather_gloves"],
            ),
            ArchiveItemRecord(
                item_id=1048,
                internal_name="Item_Face_Oblivion_Of_The_Past",
                display_name="Oblivion of the Past",
                model_stems=["oblivion_of_the_past"],
            ),
            ArchiveItemRecord(
                item_id=1049,
                internal_name="Item_Ashed_Plate_Gloves",
                display_name="Ashed Plate Gloves",
                model_stems=["ashed_plate_gloves"],
            ),
            ArchiveItemRecord(
                item_id=1050,
                internal_name="Item_Arkhan_Plate_Gloves",
                display_name="Arkhan Plate Gloves",
                model_stems=["arkhan_plate_gloves"],
            ),
            ArchiveItemRecord(
                item_id=1051,
                internal_name="Item_Ashed_Plate_Boots",
                display_name="Ashed Plate Boots",
                model_stems=["ashed_plate_boots"],
            ),
            ArchiveItemRecord(
                item_id=1052,
                internal_name="Item_Berkei_Barding",
                display_name="Berkei Barding",
                model_stems=["berkei_barding"],
            ),
            ArchiveItemRecord(
                item_id=1053,
                internal_name="Item_Calpadean_Barding",
                display_name="Calpadean Barding",
                model_stems=["calpadean_barding"],
            ),
            ArchiveItemRecord(
                item_id=1054,
                internal_name="Item_HorseArmor_Royal_Plate",
                display_name="Royal Plate Armor",
                model_stems=["royal_plate_horsearmor"],
            ),
            ArchiveItemRecord(
                item_id=1055,
                internal_name="Item_Artisans_Hand",
                display_name="Artisan's Hand",
                model_stems=["artisans_hand"],
            ),
            ArchiveItemRecord(
                item_id=1056,
                internal_name="Item_Broken_Visione",
                display_name="Broken Visione",
                model_stems=["broken_visione"],
            ),
        ]

        index = _build_archive_item_search_index_from_records(records, [])
        rows = {row.display_name: row for row in index.asset_catalog}

        self.assertEqual(rows["Furious Waves Gauntlet"].category, "Armor")
        self.assertEqual(rows["Furious Waves Gauntlet"].group, "Hands")
        self.assertEqual(rows["Bilibili Earring"].category, "Accessory")
        self.assertEqual(rows["Bilibili Earring"].group, "Earrings")
        self.assertEqual(rows["Tower Key"].category, "Quest / Document")
        self.assertEqual(rows["Tower Key"].group, "Key / Permit")
        self.assertEqual(rows["Bookcase 0001"].category, "Housing / Prop")
        self.assertEqual(rows["Bookcase 0001"].group, "Furniture")
        self.assertEqual(rows["Archaia Onehandmace"].category, "Weapon")
        self.assertEqual(rows["Archaia Onehandmace"].group, "Axe / Mace / Hammer")
        self.assertEqual(rows["Aggro Backpack"].category, "Tool")
        self.assertEqual(rows["Aggro Backpack"].group, "Backpack / Pack")
        self.assertEqual(rows["Charactercustomize Damian Tiehair"].category, "Character Customization")
        self.assertEqual(rows["Charactercustomize Damian Tiehair"].group, "Hair")
        self.assertEqual(rows["Lance Onehandlance"].category, "Weapon")
        self.assertEqual(rows["Lance Onehandlance"].group, "Polearm / Spear")
        self.assertEqual(rows["Sungrovemanor Homekey"].category, "Quest / Document")
        self.assertEqual(rows["Sungrovemanor Homekey"].group, "Key / Permit")
        self.assertEqual(rows["Nahabvillage Pendant"].category, "Accessory")
        self.assertEqual(rows["Nahabvillage Pendant"].group, "Amulet / Charm")
        self.assertEqual(rows["Goblin Pot"].category, "Housing / Prop")
        self.assertEqual(rows["Goblin Pot"].group, "Decor")
        self.assertEqual(rows["Guardiantree Pear"].category, "Consumable")
        self.assertEqual(rows["Guardiantree Pear"].group, "Food / Drink")
        self.assertEqual(rows["Grace Blueprint"].category, "Quest / Document")
        self.assertEqual(rows["Grace Blueprint"].group, "Document")
        self.assertEqual(rows["Warrobot Repairtool 01 L"].category, "Tool")
        self.assertEqual(rows["Warrobot Repairtool 01 L"].group, "Gathering Tool")
        self.assertEqual(rows["Invisible Twohandgiantbastard"].category, "Weapon")
        self.assertEqual(rows["Invisible Twohandgiantbastard"].group, "Sword")
        self.assertEqual(rows["Priestwand Big III"].category, "Weapon")
        self.assertEqual(rows["Priestwand Big III"].group, "Wand / Fan")
        self.assertEqual(rows["Kliff Glasses"].category, "Accessory")
        self.assertEqual(rows["Kliff Glasses"].group, "Other Accessory")
        self.assertEqual(rows["Testneck 1 1"].category, "Accessory")
        self.assertEqual(rows["Testneck 1 1"].group, "Necklace")
        self.assertEqual(rows["A Wife's Letter"].category, "Quest / Document")
        self.assertEqual(rows["A Wife's Letter"].group, "Document")
        self.assertEqual(rows["Saddler's Note"].category, "Quest / Document")
        self.assertEqual(rows["Saddler's Note"].group, "Document")
        self.assertEqual(rows["Food Supply Contract - Calphade"].category, "Quest / Document")
        self.assertEqual(rows["Food Supply Contract - Calphade"].group, "Document")
        self.assertTrue(rows["Food Supply Contract - Calphade"].category_evidence.startswith("Internal ID ->"))
        self.assertEqual(rows["Sighting of Camora"].category, "Quest / Document")
        self.assertEqual(rows["Sighting of Camora"].group, "Clue / Report")
        self.assertEqual(rows["News of White Horn's Defeat"].category, "Quest / Document")
        self.assertEqual(rows["News of White Horn's Defeat"].group, "Clue / Report")
        self.assertEqual(rows["The Claw"].category, "Tool")
        self.assertEqual(rows["The Claw"].group, "Fishing")
        self.assertTrue(rows["The Claw"].category_evidence.startswith("Internal ID ->"))
        self.assertEqual(rows["Mysterious Elixir"].category, "Consumable")
        self.assertEqual(rows["Mysterious Elixir"].group, "Potion / Medicine")
        self.assertEqual(rows["Recipe Book FishingRod II"].category, "Crafting / Recipe")
        self.assertEqual(rows["Recipe Book FishingRod II"].group, "Recipe Book")
        self.assertEqual(rows["Notice Paper Finale WhiteHorn"].category, "Quest / Document")
        self.assertEqual(rows["Notice Paper Finale WhiteHorn"].group, "Document")
        self.assertEqual(rows["Lost Letter Food Trader 1"].category, "Quest / Document")
        self.assertEqual(rows["Lost Letter Food Trader 1"].group, "Document")
        self.assertEqual(rows["Uniform Cat Outfit"].category, "Mount / Pet")
        self.assertEqual(rows["Uniform Cat Outfit"].group, "Pet Gear")
        self.assertTrue(rows["Uniform Cat Outfit"].category_evidence.startswith("Internal ID ->"))
        self.assertEqual(rows["Rescue Puppy Outfit"].category, "Mount / Pet")
        self.assertEqual(rows["Rescue Puppy Outfit"].group, "Pet Gear")
        self.assertTrue(rows["Rescue Puppy Outfit"].category_evidence.startswith("Internal ID ->"))
        self.assertEqual(rows["Marni Laser Helm"].category, "Armor")
        self.assertEqual(rows["Marni Laser Helm"].group, "Head")
        self.assertEqual(rows["Musket Border Guard Standard Armor"].category, "Armor")
        self.assertEqual(rows["Musket Border Guard Standard Armor"].group, "Body")
        self.assertEqual(rows["Musket Border Guard Standard Helm"].category, "Armor")
        self.assertEqual(rows["Musket Border Guard Standard Helm"].group, "Head")
        self.assertEqual(rows["Weaponsmith's Pack"].category, "Tool")
        self.assertEqual(rows["Weaponsmith's Pack"].group, "Backpack / Pack")
        for display_name in (
            "Dark Fog Lantern",
            "Fancy Flame-Patterned Lantern",
            "Firefly Lantern",
            "Flame Lantern",
            "Lantern",
            "Shiny Blue Sea Lantern",
            "Wooden Lantern",
            "Blue Scout Lantern",
            "Purple Scout Lantern",
            "Shroud Lantern",
            "Torch",
        ):
            self.assertEqual(rows[display_name].category, "Tool")
            self.assertEqual(rows[display_name].group, "Light / Lantern")
        self.assertEqual(rows["Miner's Lantern Hat"].category, "Tool")
        self.assertEqual(rows["Miner's Lantern Hat"].group, "Light / Lantern")
        self.assertEqual(rows["Tommaso Guard's Dagger-Tipped Spear"].category, "Weapon")
        self.assertEqual(rows["Tommaso Guard's Dagger-Tipped Spear"].group, "Polearm / Spear")
        for display_name in (
            "Veile Leather Gloves",
            "Ashed Plate Gloves",
            "Arkhan Plate Gloves",
        ):
            self.assertEqual(rows[display_name].category, "Armor")
            self.assertEqual(rows[display_name].group, "Hands")
        self.assertEqual(rows["Ashed Plate Boots"].category, "Armor")
        self.assertEqual(rows["Ashed Plate Boots"].group, "Feet")
        for display_name in (
            "Berkei Barding",
            "Calpadean Barding",
            "Royal Plate Armor",
        ):
            self.assertEqual(rows[display_name].category, "Mount / Pet")
            self.assertEqual(rows[display_name].group, "Horse Gear")
        for display_name in (
            "Oblivion of the Past",
            "Artisan's Hand",
        ):
            self.assertEqual(rows[display_name].category, "Weapon")
            self.assertEqual(rows[display_name].group, "Axe / Mace / Hammer")
        self.assertEqual(rows["Broken Visione"].category, "Armor")
        self.assertEqual(rows["Broken Visione"].group, "Head")

    def test_item_alias_search_uses_display_token_prefixes(self) -> None:
        filtered = filter_archive_entries(
            [_entry("character/model/cd_phm_01_sword_0166.pac")],
            filter_text="lord sword",
            exclude_filter_text="",
            extension_filter="*",
            package_filter_text="",
            structure_filter="",
            role_filter="all",
            exclude_common_technical_suffixes=False,
            min_size_kb=0,
            previewable_only=False,
            item_search_aliases={"cd_phm_01_sword_0166": "Sword of the Lord cd_phm_01_sword_0166.pac"},
        )

        self.assertEqual([entry.path for entry in filtered], ["character/model/cd_phm_01_sword_0166.pac"])


if __name__ == "__main__":
    unittest.main()
