from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace

from cdmw.core.item_icon import patch_existing_loose_mod_with_item_icon


class ItemIconLooseModPatchTests(unittest.TestCase):
    def _target_entry(self) -> SimpleNamespace:
        return SimpleNamespace(pamt_path=Path("C:/games/Crimson Desert/0000/package.pamt"))

    def test_patch_existing_loose_mod_with_manifest_updates_copy_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "SkullLantern_v1"
            payload = root / "character" / "model" / "sample.pac"
            payload.parent.mkdir(parents=True)
            payload.write_bytes(b"model")
            manifest = {
                "format": "v1",
                "kind": "mesh_loose_mod",
                "title": "Skull Lantern",
                "file_count": 1,
                "files": [{"path": "character/model/sample.pac", "format": "pac"}],
                "new_paths": ["ui/texture/icon/itemicon_abyss_artifact.dds"],
            }
            (root / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

            result = patch_existing_loose_mod_with_item_icon(
                root,
                target_path="ui/texture/icon/itemicon_abyss_artifact.dds",
                payload_data=b"DDS icon",
                target_entry=self._target_entry(),
            )

            self.assertEqual(root.parent / "SkullLantern_v1_with_icon", result.output_root)
            self.assertTrue((root / "manifest.json").exists())
            self.assertFalse((root / "ui" / "texture" / "icon" / "itemicon_abyss_artifact.dds").exists())
            self.assertEqual(b"DDS icon", result.icon_path.read_bytes())

            patched_manifest = json.loads((result.output_root / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual("Skull Lantern", patched_manifest.get("title"))
            self.assertEqual(2, patched_manifest.get("file_count"))
            self.assertNotIn("new_paths", patched_manifest)
            paths = [row["path"] for row in patched_manifest["files"]]
            self.assertEqual(1, paths.count("ui/texture/icon/itemicon_abyss_artifact.dds"))
            icon_row = next(row for row in patched_manifest["files"] if row["path"] == "ui/texture/icon/itemicon_abyss_artifact.dds")
            self.assertEqual("dds", icon_row.get("format"))
            self.assertEqual("0000", icon_row.get("package_group"))

    def test_patch_existing_loose_tree_without_manifest_writes_game_relative_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "LooseTree"
            existing = root / "character" / "texture" / "sample.dds"
            existing.parent.mkdir(parents=True)
            existing.write_bytes(b"texture")

            result = patch_existing_loose_mod_with_item_icon(
                root,
                target_path="ui/texture/icon/itemicon_test.dds",
                payload_data=b"DDS icon",
                target_entry=self._target_entry(),
            )

            self.assertEqual(result.output_root / "ui" / "texture" / "icon" / "itemicon_test.dds", result.icon_path)
            self.assertEqual(b"DDS icon", result.icon_path.read_bytes())
            self.assertIsNone(result.manifest_path)

    def test_patch_duplicate_icon_replaces_file_and_manifest_row_once(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "ExistingIconMod"
            icon = root / "ui" / "texture" / "icon" / "itemicon_test.dds"
            icon.parent.mkdir(parents=True)
            icon.write_bytes(b"old")
            manifest = {
                "format": "v1",
                "file_count": 1,
                "files": [
                    {"path": "ui/texture/icon/itemicon_test.dds", "format": "dds", "note": "old"},
                    {"path": "files/ui/texture/icon/itemicon_test.dds", "format": "dds", "note": "duplicate"},
                ],
            }
            (root / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

            result = patch_existing_loose_mod_with_item_icon(
                root,
                target_path="ui/texture/icon/itemicon_test.dds",
                payload_data=b"new",
                target_entry=self._target_entry(),
            )

            self.assertEqual(b"new", result.icon_path.read_bytes())
            patched_manifest = json.loads((result.output_root / "manifest.json").read_text(encoding="utf-8"))
            paths = [row["path"] for row in patched_manifest["files"]]
            self.assertEqual(["ui/texture/icon/itemicon_test.dds"], paths)
            self.assertEqual(1, patched_manifest.get("file_count"))

    def test_patch_skips_stale_source_zip_and_creates_fresh_zip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "ZippedMod"
            payload = root / "character" / "model" / "sample.pac"
            payload.parent.mkdir(parents=True)
            payload.write_bytes(b"model")
            (root / "manifest.json").write_text(json.dumps({"files": []}), encoding="utf-8")
            stale_zip = root / "ZippedMod.zip"
            with zipfile.ZipFile(stale_zip, "w") as archive:
                archive.writestr("stale.txt", "old")

            result = patch_existing_loose_mod_with_item_icon(
                root,
                target_path="ui/texture/icon/itemicon_test.dds",
                payload_data=b"DDS icon",
                target_entry=self._target_entry(),
            )

            self.assertFalse((result.output_root / "ZippedMod.zip").exists())
            self.assertIsNotNone(result.zip_path)
            self.assertTrue(result.zip_path.is_file())
            with zipfile.ZipFile(result.zip_path) as archive:
                names = set(archive.namelist())
            self.assertIn("manifest.json", names)
            self.assertIn("ui/texture/icon/itemicon_test.dds", names)
            self.assertNotIn("ZippedMod.zip", names)
            self.assertNotIn("stale.txt", names)

    def test_manifest_files_wrapper_writes_under_files_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "WrappedMod"
            payload = root / "files" / "character" / "model" / "sample.pac"
            payload.parent.mkdir(parents=True)
            payload.write_bytes(b"model")
            manifest = {
                "format": "v1",
                "structure": "files_wrapper",
                "files_root": "files",
                "file_count": 1,
                "files": [{"path": "character/model/sample.pac", "format": "pac"}],
            }
            (root / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

            result = patch_existing_loose_mod_with_item_icon(
                root,
                target_path="ui/texture/icon/itemicon_wrapped.dds",
                payload_data=b"DDS icon",
                target_entry=self._target_entry(),
            )

            self.assertEqual(
                result.output_root / "files" / "ui" / "texture" / "icon" / "itemicon_wrapped.dds",
                result.icon_path,
            )
            patched_manifest = json.loads((result.output_root / "manifest.json").read_text(encoding="utf-8"))
            paths = [row["path"] for row in patched_manifest["files"]]
            self.assertIn("ui/texture/icon/itemicon_wrapped.dds", paths)


if __name__ == "__main__":
    unittest.main()
