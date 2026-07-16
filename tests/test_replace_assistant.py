from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from cdmw.core.mod_package import mod_package_export_options_for_profiles
from cdmw.core.replace_assistant import (
    build_replace_assistant_archive_index,
    build_replace_assistant_items,
    build_replace_assistant_package,
    match_replace_assistant_original,
)
from cdmw.models import ArchiveEntry, ModPackageInfo, ReplaceAssistantBuildOptions, ReplaceAssistantItem


ROUTED_VPATH = "character/texture/sample.dds"
PACKAGE_VPATH = f"0009/{ROUTED_VPATH}"


def _archive_entry(root: Path) -> ArchiveEntry:
    pamt_path = root / "game" / "0009" / "0.pamt"
    pamt_path.parent.mkdir(parents=True, exist_ok=True)
    return ArchiveEntry(
        path=ROUTED_VPATH,
        pamt_path=pamt_path,
        paz_file=pamt_path.with_suffix(".paz"),
        offset=0,
        comp_size=1,
        orig_size=1,
        flags=0,
        paz_index=0,
    )


def _write_dds(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"DDS ")
    return path


def _build_options(output_parent: Path) -> ReplaceAssistantBuildOptions:
    return ReplaceAssistantBuildOptions(
        package_output_root=output_parent,
        overwrite_existing_package_files=True,
        create_no_encrypt_file=True,
        build_mode="rebuild_only",
        size_mode="match_original",
        ncnn_exe_path=None,
        ncnn_model_dir=None,
        ncnn_model_name="",
        ncnn_scale=4,
        ncnn_tile_size=0,
        ncnn_extra_args="",
        retry_smaller_tile_on_failure=False,
        upscale_post_correction_mode="none",
        upscale_texture_preset="all",
        enable_automatic_texture_rules=False,
        enable_unsafe_technical_override=False,
        package_info=ModPackageInfo(title="Routed"),
        export_options=mod_package_export_options_for_profiles(
            ("dmm", "cdumm", "crimson_sharp", "jmm", "field_json")
        ),
    )


