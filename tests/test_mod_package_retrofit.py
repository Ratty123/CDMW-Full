from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from cdmw.core.mod_package import ModPackageExportOptions
from cdmw.core.mod_package_retrofit import (
    build_retrofit_path_repair_summary,
    merge_retrofittable_mod_packages,
    retrofit_mod_package,
    scan_retrofittable_mod_packages,
)
from cdmw.models import ArchiveEntry
from cdmw.models import ModPackageInfo


def _entry(path: str, root: Path, group: str = "0009") -> ArchiveEntry:
    pamt_path = root / group / f"{group}.pamt"
    paz_path = root / group / "0.paz"
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


def _write_sword_mesh_package(root: Path, sword_id: str) -> tuple[str, str, str]:
    model_path = f"character/model/1_pc/1_phm/weapon/2_twohandweapon/cd_phm_02_sword_{sword_id}.pac"
    sidecar_path = f"character/modelproperty/1_pc/1_phm/weapon/2_twohandweapon/cd_phm_02_sword_{sword_id}.pac_xml"
    texture_path = f"character/texture/cd_phm_02_sword_{sword_id}_merged_basecolor.dds"
    root.joinpath(*Path(model_path).parts).parent.mkdir(parents=True, exist_ok=True)
    root.joinpath(*Path(sidecar_path).parts).parent.mkdir(parents=True, exist_ok=True)
    root.joinpath(*Path(texture_path).parts).parent.mkdir(parents=True, exist_ok=True)
    root.joinpath(*Path(model_path).parts).write_bytes(f"PAC {sword_id}".encode("ascii"))
    root.joinpath(*Path(sidecar_path).parts).write_text("<xml/>", encoding="utf-8")
    root.joinpath(*Path(texture_path).parts).write_bytes(b"DDS ")
    manifest = {
        "format": "v1",
        "schema_version": 1,
        "kind": "mesh_loose_mod",
        "title": root.name,
        "name": root.name,
        "version": "1.0",
        "author": "Tester",
        "description": f"{root.name} description",
        "game_build": ">9",
        "game_metadata": {"primary_package_group": "0009"},
        "include_paired_lod": False,
        "new_paths": [texture_path],
        "assets": [
            {
                "entry_path": model_path,
                "package_group": "0009",
                "format": "pac",
                "vertices": 3,
                "faces": 1,
                "submeshes": 1,
            }
        ],
        "files": [
            {"path": model_path, "package_group": "0009", "format": "pac"},
            {"path": sidecar_path, "package_group": "0009", "format": "pac_xml"},
            {"path": texture_path, "package_group": "0009", "format": "dds", "is_new": True},
        ],
    }
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return model_path, sidecar_path, texture_path


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

            dmm = retrofit_mod_package(package, output, manager_profile="dmm").package_root
            cdumm = retrofit_mod_package(package, output, manager_profile="cdumm").package_root
            crimson = retrofit_mod_package(package, output, manager_profile="crimson_sharp").package_root
            field_json = retrofit_mod_package(package, output, manager_profile="field_json").package_root

            self.assertTrue((dmm / "modinfo.json").is_file())
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

    def test_jmm_retrofit_mirrors_player_descriptor_alias_for_placement(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "Placement"
            root_descriptor = source / "character" / "phm_description_player_kliff.xml"
            root_descriptor.parent.mkdir(parents=True)
            root_descriptor.write_text("<Root/>", encoding="utf-8")
            manifest = {
                "kind": "archive_loose_mod",
                "title": "Placement",
                "name": "Placement",
                "new_paths": ["character/phm_description_player_kliff.xml"],
            }
            (source / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            package = scan_retrofittable_mod_packages(source)[0]

            result = retrofit_mod_package(package, root / "converted", manager_profile="jmm")

            root_alias = result.package_root / "character" / "phm_description_player_kliff.xml"
            descriptor_alias = (
                result.package_root
                / "character"
                / "descriptors"
                / "characterdescription"
                / "phm_description_player_kliff.xml"
            )
            self.assertTrue(root_alias.is_file())
            self.assertTrue(descriptor_alias.is_file())
            self.assertEqual(root_alias.read_bytes(), descriptor_alias.read_bytes())
            mod_json = json.loads((result.package_root / "mod.json").read_text(encoding="utf-8"))
            self.assertIn("character/phm_description_player_kliff.xml", mod_json["files"])
            self.assertIn("character/descriptors/characterdescription/phm_description_player_kliff.xml", mod_json["files"])
            self.assertIn("character/phm_description_player_kliff.xml", mod_json["new_paths"])
            self.assertIn(
                "character/descriptors/characterdescription/phm_description_player_kliff.xml",
                mod_json["new_paths"],
            )

    def test_jmm_retrofit_marks_existing_player_descriptor_alias_as_new_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "Placement"
            root_descriptor = source / "character" / "phm_description_player_kliff.xml"
            descriptor_alias = (
                source
                / "character"
                / "descriptors"
                / "characterdescription"
                / "phm_description_player_kliff.xml"
            )
            root_descriptor.parent.mkdir(parents=True)
            descriptor_alias.parent.mkdir(parents=True)
            root_descriptor.write_text("<Root/>", encoding="utf-8")
            descriptor_alias.write_text("<Root/>", encoding="utf-8")
            manifest = {
                "kind": "archive_loose_mod",
                "title": "Placement",
                "name": "Placement",
                "new_paths": ["character/phm_description_player_kliff.xml"],
            }
            (source / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            package = scan_retrofittable_mod_packages(source)[0]

            result = retrofit_mod_package(package, root / "converted", manager_profile="jmm")

            mod_json = json.loads((result.package_root / "mod.json").read_text(encoding="utf-8"))
            self.assertIn("character/phm_description_player_kliff.xml", mod_json["new_paths"])
            self.assertIn(
                "character/descriptors/characterdescription/phm_description_player_kliff.xml",
                mod_json["new_paths"],
            )

    def test_custom_compact_paths_retrofit_to_jmm_repairs_model_and_sidecar_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "Compact"
            (source / "files" / "character" / "texture").mkdir(parents=True)
            (source / "files" / "character" / "example.pac").write_bytes(b"PAC")
            (source / "files" / "character" / "example.pac_xml").write_text("<xml/>", encoding="utf-8")
            (source / "files" / "character" / "texture" / "example_new.dds").write_bytes(b"DDS ")
            manifest = {
                "format": "v1",
                "schema_version": 1,
                "kind": "mesh_loose_mod",
                "title": "Compact",
                "name": "Compact",
                "version": "1.0",
                "manager_targets": ["cdumm"],
                "files_dir": "files",
                "structure": "custom_compact_paths",
                "new_paths": ["character/texture/example_new.dds"],
                "assets": [
                    {
                        "entry_path": "character/example.pac",
                        "package_group": "0009",
                        "format": "pac",
                    }
                ],
                "files": [
                    {"path": "character/example.pac", "package_group": "0009", "format": "pac"},
                    {"path": "character/example.pac_xml", "package_group": "0009", "format": "pac_xml"},
                    {"path": "character/texture/example_new.dds", "format": "dds", "is_new": True},
                ],
            }
            (source / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            package = scan_retrofittable_mod_packages(source)[0]
            archive_index = {
                "example.pac": [
                    _entry("character/model/1_pc/weapon/example.pac", root, "0009"),
                ],
                "example.pac_xml": [
                    _entry("character/modelproperty/1_pc/weapon/example.pac_xml", root, "0009"),
                ],
            }

            result = retrofit_mod_package(
                package,
                root / "converted",
                manager_profile="jmm",
                archive_entries_by_basename=archive_index,
            )

            self.assertEqual(2, result.repaired_path_count)
            self.assertTrue((result.package_root / "character" / "model" / "1_pc" / "weapon" / "example.pac").is_file())
            self.assertTrue((result.package_root / "character" / "modelproperty" / "1_pc" / "weapon" / "example.pac_xml").is_file())
            self.assertTrue((result.package_root / "character" / "texture" / "example_new.dds").is_file())
            mod_json = json.loads((result.package_root / "mod.json").read_text(encoding="utf-8"))
            self.assertEqual("character/model/1_pc/weapon/example.pac", mod_json["target"])
            self.assertIn("character/model/1_pc/weapon/example.pac", mod_json["files"])
            self.assertIn("character/modelproperty/1_pc/weapon/example.pac_xml", mod_json["files"])
            self.assertIn("character/texture/example_new.dds", mod_json["new_paths"])
            self.assertNotIn("character/example.pac", mod_json["files"])

    def test_compact_repair_uses_assets_group_and_case_insensitive_archive_key(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "AssetOnly"
            (source / "files" / "character").mkdir(parents=True)
            (source / "files" / "character" / "example.pac").write_bytes(b"PAC")
            (source / "manifest.json").write_text(
                json.dumps(
                    {
                        "kind": "mesh_loose_mod",
                        "structure": "custom_compact_paths",
                        "assets": [
                            {
                                "entry_path": "character/example.pac",
                                "package_group": "0009",
                                "format": "pac",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            package = scan_retrofittable_mod_packages(source)[0]

            summary = build_retrofit_path_repair_summary(
                package,
                archive_entries_by_basename={
                    "Example.PAC": [
                        _entry("character/model/1_pc/weapon/example.pac", root, "0009"),
                        _entry("character/model/1_pc/npc/example.pac", root, "0008"),
                    ]
                },
            )

            self.assertEqual(1, summary.repaired_path_count)
            self.assertEqual("character/model/1_pc/weapon/example.pac", summary.mappings[0].target_path)

    def test_custom_compact_path_without_archive_index_warns_and_falls_back(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "Compact"
            (source / "files" / "character").mkdir(parents=True)
            (source / "files" / "character" / "example.pac").write_bytes(b"PAC")
            (source / "manifest.json").write_text(
                json.dumps(
                    {
                        "kind": "mesh_loose_mod",
                        "structure": "custom_compact_paths",
                        "files_dir": "files",
                        "files": [{"path": "character/example.pac", "package_group": "0009", "format": "pac"}],
                    }
                ),
                encoding="utf-8",
            )
            package = scan_retrofittable_mod_packages(source)[0]

            summary = build_retrofit_path_repair_summary(package)
            result = retrofit_mod_package(package, root / "converted", manager_profile="jmm")

            self.assertEqual(1, summary.unresolved_path_count)
            self.assertEqual(1, result.unresolved_path_count)
            self.assertTrue(any("without loaded archive index" in warning for warning in result.warnings))
            self.assertTrue((result.package_root / "character" / "example.pac").is_file())

    def test_cdumm_retrofit_accepts_structure_conflict_and_language_options(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "Cdumm"
            (source / "character" / "texture").mkdir(parents=True)
            (source / "character" / "texture" / "sample.dds").write_bytes(b"DDS ")
            (source / "manifest.json").write_text(json.dumps({"title": "Cdumm", "kind": "dds_loose_mod"}), encoding="utf-8")
            package = scan_retrofittable_mod_packages(source)[0]

            result = retrofit_mod_package(
                package,
                root / "converted",
                manager_profile="cdumm",
                export_options=ModPackageExportOptions(
                    manager_targets=("cdumm",),
                    structure="custom_compact_paths",
                    create_modinfo_json=True,
                    conflict_mode="override",
                    target_language="ko",
                    create_zip=True,
                ),
            )

            manifest = json.loads((result.package_root / "manifest.json").read_text(encoding="utf-8"))
            modinfo = json.loads((result.package_root / "modinfo.json").read_text(encoding="utf-8"))
            self.assertEqual("custom_compact_paths", manifest["structure"])
            self.assertEqual("override", modinfo["conflict_mode"])
            self.assertEqual("ko", modinfo["target_language"])

    def test_cdumm_merge_combines_distinct_sword_packages(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = root / "Gravey"
            second = root / "Hehe"
            first_model, first_sidecar, first_texture = _write_sword_mesh_package(first, "0015")
            second_model, second_sidecar, second_texture = _write_sword_mesh_package(second, "0009")
            packages = scan_retrofittable_mod_packages(root)
            by_name = {package.name: package for package in packages}

            result = merge_retrofittable_mod_packages(
                (by_name["Gravey"], by_name["Hehe"]),
                root / "converted",
                package_info=ModPackageInfo(title="Gravey Hehe Combo", version="1.0", author="Tester"),
                export_options=ModPackageExportOptions(
                    manager_targets=("cdumm",),
                    structure="files_wrapper",
                    create_modinfo_json=True,
                    create_zip=True,
                ),
            )

            for payload in (first_model, first_sidecar, first_texture, second_model, second_sidecar, second_texture):
                self.assertTrue(result.package_root.joinpath("files", *Path(payload).parts).is_file())
            self.assertTrue((result.package_root / "manifest.json").is_file())
            self.assertTrue((result.package_root / "modinfo.json").is_file())
            self.assertTrue(result.zip_path.is_file())

            manifest = json.loads((result.package_root / "manifest.json").read_text(encoding="utf-8"))
            modinfo = json.loads((result.package_root / "modinfo.json").read_text(encoding="utf-8"))
            self.assertEqual(["cdumm"], manifest["manager_targets"])
            self.assertEqual("files_wrapper", manifest["structure"])
            self.assertEqual("Gravey Hehe Combo", modinfo["name"])
            files = {item["path"]: item for item in manifest["files"]}
            self.assertEqual("0009", files[first_model]["package_group"])
            self.assertEqual("0009", files[second_model]["package_group"])
            self.assertIn(first_texture, manifest["new_paths"])
            self.assertIn(second_texture, manifest["new_paths"])

            readme = (result.package_root / "README.txt").read_text(encoding="utf-8")
            self.assertIn("Import this merged package instead of enabling the source mods separately", readme)
            with zipfile.ZipFile(result.zip_path) as archive:
                names = set(archive.namelist())
            self.assertIn(f"files/{first_model}", names)
            self.assertIn(f"files/{second_model}", names)

    def test_cdumm_merge_blocks_duplicate_resolved_payload_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = root / "First"
            second = root / "Second"
            _write_sword_mesh_package(first, "0009")
            _write_sword_mesh_package(second, "0009")
            packages = scan_retrofittable_mod_packages(root)

            with self.assertRaisesRegex(ValueError, "duplicate payload paths"):
                merge_retrofittable_mod_packages(
                    packages,
                    root / "converted",
                    package_info=ModPackageInfo(title="Duplicate Combo", version="1.0"),
                    export_options=ModPackageExportOptions(manager_targets=("cdumm",), create_zip=True),
                )
            self.assertFalse((root / "converted" / "Duplicate Combo_cdumm_merged").exists())

    def test_cdumm_merge_repairs_compact_paths_before_duplicate_checks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = root / "CompactA"
            second = root / "CompactB"
            for source, sword_id in ((first, "0009"), (second, "0015")):
                (source / "files" / "character").mkdir(parents=True)
                (source / "files" / "character" / f"cd_phm_02_sword_{sword_id}.pac").write_bytes(b"PAC")
                manifest = {
                    "kind": "mesh_loose_mod",
                    "title": source.name,
                    "structure": "custom_compact_paths",
                    "files_dir": "files",
                    "assets": [
                        {
                            "entry_path": f"character/cd_phm_02_sword_{sword_id}.pac",
                            "package_group": "0009",
                            "format": "pac",
                        }
                    ],
                    "files": [
                        {
                            "path": f"character/cd_phm_02_sword_{sword_id}.pac",
                            "package_group": "0009",
                            "format": "pac",
                        }
                    ],
                }
                (source / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            packages = scan_retrofittable_mod_packages(root)
            archive_index = {
                "cd_phm_02_sword_0009.pac": [
                    _entry(
                        "character/model/1_pc/1_phm/weapon/2_twohandweapon/cd_phm_02_sword_0009.pac",
                        root,
                        "0009",
                    )
                ],
                "cd_phm_02_sword_0015.pac": [
                    _entry(
                        "character/model/1_pc/1_phm/weapon/2_twohandweapon/cd_phm_02_sword_0015.pac",
                        root,
                        "0009",
                    )
                ],
            }

            result = merge_retrofittable_mod_packages(
                packages,
                root / "converted",
                package_info=ModPackageInfo(title="Compact Combo", version="1.0"),
                export_options=ModPackageExportOptions(manager_targets=("cdumm",), create_zip=True),
                archive_entries_by_basename=archive_index,
            )

            self.assertEqual(2, result.repaired_path_count)
            self.assertTrue(
                (
                    result.package_root
                    / "files"
                    / "character"
                    / "model"
                    / "1_pc"
                    / "1_phm"
                    / "weapon"
                    / "2_twohandweapon"
                    / "cd_phm_02_sword_0009.pac"
                ).is_file()
            )
            manifest = json.loads((result.package_root / "manifest.json").read_text(encoding="utf-8"))
            self.assertIn(
                "character/model/1_pc/1_phm/weapon/2_twohandweapon/cd_phm_02_sword_0015.pac",
                {item["path"] for item in manifest["files"]},
            )

    def test_ui_source_exposes_dialog_and_uses_retrofit_helper(self) -> None:
        source = Path("cdmw/ui/main_window.py").read_text(encoding="utf-8")

        self.assertIn("Retrofit Packaged Mods...", source)
        self.assertIn("QTableWidget(0, 11)", source)
        self.assertIn("RETROFIT_MANAGER_PROFILES", source)
        self.assertIn("MOD_PACKAGE_MANAGER_PROFILE_LABELS", source)
        self.assertIn("manager_combo.addItem", source)
        self.assertIn("archive_entries_by_basename=self.archive_entries_by_basename", source)
        self.assertIn("build_retrofit_path_repair_summary", source)
        self.assertIn("Merge Selected for CDUMM", source)
        self.assertIn("merge_retrofittable_mod_packages", source)
        self.assertIn("scan_retrofittable_mod_packages(source)", source)


if __name__ == "__main__":
    unittest.main()
