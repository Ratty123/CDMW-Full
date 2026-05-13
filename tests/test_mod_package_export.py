from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from cdmw.core.mod_package import (
    MOD_PACKAGE_METADATA_ARTIFACTS_BY_KEY,
    MeshLooseModAsset,
    MeshLooseModFile,
    ModPackageExportOptions,
    finalize_mod_package_export,
    mod_package_export_options_for_manager,
    write_mesh_loose_mod_package_metadata,
    write_mod_package_manifest,
)
from cdmw.models import ModPackageInfo


class ModPackageExportTests(unittest.TestCase):
    def test_universal_game_relative_metadata_is_minimal_by_default(self) -> None:
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

            manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))

            self.assertEqual(manifest.get("manager_targets"), ["universal"])
            self.assertEqual(manifest.get("files_dir"), ".")
            self.assertNotIn("files_root", manifest)
            self.assertNotIn("new_paths", manifest)
            self.assertTrue((root / ".no_encrypt").exists())
            self.assertFalse((root / "mod.json").exists())
            self.assertFalse((root / "modinfo.json").exists())
            self.assertFalse((root / "info.json").exists())

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
                options=ModPackageExportOptions(structure="custom_compact_paths"),
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
        universal = mod_package_export_options_for_manager("universal")
        self.assertTrue(universal.create_manifest_json)
        self.assertFalse(universal.create_mod_json)
        self.assertFalse(universal.create_modinfo_json)
        self.assertFalse(universal.create_info_json)
        self.assertFalse(universal.create_texture_resolution_manifest)

        retired_manager = mod_package_export_options_for_manager("retired_manager")
        self.assertTrue(retired_manager.create_manifest_json)
        self.assertFalse(retired_manager.create_mod_json)
        self.assertFalse(retired_manager.create_modinfo_json)
        self.assertFalse(retired_manager.create_info_json)
        self.assertEqual(("universal",), retired_manager.manager_targets)

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

        field_json = mod_package_export_options_for_manager("field_json")
        self.assertFalse(field_json.create_manifest_json)
        self.assertFalse(field_json.create_mod_json)
        self.assertFalse(field_json.create_modinfo_json)
        self.assertFalse(field_json.create_info_json)
        self.assertEqual(("field_json",), field_json.manager_targets)
        self.assertEqual("field_json_v31", field_json.structure)

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