class ReplaceAssistantMatchingTests(unittest.TestCase):
    def test_edited_dds_cannot_match_itself_and_stays_unresolved(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            original_root = Path(temp_dir) / "originals"
            source = _write_dds(original_root / PACKAGE_VPATH)
            archive_index = build_replace_assistant_archive_index((), original_dds_root=original_root)

            matched = match_replace_assistant_original(source, archive_index)
            item = build_replace_assistant_items((source,), archive_index=archive_index)[0]

            self.assertIsNone(matched.original_dds_path)
            self.assertIsNone(matched.archive_entry)
            self.assertEqual("", matched.package_root)
            self.assertEqual("", matched.archive_relative_path)
            self.assertEqual("Choose Archive Original.", matched.match_reason)
            self.assertEqual("unresolved", item.status)
            self.assertIsNone(item.matched_original)
            self.assertEqual("", item.detected_package_root)
            self.assertEqual("", item.detected_relative_path)
            self.assertEqual("Choose Archive Original.", item.status_detail)

    def test_self_rejection_continues_to_distinct_local_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            original_root = Path(temp_dir) / "originals"
            source = _write_dds(original_root / PACKAGE_VPATH)
            distinct = _write_dds(original_root / "0010" / "object" / "texture" / source.name)

            matched = match_replace_assistant_original(
                source,
                build_replace_assistant_archive_index((), original_dds_root=original_root),
            )

            self.assertEqual(distinct.resolve(), matched.original_dds_path)
            self.assertEqual("0010", matched.package_root)
            self.assertEqual("object/texture/sample.dds", matched.archive_relative_path)

    def test_self_rejection_continues_to_archive_and_keeps_authoritative_route(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            original_root = root / "originals"
            source = _write_dds(original_root / PACKAGE_VPATH)
            entry = _archive_entry(root)

            matched = match_replace_assistant_original(
                source,
                build_replace_assistant_archive_index((entry,), original_dds_root=original_root),
            )

            self.assertIs(entry, matched.archive_entry)
            self.assertIsNone(matched.original_dds_path)
            self.assertEqual("0009", matched.package_root)
            self.assertEqual(ROUTED_VPATH, matched.archive_relative_path)
            self.assertEqual(PACKAGE_VPATH, matched.loose_relative_path.as_posix())

    def test_distinct_local_match_with_same_virtual_path_remains_valid(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            original_root = root / "originals"
            original = _write_dds(original_root / PACKAGE_VPATH)
            edited = _write_dds(root / "edits" / PACKAGE_VPATH)
            archive_index = build_replace_assistant_archive_index((), original_dds_root=original_root)

            item = build_replace_assistant_items((edited,), archive_index=archive_index)[0]

            self.assertEqual("matched", item.status)
            self.assertIsNotNone(item.matched_original)
            assert item.matched_original is not None
            self.assertEqual(original.resolve(), item.matched_original.original_dds_path)
            self.assertNotEqual(edited.resolve(), item.matched_original.original_dds_path)
            self.assertEqual(item.detected_relative_path, item.matched_original.archive_relative_path)

    def test_authoritative_route_is_preserved_for_all_manager_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            original_root = root / "originals"
            source = _write_dds(original_root / PACKAGE_VPATH)
            entry = _archive_entry(root)
            matched = match_replace_assistant_original(
                source,
                build_replace_assistant_archive_index((entry,), original_dds_root=original_root),
            )
            item = ReplaceAssistantItem(
                source_path=source,
                source_kind="dds",
                detected_relative_path=matched.archive_relative_path,
                detected_package_root=matched.package_root,
                matched_original=matched,
                status="matched",
                status_detail=matched.match_reason,
            )
            extracted_original = _write_dds(root / "archive_original.dds")

            def encode(_source: Path, output: Path, **_kwargs: object) -> dict[str, str]:
                _write_dds(output)
                return {"backend": "test"}

            with (
                patch("cdmw.core.replace_assistant.ensure_archive_preview_source", return_value=(extracted_original, "")),
                patch(
                    "cdmw.core.replace_assistant.parse_dds",
                    return_value=SimpleNamespace(width=4, height=4, dds_format="BC7_UNORM"),
                ),
                patch("cdmw.core.replace_assistant._prepare_processing_png", return_value=root / "processed.png"),
                patch("cdmw.core.replace_assistant.read_png_dimensions", return_value=(4, 4)),
                patch("cdmw.core.replace_assistant.encode_dds_with_directxtex", side_effect=encode),
            ):
                summary = build_replace_assistant_package(
                    (item,),
                    _build_options(root / "out"),
                    archive_entries=(entry,),
                    original_dds_root=original_root,
                )

            package_roots = {
                profile: root / "out" / f"Routed_{profile}"
                for profile in ("dmm", "cdumm", "crimson_sharp", "jmm", "field_json")
            }
            routed_path = Path(ROUTED_VPATH)
            self.assertEqual(package_roots["dmm"], summary.output_root)
            self.assertEqual(1, summary.built_items)
            self.assertEqual(0, summary.unresolved_items)
            self.assertEqual(PACKAGE_VPATH, summary.review_items[0].relative_path.as_posix())
            self.assertTrue((package_roots["dmm"] / routed_path).is_file())
            self.assertTrue((package_roots["cdumm"] / "files" / routed_path).is_file())
            self.assertTrue((package_roots["crimson_sharp"] / "files" / routed_path).is_file())
            self.assertTrue((package_roots["jmm"] / routed_path).is_file())
            self.assertTrue((package_roots["field_json"] / "assets" / routed_path).is_file())

            jmm_manifest = json.loads((package_roots["jmm"] / "mod.json").read_text(encoding="utf-8"))
            self.assertEqual(ROUTED_VPATH, jmm_manifest["target"])
            self.assertEqual([ROUTED_VPATH], jmm_manifest["files"])
            field_manifest = json.loads(
                (package_roots["field_json"] / "mod.field.json").read_text(encoding="utf-8")
            )
            self.assertEqual(ROUTED_VPATH, field_manifest["targets"][0]["file"].removeprefix("assets/"))
            self.assertEqual(f"/{ROUTED_VPATH}", field_manifest["targets"][0]["vpath"])
            for package_root in package_roots.values():
                self.assertFalse((package_root / source.name).exists())


if __name__ == "__main__":
    unittest.main()
