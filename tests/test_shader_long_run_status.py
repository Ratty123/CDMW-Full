from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools.report_crimson_shader_long_run_status import (
    STATUS_BLOCKED_EXTERNAL,
    STATUS_COMPLETE,
    STATUS_PARTIAL,
    build_status_report,
    main,
)


class ShaderLongRunStatusTests(unittest.TestCase):
    def test_report_marks_capture_as_external_blocker_without_capture(self) -> None:
        report = build_status_report(
            extract_manifest={
                "sidecar_entries_selected": 10,
                "dds_reference_rows": 12,
                "dds_entries_selected": 2,
            },
            audit_summary={"rows": 1000, "dds_rows": 900, "unknown_rows": 1, "families": [["standard_v2", 500]]},
            dds_summary={"dds_files": 2, "fatal_files": 0, "format_counts": [["BC1_UNORM", 2]]},
            material_profile_summary={"material_profile_rows": 4, "pso_rows": 2},
        )

        self.assertEqual("partial", report["overall_status"])
        self.assertIn("renderdoc_truth_pass", report["blocking_items"])
        capture_item = next(item for item in report["plan_items"] if item["name"] == "renderdoc_truth_pass")
        self.assertEqual(STATUS_BLOCKED_EXTERNAL, capture_item["status"])

    def test_report_marks_renderdoc_partial_when_rdc_artifact_exists(self) -> None:
        report = build_status_report(
            extract_manifest={"sidecar_entries_selected": 10},
            audit_summary={"rows": 1000, "unknown_rows": 1},
            dds_summary={"dds_files": 1, "fatal_files": 0},
            material_profile_summary={"material_profile_rows": 4, "pso_rows": 2},
            capture_artifacts=[{"capture_path": "frame.rdc", "thumbnail_path": "thumb.jpg"}],
        )

        self.assertNotIn("renderdoc_truth_pass", report["blocking_items"])
        capture_item = next(item for item in report["plan_items"] if item["name"] == "renderdoc_truth_pass")
        self.assertEqual(STATUS_PARTIAL, capture_item["status"])

    def test_report_marks_capture_complete_when_truth_report_supplied(self) -> None:
        report = build_status_report(
            extract_manifest={"sidecar_entries_selected": 10},
            audit_summary={"rows": 1000, "unknown_rows": 1},
            dds_summary={"dds_files": 1, "fatal_files": 0},
            material_profile_summary={"material_profile_rows": 4, "pso_rows": 2},
            capture_reports=[
                {
                    "schema_version": 1,
                    "material_name": "Blade",
                    "srv_slots": [{"resource_path": "character/blade_ma.dds"}],
                    "sampler_states": [{"slot": 0}],
                    "constant_buffers": [{"slot": 0}],
                    "pixel_shader": {"disassembly_path": "blade.asm"},
                    "texture_srgb_views": [{"resource_path": "character/blade_ma.dds", "srgb_view": False}],
                    "normal_y_mode": "directx",
                    "blend_state": {"rt0": {"blend_enable": False}},
                    "raster_state": {"cull_mode": "back"},
                }
            ],
        )

        capture_item = next(item for item in report["plan_items"] if item["name"] == "renderdoc_truth_pass")
        self.assertEqual(STATUS_COMPLETE, capture_item["status"])

    def test_report_marks_disassembly_only_capture_partial_and_records_bindless_summary(self) -> None:
        report = build_status_report(
            extract_manifest={"sidecar_entries_selected": 10},
            audit_summary={"rows": 1000, "unknown_rows": 1},
            dds_summary={"dds_files": 1, "fatal_files": 0},
            material_profile_summary={"material_profile_rows": 4, "pso_rows": 2},
            shader_binding_summary={
                "blob_count": 2,
                "bindless_spaces": [
                    {
                        "type": "texture",
                        "space": 7,
                        "hlsl_bind": "t0,space7",
                        "shader_count": 1,
                        "names": ["g_bindlessTextures"],
                    }
                ],
                "dynamic_handle_spaces": [{"class": "srv", "space": 7, "handle_create_count": 4}],
                "findings": ["bindless_texture_array_detected"],
            },
            capture_reports=[
                {
                    "schema_version": 1,
                    "captures": [
                        {
                            "material_name": "draw_rank1",
                            "srv_slots": [{"name": "g_bindlessTextures", "source": "shader_reflection"}],
                            "sampler_states": [{"slot": 0, "source": "shader_reflection"}],
                            "constant_buffers": [{"slot": 0, "source": "shader_reflection"}],
                            "pixel_shader": {"disassembly_path": "rank1.asm"},
                            "findings": ["normal Y mode unresolved"],
                        }
                    ],
                }
            ],
        )

        capture_item = next(item for item in report["plan_items"] if item["name"] == "renderdoc_truth_pass")
        self.assertEqual(STATUS_PARTIAL, capture_item["status"])
        self.assertEqual(0, capture_item["evidence"]["capture_quality"]["resolved_srv_resource_paths"])
        binding_item = next(item for item in report["plan_items"] if item["name"] == "renderdoc_shader_binding_summary")
        self.assertEqual(STATUS_COMPLETE, binding_item["status"])
        self.assertEqual(7, binding_item["evidence"]["top_bindless_spaces"][0]["space"])

    def test_report_does_not_count_shader_binding_names_as_resolved_texture_paths(self) -> None:
        report = build_status_report(
            extract_manifest={"sidecar_entries_selected": 10},
            audit_summary={"rows": 1000, "unknown_rows": 1},
            dds_summary={"dds_files": 1, "fatal_files": 0},
            material_profile_summary={"material_profile_rows": 4, "pso_rows": 2},
            capture_reports=[
                {
                    "schema_version": 1,
                    "srv_slots": [{"resource_path": "__0__7__0__0__g_bindlessTextures"}],
                    "sampler_states": [{"slot": 0}],
                    "constant_buffers": [{"slot": 0}],
                    "pixel_shader": {"disassembly_path": "rank1.asm"},
                }
            ],
        )

        capture_item = next(item for item in report["plan_items"] if item["name"] == "renderdoc_truth_pass")
        self.assertEqual(0, capture_item["evidence"]["capture_quality"]["resolved_srv_resource_paths"])

    def test_report_counts_descriptor_heap_resource_id_truth(self) -> None:
        report = build_status_report(
            extract_manifest={"sidecar_entries_selected": 10},
            audit_summary={"rows": 1000, "unknown_rows": 1},
            dds_summary={"dds_files": 1, "fatal_files": 0},
            material_profile_summary={"material_profile_rows": 4, "pso_rows": 2},
            capture_reports=[
                {
                    "schema_version": 1,
                    "srv_slots": [
                        {
                            "resource": "18390",
                            "resource_name": "WeaponAlbedo",
                            "format": "DXGI_FORMAT_BC7_UNORM_SRGB",
                            "source": "initial_contents_descriptor",
                        }
                    ],
                    "sampler_states": [{"slot": 0}],
                    "constant_buffers": [{"slot": 0}],
                    "pixel_shader": {"disassembly_path": "rank1.asm"},
                    "texture_srgb_views": [{"resource": "18390", "srgb_view": True}],
                }
            ],
        )

        capture_item = next(item for item in report["plan_items"] if item["name"] == "renderdoc_truth_pass")
        quality = capture_item["evidence"]["capture_quality"]
        self.assertEqual(1, quality["resolved_srv_resource_ids"])
        self.assertEqual(1, quality["named_srv_resources"])
        self.assertEqual(1, quality["initial_descriptor_srv_count"])
        self.assertEqual(0, quality["resolved_srv_resource_paths"])

    def test_report_includes_dds_correlation_and_normal_y_policy_evidence(self) -> None:
        report = build_status_report(
            extract_manifest={"sidecar_entries_selected": 10},
            audit_summary={"rows": 1000, "unknown_rows": 1},
            dds_summary={"dds_files": 1, "fatal_files": 0},
            material_profile_summary={"material_profile_rows": 4, "pso_rows": 2},
            dds_correlation_summary={
                "dds_count": 4,
                "capture_resource_count": 2,
                "matched_resource_count": 1,
                "unique_high_confidence_count": 1,
                "policy": "metadata correlation",
            },
            normal_y_policy={
                "status": "inferred",
                "normal_y_mode": "green_up_asset_inverted_for_directx_preview",
                "authority": "corpus_and_app_policy_inferred",
                "renderdoc_authority": "unavailable_ags_replay_blocked",
                "audit": {"normal_rows": 12},
            },
        )

        dds_item = next(item for item in report["plan_items"] if item["name"] == "renderdoc_dds_path_correlation")
        normal_item = next(item for item in report["plan_items"] if item["name"] == "normal_y_policy_inference")
        self.assertEqual(STATUS_PARTIAL, dds_item["status"])
        self.assertEqual(STATUS_COMPLETE, normal_item["status"])
        self.assertEqual(1, dds_item["evidence"]["unique_high_confidence_count"])
        self.assertEqual("green_up_asset_inverted_for_directx_preview", normal_item["evidence"]["normal_y_mode"])

    def test_cli_writes_json_and_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            extract = root / "extract.json"
            audit = root / "audit.json"
            dds = root / "dds.json"
            profiles = root / "profiles.json"
            bindings = root / "bindings.json"
            out_json = root / "status.json"
            out_md = root / "status.md"
            extract.write_text(json.dumps({"sidecar_entries_selected": 3}), encoding="utf-8")
            audit.write_text(json.dumps({"rows": 10, "unknown_rows": 0}), encoding="utf-8")
            dds.write_text(json.dumps({"dds_files": 1, "fatal_files": 0}), encoding="utf-8")
            profiles.write_text(json.dumps({"material_profile_rows": 2, "pso_rows": 1}), encoding="utf-8")
            bindings.write_text(json.dumps({"blob_count": 1}), encoding="utf-8")

            exit_code = main(
                [
                    "--extract-manifest",
                    str(extract),
                    "--audit-summary",
                    str(audit),
                    "--dds-summary",
                    str(dds),
                    "--material-profile-summary",
                    str(profiles),
                    "--shader-binding-summary",
                    str(bindings),
                    "--out-json",
                    str(out_json),
                    "--out-md",
                    str(out_md),
                ]
            )

            self.assertEqual(0, exit_code)
            self.assertTrue(out_json.is_file())
            self.assertIn("Crimson Shader Long-Run Status", out_md.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
