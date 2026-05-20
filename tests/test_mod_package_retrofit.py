from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from cdmw.core.mod_package_retrofit import (
    retrofit_mod_package,
    scan_retrofittable_mod_packages,
)


def _write_manifest(root: Path, *, kind: str = "mesh_loose_mod") -> None:
    payload = {
        "format": "v1",
        "schema_version": 1,
        "kind": kind,
        "title": root.name,
        "name": root.name,
        "version": "1.0",
        "author": "Tester",
        "description": f"{root.name} description",
        "game_build": "2",
        "game_metadata": {"primary_package_group": "0009"},
        "include_paired_lod": False,
        "assets": [
            {
                "entry_path": "character/model/example.pac",
                "package_group": "0009",
                "format": "pac",
                "vertices": 3,
                "faces": 1,
                "submeshes": 1,
            }
        ],
        "files": [
            {"path": "character/model/example.pac", "package_group": "0009", "format": "pac"},
            {"path": "character/modelproperty/example.pac_xml", "package_group": "0009", "format": "pac_xml"},
            {"path": "character/texture/example.dds", "package_group": "0009", "format": "dds"},
        ],
    }
    (root / "manifest.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_mesh_package(root: Path) -> None:
    (root / "character" / "model").mkdir(parents=True)
    (root / "character" / "modelproperty").mkdir(parents=True)
    (root / "character" / "texture").mkdir(parents=True)
    (root / "character" / "model" / "example.pac").write_bytes(b"PAC")
    (root / "character" / "modelproperty" / "example.pac_xml").write_text("<xml/>", encoding="utf-8")
    (root / "character" / "texture" / "example.dds").write_bytes(b"DDS ")
    (root / ".no_encrypt").write_text("", encoding="utf-8")
    (root / "README.txt").write_text("readme", encoding="utf-8")
    (root / "picture_1.png").write_bytes(b"PNG")
    with zipfile.ZipFile(root / f"{root.name}.zip", "w") as archive:
        archive.writestr("old.txt", "old archive")
    _write_manifest(root)


class ModPackageRetrofitTests(unittest.TestCase):
    def test_scan_parent_and_direct_package_ignore_preview_images_and_existing_zip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            parent = Path(temp_dir)
            package_root = parent / "SkullLantern_v1"
            package_root.mkdir()
            _write_mesh_package(package_root)

            parent_results = scan_retrofittable_mod_packages(parent)
            direct_results = scan_retrofittable_mod_packages(package_root)

            self.assertEqual(["SkullLantern_v1"], [package.name for package in parent_results])
            self.assertEqual(["SkullLantern_v1"], [package.name for package in direct_results])
            self.assertEqual("mesh_loose_mod", parent_results[0].kind)
            self.assertEqual(
                [
                    "character/model/example.pac",
                    "character/modelproperty/example.pac_xml",
                    "character/texture/example.dds",
                ],
                sorted(parent_results[0].payload_paths),
            )

    def test_files_wrapper_scan_normalizes_to_game_relative_payloads(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "Wrapped"
            (root / "files" / "character" / "texture").mkdir(parents=True)
            (root / "files" / "character" / "texture" / "wrapped.dds").write_bytes(b"DDS ")
            (root / "manifest.json").write_text(json.dumps({"title": "Wrapped", "kind": "dds_loose_mod"}), encoding="utf-8")

            result = scan_retrofittable_mod_packages(root)[0]

            self.assertEqual(("character/texture/wrapped.dds",), result.payload_paths)
            self.assertEqual("dds_loose_mod", result.kind)

    def test_dmm_texture_retrofit_writes_modinfo_zip_and_leaves_original_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "TextureOnly"
            (source / "character" / "texture").mkdir(parents=True)
            (source / "character" / "texture" / "sample.dds").write_bytes(b"DDS ")
            (source / "manifest.json").write_text(json.dumps({"title": "Texture Only", "kind": "dds_loose_mod"}), encoding="utf-8")
            with zipfile.ZipFile(source / "TextureOnly.zip", "w") as archive:
                archive.writestr("old.txt", "old")
            original_zip_bytes = (source / "TextureOnly.zip").read_bytes()

            package = scan_retrofittable_mod_packages(source)[0]
            result = retrofit_mod_package(package, Path(temp_dir) / "converted", manager_profile="dmm")

            self.assertTrue((result.package_root / "modinfo.json").is_file())
            self.assertFalse((result.package_root / "manifest.json").exists())
            self.assertFalse((result.package_root / ".no_encrypt").exists())
            self.assertTrue(result.zip_path.is_file())
            self.assertEqual(original_zip_bytes, (source / "TextureOnly.zip").read_bytes())
            self.assertTrue((source / "manifest.json").is_file())
            with zipfile.ZipFile(result.zip_path) as archive:
                names = set(archive.namelist())
            self.assertIn("modinfo.json", names)
            self.assertIn("character/texture/sample.dds", names)
            self.assertNotIn("TextureOnly.zip", names)
            self.assertNotIn("old.txt", names)

    def test_dmm_mesh_retrofit_keeps_workbench_manifest_and_adds_modinfo(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "MeshMod"
            source.mkdir()
            _write_mesh_package(source)

            package = scan_retrofittable_mod_packages(source)[0]
            result = retrofit_mod_package(package, Path(temp_dir) / "converted", manager_profile="dmm")

            manifest = json.loads((result.package_root / "manifest.json").read_text(encoding="utf-8"))
            modinfo = json.loads((result.package_root / "modinfo.json").read_text(encoding="utf-8"))
            self.assertEqual("mesh_loose_mod", manifest["kind"])
            self.assertEqual("game_relative", manifest["structure"])
            self.assertEqual(["dmm"], manifest["manager_targets"])
            self.assertEqual("MeshMod", modinfo["name"])
            self.assertFalse((result.package_root / ".no_encrypt").exists())
            self.assertTrue(result.zip_path.is_file())

    def test_manager_profiles_generate_expected_metadata_shapes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "Profiles"
            (source / "character" / "texture").mkdir(parents=True)
            (source / "character" / "texture" / "sample.dds").write_bytes(b"DDS " + b"\0" * 8)
            (source / "manifest.json").write_text(json.dumps({"title": "Profiles", "kind": "dds_loose_mod"}), encoding="utf-8")
            package = scan_retrofittable_mod_packages(source)[0]
            output = Path(temp_dir) / "converted"

            universal = retrofit_mod_package(package, output, manager_profile="universal").package_root
            cdumm = retrofit_mod_package(package, output, manager_profile="cdumm").package_root
            crimson = retrofit_mod_package(package, output, manager_profile="crimson_sharp").package_root
            field_json = retrofit_mod_package(package, output, manager_profile="field_json").package_root

            self.assertTrue((universal / "manifest.json").is_file())
            self.assertTrue((universal / ".no_encrypt").is_file())
            self.assertTrue((cdumm / "modinfo.json").is_file())
            self.assertTrue((cdumm / "files" / "character" / "texture" / "sample.dds").is_file())
            self.assertTrue((crimson / "mod.json").is_file())
            self.assertTrue((crimson / "files" / "character" / "texture" / "sample.dds").is_file())
            self.assertTrue((field_json / "mod.field.json").is_file())
            self.assertTrue((field_json / "assets" / "character" / "texture" / "sample.dds").is_file())

    def test_nested_jmm_json_zip_scans_and_retrofits_to_jmm_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source_zip = Path(temp_dir) / "Wolf Gravestone Sword 2h (JSON).zip"
            mod_json = {
                "name": "Wolf Gravestone Sword_2h_v1",
                "title": "Wolf Gravestone Sword (2H) v1",
                "version": "1.0",
                "author": "Ratrider",
                "game": "Crimson Desert",
                "description": "Replaces a two-handed sword.",
                "kind": "file_replacement",
                "category": "weapon",
                "target": "character/model/1_pc/weapon/example.pac",
                "files": [
                    "character/model/1_pc/weapon/example.pac",
                    "character/modelproperty/1_pc/weapon/example.pac_xml",
                    "character/texture/example_basecolor.dds",
                    "character/texture/example_n.dds",
                ],
                "new_paths": [
                    "character/texture/example_basecolor.dds",
                    "character/texture/example_n.dds",
                ],
            }
            with zipfile.ZipFile(source_zip, "w") as archive:
                prefix = "Wolf Gravestone Sword 2h (JSON)/Wolf Gravestone Sword_2h_v1"
                archive.writestr(f"{prefix}/character/model/1_pc/weapon/example.pac", b"PAC")
                archive.writestr(f"{prefix}/character/modelproperty/1_pc/weapon/example.pac_xml", b"<xml/>")
                archive.writestr(f"{prefix}/character/texture/example_basecolor.dds", b"DDS base")
                archive.writestr(f"{prefix}/character/texture/example_n.dds", b"DDS normal")
                archive.writestr(f"{prefix}/mod.json", json.dumps(mod_json))

            packages = scan_retrofittable_mod_packages(source_zip)
            self.assertEqual(1, len(packages))
            self.assertEqual("Wolf Gravestone Sword 2h (JSON)", packages[0].name)
            self.assertEqual("mesh_loose_mod", packages[0].kind)
            self.assertEqual(tuple(mod_json["files"]), packages[0].payload_paths)
            self.assertEqual(("mod.json",), packages[0].existing_metadata)

            result = retrofit_mod_package(packages[0], Path(temp_dir) / "converted", manager_profile="jmm")

            written_mod_json = json.loads((result.package_root / "mod.json").read_text(encoding="utf-8"))
            self.assertEqual("file_replacement", written_mod_json["kind"])
            self.assertEqual("weapon", written_mod_json["category"])
            self.assertEqual(mod_json["files"], written_mod_json["files"])
            self.assertEqual(mod_json["new_paths"], written_mod_json["new_paths"])
            self.assertTrue((result.package_root / "character" / "model" / "1_pc" / "weapon" / "example.pac").is_file())
            self.assertTrue(result.zip_path.is_file())
            with zipfile.ZipFile(result.zip_path) as archive:
                names = set(archive.namelist())
            self.assertIn("mod.json", names)
            self.assertIn("character/model/1_pc/weapon/example.pac", names)
            self.assertNotIn("Wolf Gravestone Sword 2h (JSON).zip", names)

    def test_ui_source_exposes_dialog_and_uses_retrofit_helper(self) -> None:
        source = Path("cdmw/ui/main_window.py").read_text(encoding="utf-8")

        self.assertIn("Retrofit Packaged Mods...", source)
        self.assertIn("QTableWidget(0, 7)", source)
        self.assertIn("RETROFIT_MANAGER_PROFILES", source)
        self.assertIn('"jmm": "JMM JSON"', source)
        self.assertIn("manager_combo.addItem", source)
        self.assertIn("retrofit_mod_package(package, output_root, manager_profile=profile)", source)
        self.assertIn("scan_retrofittable_mod_packages(source)", source)


if __name__ == "__main__":
    unittest.main()
