from __future__ import annotations

import struct
import json
import tempfile
import unittest
from pathlib import Path

from cdmw.core.archive_modding import (
    ArchivePatchRequest,
    MeshImportSupplementalFileSpec,
    export_archive_payloads_to_mod_ready_loose,
)
from cdmw.core.mod_package import ModPackageExportOptions
from cdmw.core.source_mix import (
    SourceMixSelection,
    group_source_mix_candidates_by_family,
    normalize_source_mix_virtual_path,
    scan_loose_folder_source,
    scan_mod_archive_source,
    source_mix_role_for_virtual_path,
    validate_source_mix_selections,
)
from cdmw.models import ArchiveEntry, ModPackageInfo


def _entry(path: str, root: Path) -> ArchiveEntry:
    package_root = root / "0008"
    package_root.mkdir(parents=True, exist_ok=True)
    return ArchiveEntry(
        path=path,
        pamt_path=package_root / "0.pamt",
        paz_file=package_root / "0.paz",
        offset=0,
        comp_size=0,
        orig_size=0,
        flags=0,
        paz_index=0,
    )


def _path_block(path: str) -> bytes:
    encoded = path.encode("utf-8")
    return struct.pack("<IB", 0xFFFFFFFF, len(encoded)) + encoded


def _write_single_file_pamt(package_dir: Path, virtual_path: str, payload: bytes) -> Path:
    package_dir.mkdir(parents=True, exist_ok=True)
    pamt_path = package_dir / "0.pamt"
    paz_path = package_dir / "0.paz"
    paz_path.write_bytes(payload)
    name_block = _path_block(virtual_path)
    data = bytearray()
    data.extend(struct.pack("<III", 0, 1, 0))
    data.extend(b"\x00" * 12)
    data.extend(struct.pack("<I", 0))
    data.extend(struct.pack("<I", len(name_block)))
    data.extend(name_block)
    data.extend(struct.pack("<I", 0))
    data.extend(struct.pack("<I", 1))
    data.extend(struct.pack("<IIIIHH", 0, 0, len(payload), len(payload), 0, 0))
    pamt_path.write_bytes(bytes(data))
    return pamt_path


