from __future__ import annotations

from pathlib import Path
import struct
import tempfile
import unittest
from unittest import mock

from cdmw.rendering.asset_fidelity_preflight import (
    asset_fidelity_preflight_manifest,
    dds_encoder_compatibility_matrix,
    image_color_preflight_report,
    normal_y_policy_report,
    renderdoc_truth_pass_report,
    shader_truth_capture_backend_report,
    tangent_basis_report,
)


class AssetFidelityPreflightTests(unittest.TestCase):
    def test_image_preflight_detects_openimageio_console_script_beside_python(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            scripts = Path(temp_dir) / "Scripts"
            scripts.mkdir()
            python = scripts / "python.exe"
            helper = scripts / "oiiotool.exe"
            python.write_text("", encoding="utf-8")
            helper.write_text("", encoding="utf-8")
            with (
                mock.patch("cdmw.rendering.asset_fidelity_preflight.sys.executable", str(python)),
                mock.patch.dict("os.environ", {"PATH": "", "PATHEXT": ".EXE;.BAT;.CMD"}),
            ):
                report = image_color_preflight_report()

        openimageio = report["backends"]["OpenImageIO"]
        self.assertEqual("python_console_script_detected", openimageio["status"])
        self.assertEqual(str(helper), openimageio["path"])
        self.assertEqual("optional_source_image_io_and_parity_diagnostics", openimageio["role"])

    def test_dds_encoder_matrix_keeps_directxtex_as_writer_authority(self) -> None:
        matrix = dds_encoder_compatibility_matrix()

        self.assertEqual(1, matrix["schema_version"])
        self.assertEqual("bundled", matrix["backends"]["DirectXTex"]["status"])
        self.assertEqual("dds_writer_authority", matrix["backends"]["DirectXTex"]["role"])
        self.assertEqual("not_bundled", matrix["backends"]["Compressonator"]["bundled_feasibility"])
        self.assertEqual("not_bundled", matrix["backends"]["NVTT"]["bundled_feasibility"])
        self.assertEqual("not_bundled", matrix["backends"]["ISPC Texture Compressor"]["bundled_feasibility"])
        self.assertEqual("not_bundled", matrix["backends"]["bc7enc_rdo"]["bundled_feasibility"])

    def test_tangent_report_marks_mikktspace_native_helper_as_active(self) -> None:
        report = tangent_basis_report()

        self.assertEqual("MikkTSpace", report["active"])
        self.assertEqual("bundled", report["paths"]["cdmw_fallback"]["status"])
        self.assertIn("legacy", report["paths"]["cdmw_fallback"]["role"])
        self.assertIn("mirrored-UV handedness", report["paths"]["cdmw_fallback"]["notes"])
        self.assertEqual("bundled_native_helper", report["paths"]["MikkTSpace"]["status"])
        self.assertTrue(report["paths"]["MikkTSpace"]["package_safe"])
        self.assertIn("face-corner", report["paths"]["MikkTSpace"]["notes"])

    def test_manifest_includes_health_report_fields(self) -> None:
        manifest = asset_fidelity_preflight_manifest(
            {
                "vertex_count": 3,
                "face_count": 1,
                "batches": [
                    {"index": 0, "has_texture_coordinates": False, "tangents_usable": False},
                ],
            }
        )

        self.assertIn("dds_encoder_matrix", manifest)
        self.assertEqual(1, manifest["mesh_health"]["missing_uv_batches"])
        self.assertEqual(1, manifest["mesh_health"]["missing_tangent_batches"])
        self.assertEqual("green_up_asset_inverted_for_directx_preview", manifest["normal_y_policy"]["normal_y_mode"])
        self.assertEqual("checklist_only", manifest["renderdoc_truth_pass"]["status"])
        self.assertIn("capture_backends", manifest["renderdoc_truth_pass"])
        self.assertEqual("registry_covered", manifest["shader_asset_fidelity_status"]["status"])

    def test_normal_y_report_records_force_modes_without_changing_archive_policy(self) -> None:
        report = normal_y_policy_report("force_no_flip")

        self.assertEqual("green_up_asset_inverted_for_directx_preview", report["normal_y_mode"])
        self.assertEqual("green_up", report["archive_source_normal_space"])
        self.assertEqual("force_no_flip", report["d3d11_normal_y_mode"])
        self.assertEqual("force_preserve_normal_y", report["effective_preview_policy"])
        self.assertEqual("unavailable_ags_replay_blocked", report["renderdoc_authority"])

    def test_renderdoc_truth_report_surfaces_current_capture_gaps(self) -> None:
        report = renderdoc_truth_pass_report()

        self.assertEqual("checklist_only", report["status"])
        self.assertEqual("ags_replay_blocked_for_current_crimson_capture", report["replay_status"])
        self.assertTrue(any(".dds names" in item for item in report["current_truth_gaps"]))
        self.assertTrue(any("normal-Y truth unresolved" in item for item in report["current_truth_gaps"]))

    def test_shader_fidelity_status_counts_unknown_crimson_maps_as_diagnostics(self) -> None:
        manifest = asset_fidelity_preflight_manifest(
            {
                "d3d11_normal_y_mode": "asset",
                "batches": [
                    {
                        "index": 3,
                        "material_contract": {
                            "slot_diagnostics": [
                                {
                                    "slot": "base",
                                    "status": "direct_dds",
                                    "authority": "authoritative",
                                    "source_kind": "crimson_overlay_color",
                                    "disposition": "promoted",
                                }
                            ],
                            "registry_decodes": [
                                {
                                    "slot": "material",
                                    "authority": "guess",
                                    "source_kind": "unknown_crimson_texture",
                                    "disposition": "diagnostic_only",
                                    "parameter_name": "_mysteryPackedTexture",
                                    "source_dds_path": "unknown_ma.dds",
                                }
                            ],
                        },
                        "material_channel_contract": {
                            "unresolved": [
                                {
                                    "slot": "material",
                                    "authority": "guess",
                                    "source_kind": "unknown_crimson_texture",
                                    "disposition": "diagnostic_only",
                                    "parameter_name": "_mysteryPackedTexture",
                                    "source_dds_path": "unknown_ma.dds",
                                }
                            ]
                        },
                    }
                ],
            }
        )

        status = manifest["shader_asset_fidelity_status"]
        self.assertEqual("needs_capture_truth", status["status"])
        self.assertEqual("unresolved_diagnostic", status["unknown_crimson_map_policy"])
        self.assertGreaterEqual(status["unknown_crimson_map_count"], 1)
        self.assertGreaterEqual(status["diagnostic_only_count"], 1)
        self.assertGreaterEqual(status["authority_counts"]["guess"], 1)
        self.assertIn("Unknown Crimson packed maps:", " ".join(status["ui_summary"]))

    def test_shader_truth_capture_report_records_renderdoc_amd_probe_notes(self) -> None:
        report = shader_truth_capture_backend_report()

        self.assertIn("RenderDoc", report["backends"])
        renderdoc = report["backends"]["RenderDoc"]
        self.assertIn("AMD.ags.AllowUnknownExtensions", " ".join(renderdoc["crimson_desert_notes"]))
        self.assertEqual("dxcompiler.dll", renderdoc["shader_disassembly"]["backend"])
        self.assertIn("PIX", report["backends"])
        self.assertEqual("not_bundled", report["backends"]["PIX"]["bundled_feasibility"])

    def test_mesh_health_reads_vertex_blob_for_degenerate_and_weld_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_dir = Path(temp_dir)
            geometry = package_dir / "geometry.bin"
            vertex = struct.Struct("<23f")
            one = (0.0, 0.0, 0.0, 0.0, 0.0, 1.0, *([0.0] * 17))
            two = (0.0, 0.0, 0.0, 0.0, 0.0, 1.0, *([0.0] * 17))
            three = (0.0, 0.0, 0.0, 0.0, 0.0, 1.0, *([0.0] * 17))
            geometry.write_bytes(vertex.pack(*one) + vertex.pack(*two) + vertex.pack(*three))

            manifest = asset_fidelity_preflight_manifest(
                {
                    "vertex_count": 3,
                    "face_count": 1,
                    "batches": [
                        {
                            "index": 0,
                            "vertex_file": "geometry.bin",
                            "vertex_offset": 0,
                            "vertex_size": geometry.stat().st_size,
                            "has_texture_coordinates": True,
                            "tangents_usable": True,
                        }
                    ],
                },
                package_dir=package_dir,
            )

        self.assertEqual(1, manifest["mesh_health"]["degenerate_triangles"])
        self.assertGreaterEqual(manifest["mesh_health"]["duplicate_vertices"], 2)
        self.assertGreaterEqual(manifest["mesh_health"]["weld_candidate_vertices"], 2)


if __name__ == "__main__":
    unittest.main()
