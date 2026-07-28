from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from cdmw.core.archive_modding import ArchivePatchRequest, export_archive_payloads_to_mod_ready_loose
from cdmw.core.mod_package import (
    MOD_PACKAGE_METADATA_ARTIFACTS_BY_KEY,
    MeshLooseModAsset,
    MeshLooseModFile,
    ModPackageExportOptions,
    finalize_mod_package_export,
    mod_package_expanded_export_options,
    mod_package_export_options_for_profiles,
    mod_package_export_options_for_manager,
    write_mesh_loose_mod_package_metadata,
    write_mod_package_manifest,
)
from cdmw.core.pipeline import build_mod_package_export_options_from_config
from cdmw.models import AppConfig, ArchiveEntry, ModPackageInfo


def _entry(path: str, root: Path) -> ArchiveEntry:
    pamt_path = root / "0009" / "0009.pamt"
    paz_path = root / "0009" / "0.paz"
    pamt_path.parent.mkdir(parents=True, exist_ok=True)
    return ArchiveEntry(
        path=path,
        pamt_path=pamt_path,
        paz_file=paz_path,
        offset=0,
        comp_size=1,
        orig_size=1,
        flags=0,
        paz_index=0,
    )


class ModPackageExportTests(unittest.TestCase):
    def test_default_package_options_target_dmm(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "ExampleMod"
            payload = root / "object" / "texture" / "sample.dds"
            payload.parent.mkdir(parents=True)
            payload.write_bytes(b"DDS ")

            finalize_mod_package_export(
                root,
                ModPackageInfo(title="Example", version="1.2", author="Author", description="Desc", nexus_url="https://example.com"),
                kind="dds_loose_mod",
                payload_paths=("object/texture/sample.dds",),
                options=ModPackageExportOptions(structure="game_relative", create_zip=False),
            )

            self.assertFalse((root / "manifest.json").exists())
            self.assertFalse((root / "mod.json").exists())
            self.assertTrue((root / "modinfo.json").exists())
            self.assertFalse((root / "info.json").exists())
            self.assertFalse((root / ".no_encrypt").exists())

    def test_explicit_compatibility_metadata_is_consistent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "ExampleMod"
            payload = root / "object" / "texture" / "sample.dds"
            payload.parent.mkdir(parents=True)
            payload.write_bytes(b"DDS ")

            finalize_mod_package_export(
                root,
                ModPackageInfo(title="Example", version="1.2", author="Author", description="Desc", nexus_url="https://example.com"),
                kind="dds_loose_mod",
                payload_paths=("object/texture/sample.dds",),
                options=ModPackageExportOptions(
                    manager_targets=("cdumm",),
                    structure="game_relative",
                    create_mod_json=True,
                    create_modinfo_json=True,
                    create_info_json=True,
                    create_zip=False,
                ),
            )

            manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
            mod_json = json.loads((root / "mod.json").read_text(encoding="utf-8"))
            modinfo = json.loads((root / "modinfo.json").read_text(encoding="utf-8"))
            info_json = json.loads((root / "info.json").read_text(encoding="utf-8"))

            for key in ("title", "version", "author", "description", "nexus_url", "game", "generator", "files_dir", "manager_targets"):
                self.assertEqual(manifest.get(key), info_json.get(key), key)
                self.assertEqual(manifest.get(key), mod_json.get(key), key)
            self.assertEqual(modinfo.get("name"), "Example")
            self.assertEqual(modinfo.get("version"), "1.2")
            self.assertEqual(modinfo.get("author"), "Author")
            self.assertEqual(modinfo.get("description"), "Desc")
            self.assertNotIn("manager_targets", modinfo)

    def test_ready_zip_excludes_stale_material_authority_reports_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "ExampleMod"
            payload = root / "character" / "texture" / "sample.dds"
            payload.parent.mkdir(parents=True)
            payload.write_bytes(b"DDS ")
            (root / "cdmw_material_authority_report.json").write_text("{}", encoding="utf-8")
            (root / "cdmw_material_authority_report_check.json").write_text("{}", encoding="utf-8")

            finalize_mod_package_export(
                root,
                ModPackageInfo(title="Example"),
                kind="dds_loose_mod",
                payload_paths=("character/texture/sample.dds",),
                options=ModPackageExportOptions(create_zip=True, create_material_authority_report=False),
            )

            with zipfile.ZipFile(root.with_suffix(".zip")) as archive:
                names = set(archive.namelist())
            self.assertIn("character/texture/sample.dds", names)
            self.assertNotIn("cdmw_material_authority_report.json", names)
            self.assertNotIn("cdmw_material_authority_report_check.json", names)

    def test_ready_zip_can_include_material_authority_reports_when_requested(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "ExampleMod"
            payload = root / "character" / "texture" / "sample.dds"
            payload.parent.mkdir(parents=True)
            payload.write_bytes(b"DDS ")
            (root / "cdmw_material_authority_report.json").write_text("{}", encoding="utf-8")
            (root / "cdmw_material_authority_report_check.json").write_text("{}", encoding="utf-8")

            finalize_mod_package_export(
                root,
                ModPackageInfo(title="Example"),
                kind="dds_loose_mod",
                payload_paths=("character/texture/sample.dds",),
                options=ModPackageExportOptions(create_zip=True, create_material_authority_report=True),
            )

            with zipfile.ZipFile(root.with_suffix(".zip")) as archive:
                names = set(archive.namelist())
            self.assertIn("cdmw_material_authority_report.json", names)
            self.assertIn("cdmw_material_authority_report_check.json", names)

    def test_files_wrapper_moves_payload_and_preserves_new_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "WrappedMod"
            payload = root / "object" / "texture" / "new.dds"
            payload.parent.mkdir(parents=True)
            payload.write_bytes(b"DDS ")

            finalize_mod_package_export(
                root,
                ModPackageInfo(title="Wrapped"),
                kind="dds_loose_mod",
                payload_paths=("object/texture/new.dds",),
                new_file_paths=("object/texture/new.dds",),
                options=ModPackageExportOptions(manager_targets=("cdumm",), structure="files_wrapper"),
            )

            manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
            self.assertFalse(payload.exists())
            self.assertTrue((root / "files" / "object" / "texture" / "new.dds").exists())
            self.assertFalse((root / "object").exists())
            self.assertEqual(manifest.get("format"), "v1")
            self.assertEqual(manifest.get("files_dir"), "files")
            self.assertEqual(manifest.get("files_root"), "files")
            self.assertEqual(manifest.get("new_paths"), ["object/texture/new.dds"])
            self.assertEqual(manifest.get("manager_targets"), ["cdumm"])

    def test_archive_loose_export_preserves_actionchart_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            actionchart_path = "actionchart/bin__/animmeta/1_pc/1_phm/test_motion.paa_metabin"

            result = export_archive_payloads_to_mod_ready_loose(
                [ArchivePatchRequest(_entry(actionchart_path, root), b"meta")],
                parent_root=root,
                package_info=ModPackageInfo(title="ActionchartMod"),
                export_options=mod_package_export_options_for_manager("cdumm"),
            )

            self.assertTrue((result.package_root / "files" / "actionchart" / "bin__" / "animmeta" / "1_pc" / "1_phm" / "test_motion.paa_metabin").is_file())
            self.assertFalse((result.package_root / "files" / "test_motion.paa_metabin").exists())

    def test_cdumm_modinfo_uses_documented_fields_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "CdummMod"
            payload = root / "object" / "texture" / "sample.dds"
            payload.parent.mkdir(parents=True)
            payload.write_bytes(b"DDS ")

            write_mod_package_manifest(
                root,
                ModPackageInfo(title="CDUMM Example", version="2.0", author="Author", description="Desc"),
                kind="dds_loose_mod",
                export_options=ModPackageExportOptions(
                    manager_targets=("cdumm",),
                    structure="files_wrapper",
                    create_modinfo_json=True,
                    conflict_mode="override",
                    target_language="ko",
                ),
            )

            modinfo = json.loads((root / "modinfo.json").read_text(encoding="utf-8"))
            self.assertEqual(
                set(modinfo),
                {"name", "version", "author", "description", "conflict_mode", "target_language"},
            )
            self.assertEqual(modinfo["conflict_mode"], "override")
            self.assertEqual(modinfo["target_language"], "ko")

    def test_dmm_texture_profile_writes_texture_folder_shape(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "DmmTextureMod"
            payload = root / "character" / "texture" / "sample.dds"
            payload.parent.mkdir(parents=True)
            payload.write_bytes(b"DDS ")

            returned_path = write_mod_package_manifest(
                root,
                ModPackageInfo(title="DMM Texture", version="1.0", author="Author", description="Desc"),
                kind="dds_loose_mod",
                export_options=ModPackageExportOptions(
                    manager_targets=("dmm",),
                    structure="dmm_texture",
                    create_manifest_json=False,
                    create_mod_json=False,
                    create_info_json=False,
                    create_no_encrypt_file=False,
                ),
            )

            self.assertTrue((root / "character" / "texture" / "sample.dds").exists())
            self.assertTrue((root / "modinfo.json").exists())
            self.assertFalse((root / "files").exists())
            self.assertFalse((root / "manifest.json").exists())
            self.assertFalse((root / "mod.json").exists())
            self.assertFalse((root / "info.json").exists())
            self.assertFalse((root / ".no_encrypt").exists())
            self.assertEqual(returned_path.name, "modinfo.json")
            modinfo = json.loads((root / "modinfo.json").read_text(encoding="utf-8"))
            self.assertEqual(set(modinfo), {"name", "version", "author", "description"})
            readme_text = (root / "README.txt").read_text(encoding="utf-8")
            self.assertIn("mods/_textures/", readme_text)
            self.assertIn("LAYOUT\n=========================================================", readme_text)
            self.assertIn("This DMM texture layout intentionally does not use a", readme_text)
            self.assertIn("files/ wrapper.", readme_text)
            self.assertNotIn("NOTES\n=========================================================", readme_text)
            self.assertNotIn("Preferred manager", readme_text)
            self.assertNotIn("nexusmods.com/crimsondesert/mods/113", readme_text)

    def test_field_json_v31_profile_writes_assets_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "FieldJsonMod"
            payload_bytes = b"DDS " + b"\x00" * 128
            payload = root / "character" / "texture" / "sample.dds"
            payload.parent.mkdir(parents=True)
            payload.write_bytes(payload_bytes)

            returned_path = write_mod_package_manifest(
                root,
                ModPackageInfo(title="Field Example", version="1.0", author="Author", description="Desc"),
                kind="dds_loose_mod",
                export_options=ModPackageExportOptions(
                    manager_targets=("field_json",),
                    structure="field_json_v31",
                    create_manifest_json=False,
                    create_no_encrypt_file=False,
                ),
            )

            field_manifest_path = root / "mod.field.json"
            asset_path = root / "assets" / "character" / "texture" / "sample.dds"
            self.assertEqual(field_manifest_path, returned_path)
            self.assertTrue(asset_path.exists())
            self.assertFalse((root / "manifest.json").exists())
            self.assertFalse((root / ".no_encrypt").exists())
            manifest = json.loads(field_manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(3, manifest["format"])
            self.assertEqual(1, manifest["format_minor"])
            self.assertEqual("Field Example", manifest["modinfo"]["name"])
            self.assertEqual(
                [
                    {
                        "kind": "asset",
                        "asset_type": "dds",
                        "file": "assets/character/texture/sample.dds",
                        "vpath": "/character/texture/sample.dds",
                        "sha256": hashlib.sha256(payload_bytes).hexdigest(),
                        "size": len(payload_bytes),
                    }
                ],
                manifest["targets"],
            )
            self.assertIn("Field-JSON", (root / "README.txt").read_text(encoding="utf-8"))

    def test_custom_compact_paths_uses_files_wrapper_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "CompactMod"
            payload = root / "character" / "sample.pac"
            payload.parent.mkdir(parents=True)
            payload.write_bytes(b"PAC ")

            finalize_mod_package_export(
                root,
                ModPackageInfo(title="Compact"),
                kind="mesh_loose_mod",
                payload_paths=("character/sample.pac",),
                options=ModPackageExportOptions(manager_targets=("cdumm",), structure="custom_compact_paths"),
            )

            manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
            self.assertFalse(payload.exists())
            self.assertTrue((root / "files" / "character" / "sample.pac").exists())
            self.assertFalse((root / "character").exists())
            self.assertEqual(manifest.get("structure"), "custom_compact_paths")
            self.assertEqual(manifest.get("files_dir"), "files")
            self.assertEqual(manifest.get("files_root"), "files")

    def test_mesh_loose_mod_coerces_dmm_texture_structure_to_mesh_safe_layout(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "MeshDmmSafe"
            payload = root / "character" / "sample.pac"
            payload.parent.mkdir(parents=True)
            payload.write_bytes(b"PAC ")

            finalize_mod_package_export(
                root,
                ModPackageInfo(title="Mesh DMM Safe"),
                kind="mesh_loose_mod",
                payload_paths=("character/sample.pac",),
                options=ModPackageExportOptions(manager_targets=("dmm",), structure="dmm_texture"),
            )

            manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
            self.assertTrue((root / "character" / "sample.pac").exists())
            self.assertEqual(manifest.get("structure"), "game_relative")
            self.assertEqual(manifest.get("files_dir"), ".")

    def test_dmm_mesh_profile_writes_manifest_and_modinfo(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "MeshDmm"
            payload = root / "character" / "model" / "sample.pac"
            payload.parent.mkdir(parents=True)
            payload.write_bytes(b"PAC ")

            write_mesh_loose_mod_package_metadata(
                root,
                ModPackageInfo(title="Mesh DMM", version="1.0", author="Author"),
                assets=(
                    MeshLooseModAsset(
                        entry_path="character/model/sample.pac",
                        package_group="0009",
                        format="pac",
                    ),
                ),
                files=(
                    MeshLooseModFile(
                        path="character/model/sample.pac",
                        package_group="0009",
                        format="pac",
                    ),
                ),
                include_paired_lod=False,
                export_options=mod_package_export_options_for_profiles(("dmm",)),
            )

            manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
            modinfo = json.loads((root / "modinfo.json").read_text(encoding="utf-8"))
            self.assertEqual("mesh_loose_mod", manifest["kind"])
            self.assertEqual("game_relative", manifest["structure"])
            self.assertEqual(["dmm"], manifest["manager_targets"])
            self.assertEqual("Mesh DMM", modinfo["name"])
            self.assertFalse((root / ".no_encrypt").exists())

    def test_no_encrypt_toggle_and_ready_zip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "ZipMod"
            payload = root / "object" / "texture" / "sample.dds"
            payload.parent.mkdir(parents=True)
            payload.write_bytes(b"DDS ")

            result = finalize_mod_package_export(
                root,
                ModPackageInfo(title="Zip"),
                payload_paths=("object/texture/sample.dds",),
                options=ModPackageExportOptions(create_no_encrypt_file=False, create_zip=True),
            )

            self.assertFalse((root / ".no_encrypt").exists())
            self.assertIsNotNone(result.zip_path)
            assert result.zip_path is not None
            with zipfile.ZipFile(result.zip_path) as archive:
                names = set(archive.namelist())
            self.assertIn("manifest.json", names)
            self.assertNotIn("mod.json", names)
            self.assertNotIn("modinfo.json", names)
            self.assertNotIn("info.json", names)
            self.assertIn("object/texture/sample.dds", names)
            self.assertNotIn(".no_encrypt", names)

    def test_manager_profiles_write_only_targeted_metadata_by_default(self) -> None:
        retired_manager = mod_package_export_options_for_manager("retired_manager")
        self.assertFalse(retired_manager.create_manifest_json)
        self.assertFalse(retired_manager.create_mod_json)
        self.assertTrue(retired_manager.create_modinfo_json)
        self.assertFalse(retired_manager.create_info_json)
        self.assertEqual(("dmm",), retired_manager.manager_targets)

        cdumm = mod_package_export_options_for_manager("cdumm")
        self.assertTrue(cdumm.create_manifest_json)
        self.assertFalse(cdumm.create_mod_json)
        self.assertTrue(cdumm.create_modinfo_json)
        self.assertFalse(cdumm.create_info_json)

        dmm = mod_package_export_options_for_manager("dmm")
        self.assertFalse(dmm.create_manifest_json)
        self.assertFalse(dmm.create_mod_json)
        self.assertTrue(dmm.create_modinfo_json)
        self.assertFalse(dmm.create_info_json)
        self.assertFalse(dmm.create_texture_resolution_manifest)
        self.assertFalse(dmm.create_material_authority_report)
        self.assertFalse(dmm.create_active_file_authority_audit)

        field_json = mod_package_export_options_for_manager("field_json")
        self.assertFalse(field_json.create_manifest_json)
        self.assertFalse(field_json.create_mod_json)
        self.assertFalse(field_json.create_modinfo_json)
        self.assertFalse(field_json.create_info_json)
        self.assertEqual(("field_json",), field_json.manager_targets)
        self.assertEqual("field_json_v31", field_json.structure)

        jmm = mod_package_export_options_for_manager("jmm")
        self.assertFalse(jmm.create_manifest_json)
        self.assertFalse(jmm.create_mod_json)
        self.assertFalse(jmm.create_modinfo_json)
        self.assertFalse(jmm.create_info_json)
        self.assertEqual(("jmm",), jmm.manager_targets)
        self.assertEqual("game_relative", jmm.structure)

    def test_multi_profile_config_keeps_cdumm_conflict_options(self) -> None:
        options = build_mod_package_export_options_from_config(
            AppConfig(
                mod_ready_manager_profile="dmm",
                mod_ready_manager_profiles=("dmm", "cdumm"),
                mod_ready_conflict_mode="override",
                mod_ready_target_language="ko",
            )
        )

        self.assertEqual("override", options.conflict_mode)
        self.assertEqual("ko", options.target_language)

    def test_profile_helper_auto_maps_single_manager_metadata(self) -> None:
        cdumm = mod_package_export_options_for_profiles(("cdumm",), conflict_mode="override", target_language="ko")

        self.assertEqual(("cdumm",), cdumm.manager_targets)
        self.assertEqual((), cdumm.export_profiles)
        self.assertEqual("files_wrapper", cdumm.structure)
        self.assertTrue(cdumm.create_manifest_json)
        self.assertTrue(cdumm.create_modinfo_json)
        self.assertFalse(cdumm.create_mod_json)
        self.assertTrue(cdumm.create_no_encrypt_file)
        self.assertEqual("override", cdumm.conflict_mode)
        self.assertEqual("ko", cdumm.target_language)

        jmm = mod_package_export_options_for_profiles(
            ("jmm",),
            create_zip=True,
            create_material_authority_report=True,
            create_active_file_authority_audit=True,
        )
        self.assertEqual(("jmm",), jmm.manager_targets)
        self.assertEqual("game_relative", jmm.structure)
        self.assertFalse(jmm.create_manifest_json)
        self.assertTrue(jmm.create_zip)
        self.assertTrue(jmm.create_material_authority_report)
        self.assertTrue(jmm.create_active_file_authority_audit)

    def test_profile_helper_expands_multi_manager_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            entry = _entry("character/texture/sample.dds", root)

            export_options = mod_package_export_options_for_profiles(
                ("jmm", "cdumm"),
                create_zip=True,
                create_material_authority_report=True,
                conflict_mode="override",
            )
            result = export_archive_payloads_to_mod_ready_loose(
                (ArchivePatchRequest(entry, b"DDS "),),
                parent_root=root / "out",
                package_info=ModPackageInfo(title="AutoProfiles"),
                export_options=export_options,
            )

            jmm_root = root / "out" / "AutoProfiles_jmm"
            cdumm_root = root / "out" / "AutoProfiles_cdumm"
            self.assertEqual((jmm_root, cdumm_root), result.package_roots)
            self.assertTrue((jmm_root / "mod.json").is_file())
            self.assertFalse((jmm_root / "manifest.json").exists())
            self.assertTrue((jmm_root.with_suffix(".zip")).is_file())
            self.assertTrue((cdumm_root / "manifest.json").is_file())
            self.assertTrue((cdumm_root / "modinfo.json").is_file())
            self.assertTrue((cdumm_root / "files" / "character" / "texture" / "sample.dds").is_file())
            modinfo = json.loads((cdumm_root / "modinfo.json").read_text(encoding="utf-8"))
            self.assertEqual("override", modinfo["conflict_mode"])

            expanded = mod_package_expanded_export_options(export_options)
            self.assertTrue(expanded[0][1].create_material_authority_report)
            self.assertTrue(expanded[1][1].create_material_authority_report)

    def test_jmm_profile_writes_jmm_mod_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "JmmMod"
            payload = root / "character" / "model" / "weapon" / "sample.pac"
            payload.parent.mkdir(parents=True)
            payload.write_bytes(b"PAC")
            texture = root / "character" / "texture" / "sample_new.dds"
            texture.parent.mkdir(parents=True)
            texture.write_bytes(b"DDS ")

            write_mod_package_manifest(
                root,
                ModPackageInfo(title="JMM Example", version="1.0", author="Author"),
                kind="mesh_loose_mod",
                all_payload_paths=(
                    "character/model/weapon/sample.pac",
                    "character/texture/sample_new.dds",
                ),
                new_file_paths=("character/texture/sample_new.dds",),
                export_options=ModPackageExportOptions(manager_targets=("jmm",), structure="game_relative"),
            )

            self.assertFalse((root / "manifest.json").exists())
            mod_json = json.loads((root / "mod.json").read_text(encoding="utf-8"))
            self.assertEqual("JMM Example", mod_json["title"])
            self.assertEqual("character/model/weapon/sample.pac", mod_json["target"])
            self.assertEqual(
                ["character/model/weapon/sample.pac", "character/texture/sample_new.dds"],
                mod_json["files"],
            )
            self.assertEqual(["character/texture/sample_new.dds"], mod_json["new_paths"])

    def test_jmm_archive_export_mirrors_player_descriptor_alias_for_placement(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            entry = _entry("character/phm_description_player_kliff.xml", root)

            result = export_archive_payloads_to_mod_ready_loose(
                (ArchivePatchRequest(entry, b"<Root/>"),),
                parent_root=root / "out",
                package_info=ModPackageInfo(title="JMM Placement"),
                export_options=ModPackageExportOptions(manager_targets=("jmm",), structure="game_relative"),
            )

            package_root = result.package_root
            root_alias = package_root / "character" / "phm_description_player_kliff.xml"
            descriptor_alias = (
                package_root
                / "character"
                / "descriptors"
                / "characterdescription"
                / "phm_description_player_kliff.xml"
            )
            self.assertTrue(root_alias.is_file())
            self.assertTrue(descriptor_alias.is_file())
            self.assertEqual(root_alias.read_bytes(), descriptor_alias.read_bytes())

            mod_json = json.loads((package_root / "mod.json").read_text(encoding="utf-8"))
            self.assertIn("character/phm_description_player_kliff.xml", mod_json["files"])
            self.assertIn(
                "character/descriptors/characterdescription/phm_description_player_kliff.xml",
                mod_json["files"],
            )
            self.assertIn(
                "character/descriptors/characterdescription/phm_description_player_kliff.xml",
                mod_json["new_paths"],
            )

    def test_multi_profile_archive_export_writes_separate_profile_folders_and_zips(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            entry = _entry("character/texture/sample.dds", root)

            result = export_archive_payloads_to_mod_ready_loose(
                (ArchivePatchRequest(entry, b"DDS "),),
                parent_root=root / "out",
                package_info=ModPackageInfo(title="Multi"),
                export_options=ModPackageExportOptions(
                    export_profiles=("jmm", "cdumm"),
                    create_zip=True,
                    conflict_mode="override",
                ),
            )

            jmm_root = root / "out" / "Multi_jmm"
            cdumm_root = root / "out" / "Multi_cdumm"
            self.assertEqual((jmm_root, cdumm_root), result.package_roots)
            self.assertTrue((jmm_root / "mod.json").is_file())
            self.assertTrue((jmm_root.with_suffix(".zip")).is_file())
            self.assertTrue((cdumm_root / "manifest.json").is_file())
            self.assertTrue((cdumm_root / "modinfo.json").is_file())
            self.assertTrue((cdumm_root.with_suffix(".zip")).is_file())
            self.assertTrue((cdumm_root / "files" / "character" / "texture" / "sample.dds").is_file())

    def test_metadata_artifact_table_covers_generate_options(self) -> None:
        expected = {
            "manifest_json",
            "mod_json",
            "modinfo_json",
            "info_json",
            "mod_field_json",
            "no_encrypt",
            "ready_zip",
        }
        self.assertEqual(expected, set(MOD_PACKAGE_METADATA_ARTIFACTS_BY_KEY))
        for key in expected:
            self.assertTrue(MOD_PACKAGE_METADATA_ARTIFACTS_BY_KEY[key].label)
            self.assertTrue(MOD_PACKAGE_METADATA_ARTIFACTS_BY_KEY[key].description)

    def test_mesh_manifest_records_game_index_fingerprints(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "MeshMod"

            write_mesh_loose_mod_package_metadata(
                root,
                ModPackageInfo(title="Mesh"),
                assets=(
                    MeshLooseModAsset(
                        entry_path="character/example.pac",
                        package_group="0009",
                        format="pac",
                        obj_path="source.obj",
                        vertices=3,
                        faces=1,
                        submeshes=1,
                    ),
                ),
                files=(
                    MeshLooseModFile(
                        path="character/example.pac",
                        package_group="0009",
                        format="pac",
                    ),
                ),
                include_paired_lod=False,
                game_build="0.papgt 0x12345678",
                game_metadata={
                    "game_build": "0.papgt 0x12345678",
                    "papgt_crc": "0x12345678",
                    "pamt_crc": "0xABCDEF01",
                },
                export_options=ModPackageExportOptions(manager_targets=("cdumm",)),
            )

            manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["game_build"], "0.papgt 0x12345678")
            self.assertEqual(manifest["game_metadata"]["papgt_crc"], "0x12345678")
            self.assertEqual(manifest["game_metadata"]["pamt_crc"], "0xABCDEF01")

    def test_mesh_manifest_lists_exact_new_file_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "MeshMod"

            write_mesh_loose_mod_package_metadata(
                root,
                ModPackageInfo(title="Mesh"),
                assets=(
                    MeshLooseModAsset(
                        entry_path="character/model/weapon/example.pac",
                        package_group="0009",
                        format="pac",
                    ),
                ),
                files=(
                    MeshLooseModFile(
                        path="character/model/weapon/example.pac",
                        package_group="0009",
                        format="pac",
                    ),
                    MeshLooseModFile(
                        path="character/modelproperty/weapon/example.pac_xml",
                        package_group="0009",
                        format="pac_xml",
                    ),
                    MeshLooseModFile(
                        path="character/texture/example_base_color.dds",
                        package_group="0009",
                        format="dds",
                        is_new=True,
                    ),
                    MeshLooseModFile(
                        path="character/texture/example_n.dds",
                        package_group="0009",
                        format="dds",
                        is_new=True,
                    ),
                ),
                include_paired_lod=False,
            )

            manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(
                manifest["new_paths"],
                [
                    "character/texture/example_base_color.dds",
                    "character/texture/example_n.dds",
                ],
            )

    def test_high_level_manifest_writer_readme_lists_generated_metadata_and_zip_contains_readme(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "ReadmeMod"
            payload = root / "object" / "texture" / "sample.dds"
            payload.parent.mkdir(parents=True)
            payload.write_bytes(b"DDS ")

            write_mod_package_manifest(
                root,
                ModPackageInfo(title="Readme"),
                kind="dds_loose_mod",
                all_payload_paths=("object/texture/sample.dds",),
                export_options=ModPackageExportOptions(
                    manager_targets=("cdumm",),
                    create_mod_json=True,
                    create_modinfo_json=True,
                    create_info_json=True,
                    create_zip=True,
                ),
            )

            readme_text = (root / "README.txt").read_text(encoding="utf-8")
            self.assertIn("Crimson Desert Mod Workbench", readme_text)
            self.assertIn("Generated Loose Mod Package", readme_text)
            self.assertIn("::::::::::::-------------::---::-----:---------::::::::::", readme_text)
            self.assertIn(":::::::----::--:::-----====+==+++=++**++++=---:::::::::::", readme_text)
            self.assertIn("========     ===       ===  =====  ==  ====  ====  ======", readme_text)
            self.assertIn("+=======================================================+", readme_text)
            self.assertIn("PACKAGE\n=========================================================", readme_text)
            self.assertIn("Loose files        1", readme_text)
            self.assertNotIn("NOTES\n=========================================================", readme_text)
            self.assertNotIn("Generated automatically by Crimson Desert Mod Workbench.", readme_text)
            self.assertNotIn("Keep manifest.json with the payload for validation and manager compatibility.", readme_text)
            self.assertNotIn("Keep generated metadata files with the package when sharing or archiving it.", readme_text)
            self.assertNotIn("Preferred manager", readme_text)
            self.assertNotIn("preferred mod manager", readme_text)
            self.assertNotIn("nexusmods.com/crimsondesert/mods/113", readme_text)
            for expected in ("manifest.json", "mod.json", "modinfo.json", "info.json", ".no_encrypt", "ReadmeMod.zip"):
                self.assertIn(expected, readme_text)
            with zipfile.ZipFile(root.with_suffix(".zip")) as archive:
                names = set(archive.namelist())
            self.assertIn("README.txt", names)
            self.assertIn("manifest.json", names)


if __name__ == "__main__":
    unittest.main()


class RemovalGuidanceTest(unittest.TestCase):
    """Every package said how to install it and nothing said how to get back.

    That is the step someone needs exactly when the game has stopped working
    and they are least able to go looking for it.
    """

    def test_readme_says_how_to_remove_the_mod(self) -> None:
        from cdmw.core.mod_package import _readme_add_section

        lines: list[str] = []
        _readme_add_section(lines, "Removing This Mod")
        self.assertIn("REMOVING THIS MOD", "\n".join(lines))