class SourceMixTests(unittest.TestCase):
    def test_loose_folder_scan_normalizes_files_wrapper_virtual_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "ThorPower" / "files" / "gamedata" / "binary__" / "client" / "bin"
            source.mkdir(parents=True)
            payload = source / "iteminfo.pabgb"
            payload.write_bytes(b"body")

            candidates = scan_loose_folder_source(root / "ThorPower")

            self.assertEqual(1, len(candidates))
            self.assertEqual("gamedata/binary__/client/bin/iteminfo.pabgb", candidates[0].normalized_virtual_path)
            self.assertEqual(b"body", candidates[0].read_payload())
            self.assertEqual("Skeleton / Rig", candidates[0].role)
            self.assertEqual("extra", candidates[0].match_status)
            self.assertEqual("skip", candidates[0].default_action)

    def test_mod_archive_scan_uses_archive_virtual_paths_and_lazy_payloads(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            pamt_path = _write_single_file_pamt(
                root / "0036",
                "gamedata/binary__/client/bin/iteminfo.pabgh",
                b"header",
            )

            candidates = scan_mod_archive_source(pamt_path)

            self.assertEqual(1, len(candidates))
            self.assertEqual("gamedata/binary__/client/bin/iteminfo.pabgh", candidates[0].normalized_virtual_path)
            self.assertEqual(b"header", candidates[0].read_payload())

    def test_loose_folder_scan_adds_roles_family_ids_and_match_actions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive_root = root / "archive"
            model_entry = _entry("character/model/1_pc/1_phm/weapon/cd_phm_02_sword_0014.pac", archive_root)
            hkx_entry = _entry("character/bin__/meshphysics/1_pc/1_phm/weapon/cd_phm_02_sword_0014.hkx", archive_root)
            hkt_entry = _entry("character/bin__/meshphysics/1_pc/1_phm/weapon/cd_phm_02_sword_0014.hkt", archive_root)
            target_map = {
                normalize_source_mix_virtual_path(model_entry.path): model_entry,
                normalize_source_mix_virtual_path(hkx_entry.path): hkx_entry,
                normalize_source_mix_virtual_path(hkt_entry.path): hkt_entry,
            }
            loose_root = root / "2hto1hsword" / "files"
            files = {
                "character/model/1_pc/1_phm/weapon/cd_phm_02_sword_0014.pac": b"model",
                "character/modelproperty/1_pc/1_phm/weapon/cd_phm_02_sword_0014.pac_xml": b"mat",
                "character/bin__/meshphysics/1_pc/1_phm/weapon/cd_phm_02_sword_0014.hkx": b"hkx",
                "character/bin__/meshphysics/1_pc/1_phm/weapon/cd_phm_02_sword_0014.hkt": b"hkt",
                "character/descriptors/prefab/cd_phm_02_sword_0014.prefab": b"prefab",
                "character/animation/cd_phm_02_sword_0014.paa": b"paa",
                "character/descriptors/socketbonedata/phm_01.pab.sockets.xml": b"socket",
                "character/texture/cd_phm_02_sword_0014_n.dds": b"dds",
            }
            for relative, payload in files.items():
                path = loose_root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(payload)

            candidates = scan_loose_folder_source(root / "2hto1hsword", target_entries_by_virtual_path=target_map)
            by_path = {candidate.normalized_virtual_path: candidate for candidate in candidates}
            self.assertEqual("Model", by_path[normalize_source_mix_virtual_path(model_entry.path)].role)
            self.assertEqual("exact", by_path[normalize_source_mix_virtual_path(model_entry.path)].match_status)
            self.assertEqual("replace", by_path[normalize_source_mix_virtual_path(model_entry.path)].default_action)
            self.assertEqual("Physics HKX", by_path[normalize_source_mix_virtual_path(hkx_entry.path)].role)
            self.assertEqual("Physics HKX", by_path[normalize_source_mix_virtual_path(hkt_entry.path)].role)
            self.assertEqual("Material", source_mix_role_for_virtual_path("x/cd_phm_02_sword_0014.pac_xml"))
            self.assertEqual("Socket XML", source_mix_role_for_virtual_path("x/phm_01.pab.sockets.xml"))
            grouped = group_source_mix_candidates_by_family(candidates)
            model_family = by_path[normalize_source_mix_virtual_path(model_entry.path)].family_id
            self.assertIn(model_family, grouped)
            self.assertGreaterEqual(len(grouped[model_family]), 2)

    def test_loose_folder_scan_matches_compact_working_mod_paths_by_basename(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive_root = root / "archive"
            model_entry = _entry(
                "character/model/1_pc/1_phm/weapon/2_twohandweapon/cd_phm_02_sword_0042.pac",
                archive_root,
            )
            sidecar_entry = _entry(
                "character/modelproperty/1_pc/1_phm/weapon/2_twohandweapon/cd_phm_02_sword_0042.pac_xml",
                archive_root,
            )
            target_map = {
                normalize_source_mix_virtual_path(model_entry.path): model_entry,
                normalize_source_mix_virtual_path(sidecar_entry.path): sidecar_entry,
            }
            loose_root = root / "CrimsonForgeMod"
            files = {
                "files/character/cd_phm_02_sword_0042.pac": b"model",
                "files/character/cd_phm_02_sword_0042.pac_xml": b"mat",
                "manifest.json": b"{}",
                "modinfo.json": b"{}",
                "README.txt": b"readme",
            }
            for relative, payload in files.items():
                path = loose_root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(payload)

            candidates = scan_loose_folder_source(loose_root, target_entries_by_virtual_path=target_map)

            self.assertEqual(2, len(candidates))
            by_source_path = {candidate.normalized_virtual_path: candidate for candidate in candidates}
            compact_model = by_source_path["character/cd_phm_02_sword_0042.pac"]
            compact_sidecar = by_source_path["character/cd_phm_02_sword_0042.pac_xml"]
            self.assertIs(compact_model.target_archive_entry, model_entry)
            self.assertIs(compact_sidecar.target_archive_entry, sidecar_entry)
            self.assertEqual("basename", compact_model.match_status)
            self.assertEqual("replace", compact_model.default_action)
            self.assertIn("filename", compact_model.confidence)

    def test_loose_folder_scan_marks_duplicate_conflicts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = root / "A" / "files" / "character" / "model" / "x.pac"
            second = root / "A" / "character" / "model" / "x.pac"
            first.parent.mkdir(parents=True, exist_ok=True)
            second.parent.mkdir(parents=True, exist_ok=True)
            first.write_bytes(b"one")
            second.write_bytes(b"different")

            candidates = scan_loose_folder_source(root / "A")

            matching = [candidate for candidate in candidates if candidate.normalized_virtual_path == "character/model/x.pac"]
            self.assertEqual(2, len(matching))
            self.assertTrue(all(candidate.conflict_status == "conflict" for candidate in matching))
            self.assertTrue(all(candidate.default_action == "resolve" for candidate in matching))

    def test_incomplete_pabgb_pabgh_selection_blocks_export(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = _entry("gamedata/binary__/client/bin/iteminfo.pabgb", root)
            source_dir = root / "Mod" / "files" / "gamedata" / "binary__" / "client" / "bin"
            source_dir.mkdir(parents=True)
            (source_dir / "iteminfo.pabgb").write_bytes(b"body")
            candidates = scan_loose_folder_source(
                root / "Mod",
                target_entries_by_virtual_path={
                    normalize_source_mix_virtual_path(target.path): target,
                },
            )

            result = validate_source_mix_selections(
                [
                    SourceMixSelection(
                        virtual_path=target.path,
                        chosen_candidate=candidates[0],
                        strategy="replace",
                    )
                ]
            )

            self.assertFalse(result.ok)
            self.assertIn("requires gamedata/binary__/client/bin/iteminfo.pabgh", "\n".join(result.blocking_errors))

    def test_complete_pabgb_pabgh_selection_writes_loose_package_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            body_entry = _entry("gamedata/binary__/client/bin/iteminfo.pabgb", root)
            header_entry = _entry("gamedata/binary__/client/bin/iteminfo.pabgh", root)
            source_dir = root / "Mod" / "files" / "gamedata" / "binary__" / "client" / "bin"
            source_dir.mkdir(parents=True)
            (source_dir / "iteminfo.pabgb").write_bytes(b"body")
            (source_dir / "iteminfo.pabgh").write_bytes(b"header")
            target_map = {
                normalize_source_mix_virtual_path(body_entry.path): body_entry,
                normalize_source_mix_virtual_path(header_entry.path): header_entry,
            }
            candidates = {
                candidate.normalized_virtual_path: candidate
                for candidate in scan_loose_folder_source(root / "Mod", target_entries_by_virtual_path=target_map)
            }
            selections = [
                SourceMixSelection(body_entry.path, candidates[normalize_source_mix_virtual_path(body_entry.path)], "replace"),
                SourceMixSelection(header_entry.path, candidates[normalize_source_mix_virtual_path(header_entry.path)], "replace"),
            ]

            validation = validate_source_mix_selections(selections)
            self.assertTrue(validation.ok, validation.blocking_errors)
            result = export_archive_payloads_to_mod_ready_loose(
                [
                    ArchivePatchRequest(entry=selection.chosen_candidate.target_archive_entry, payload_data=selection.chosen_candidate.read_payload())
                    for selection in selections
                    if selection.chosen_candidate is not None and selection.chosen_candidate.target_archive_entry is not None
                ],
                parent_root=root / "exports",
                package_info=ModPackageInfo(title="Pair Mod"),
                export_options=ModPackageExportOptions(create_zip=False),
            )

            self.assertTrue((result.package_root / "gamedata" / "binary__" / "client" / "bin" / "iteminfo.pabgb").exists())
            self.assertTrue((result.package_root / "gamedata" / "binary__" / "client" / "bin" / "iteminfo.pabgh").exists())
            self.assertTrue((result.package_root / "manifest.json").exists())

    def test_source_mix_export_can_include_sidecar_referenced_extra_payloads(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = _entry("character/modelproperty/weapon/target_weapon.pac_xml", root)
            extra_dds = root / "source" / "files" / "character" / "texture" / "source_custom.dds"
            extra_dds.parent.mkdir(parents=True)
            extra_dds.write_bytes(b"DDS custom")

            result = export_archive_payloads_to_mod_ready_loose(
                [
                    ArchivePatchRequest(
                        entry=target,
                        payload_data=(
                            b'<SkinnedMeshMaterialWrapper _subMeshName="weapon">'
                            b'<MaterialParameterTexture _name="_baseColorTexture">'
                            b'<ResourceReferencePath_ITexture Name="_value" _path="character/texture/source_custom.dds"/>'
                            b"</MaterialParameterTexture>"
                            b"</SkinnedMeshMaterialWrapper>"
                        ),
                    )
                ],
                parent_root=root / "exports",
                package_info=ModPackageInfo(title="Sidecar Extra"),
                export_options=ModPackageExportOptions(create_zip=False),
                extra_payloads_to_include=(
                    MeshImportSupplementalFileSpec(
                        source_path=extra_dds,
                        target_path="character/texture/source_custom.dds",
                        kind="texture",
                        target_entry=None,
                    ),
                ),
            )

            self.assertTrue((result.package_root / "character" / "modelproperty" / "weapon" / "target_weapon.pac_xml").exists())
            self.assertTrue((result.package_root / "character" / "texture" / "source_custom.dds").exists())

    def test_existing_target_icon_extra_payload_is_not_declared_as_new_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = _entry("character/model/weapon/target_weapon.pac", root)
            icon_entry = _entry("ui/itemicon/itemicon_prefab_cd_phm_01_sword_0166.dds", root)
            icon_payload = root / "generated_icon.dds"
            icon_payload.write_bytes(b"DDS generated icon")

            result = export_archive_payloads_to_mod_ready_loose(
                [ArchivePatchRequest(entry=target, payload_data=b"model")],
                parent_root=root / "exports",
                package_info=ModPackageInfo(title="Icon Override"),
                export_options=ModPackageExportOptions(create_zip=False),
                extra_payloads_to_include=(
                    MeshImportSupplementalFileSpec(
                        source_path=icon_payload,
                        target_path=icon_entry.path,
                        kind="item_icon_generated",
                        target_entry=icon_entry,
                        payload_data=icon_payload.read_bytes(),
                    ),
                ),
            )

            manifest = json.loads((result.package_root / "manifest.json").read_text(encoding="utf-8"))
            self.assertTrue((result.package_root / "ui" / "itemicon" / "itemicon_prefab_cd_phm_01_sword_0166.dds").exists())
            self.assertNotIn("new_paths", manifest)


if __name__ == "__main__":
    unittest.main()
