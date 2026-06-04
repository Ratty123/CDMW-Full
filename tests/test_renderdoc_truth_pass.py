from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from cdmw.rendering.renderdoc_truth_pass import normalize_renderdoc_truth_pass
from tools.import_renderdoc_truth_pass import main


class RenderDocTruthPassTests(unittest.TestCase):
    def test_normalizes_capture_truth_with_capture_authority(self) -> None:
        report = normalize_renderdoc_truth_pass(
            {
                "material_name": "Blade",
                "shader_family": "SkinnedMeshStandard_Ver2",
                "srv_slots": [
                    {
                        "slot": 3,
                        "parameter_name": "_colorBlendingMaskTexture",
                        "resource_path": "character/texture/blade_ma.dds",
                        "format": "BC7_UNORM",
                        "srgb_view": False,
                        "hlsl_bind": "t3,space1",
                        "source": "shader_reflection",
                    }
                ],
                "samplers": [{"slot": 0, "filter": "anisotropic", "address_u": "wrap", "address_v": "wrap", "hlsl_bind": "s0,space1"}],
                "constant_buffers": [{"slot": 0, "name": "Material", "hlsl_bind": "cb0,space1", "variables": [{"name": "roughness", "value": 0.5}]}],
                "vertex_shader": {"hash": "vs", "model": "DXIL", "bytecode_length": 128, "blob_id": 7},
                "pixel_shader": {"hash": "abc", "model": "ps_5_0", "bytecode_length": 256, "blob_id": 8, "disassembly": "sample_indexable(texture2d)"},
                "pipeline_state": 22,
                "root_signature": 33,
                "index_count": 123,
                "normal_y_mode": "inverted",
                "blend_state": {"alpha_to_coverage": False},
                "raster_state": {"cull": "back"},
                "depth_stencil_state": {"depth_enable": True},
                "render_target_formats": ["DXGI_FORMAT_R16G16B16A16_FLOAT"],
            }
        )

        self.assertEqual("capture_imported", report["status"])
        srv = report["srv_slots"][0]
        self.assertEqual("capture_inferred", srv["registry_decode"]["authority"])
        self.assertEqual({"ao": "r", "roughness": "g", "metalness": "b"}, srv["registry_decode"]["promoted_channels"])
        self.assertIn("capture inferred crimson_color_blending_mask at SRV 3", report["findings"])
        self.assertEqual("t3,space1", srv["hlsl_bind"])
        self.assertEqual("s0,space1", report["sampler_states"][0]["hlsl_bind"])
        self.assertEqual("cb0,space1", report["constant_buffers"][0]["hlsl_bind"])
        self.assertEqual(False, report["texture_srgb_views"][0]["srgb_view"])
        self.assertEqual(22, report["pipeline_state"])
        self.assertEqual(128, report["vertex_shader"]["bytecode_length"])
        self.assertEqual(256, report["pixel_shader"]["bytecode_length"])
        self.assertEqual(["DXGI_FORMAT_R16G16B16A16_FLOAT"], report["render_target_formats"])

    def test_preserves_shader_blob_manifest_fields(self) -> None:
        report = normalize_renderdoc_truth_pass(
            {
                "material_name": "Draw",
                "vertex_shader": {"sha256": "vs-hash", "blob_path": "vs.dxil", "dxbc_parts": [{"tag": "DXIL"}]},
                "pixel_shader": {
                    "sha256": "ps-hash",
                    "blob_path": "ps.dxil",
                    "container_kind": "DXBC",
                    "shader_ir": "DXIL",
                    "dxbc_parts": [{"tag": "DXIL", "size": 8}],
                    "resource_bindings": [{"name": "Tex", "type": "texture"}],
                    "handle_creates": [{"space": 7, "class": "srv", "is_unbounded": True}],
                    "disassembly_path": "ps.asm",
                    "disassembly_status": "ok",
                },
                "blend_state": {"alpha_to_coverage": False},
                "raster_state": {"cull_mode": "none"},
            }
        )

        self.assertEqual("vs-hash", report["vertex_shader"]["hash"])
        self.assertEqual("ps-hash", report["pixel_shader"]["sha256"])
        self.assertEqual("ps.dxil", report["pixel_shader"]["blob_path"])
        self.assertEqual("DXIL", report["pixel_shader"]["dxbc_parts"][0]["tag"])
        self.assertEqual("Tex", report["pixel_shader"]["resource_bindings"][0]["name"])
        self.assertEqual(7, report["pixel_shader"]["handle_creates"][0]["space"])
        self.assertNotIn("no pixel shader disassembly supplied", report["findings"])

    def test_infers_srgb_view_from_dxgi_format_and_preserves_descriptor_ids(self) -> None:
        report = normalize_renderdoc_truth_pass(
            {
                "material_name": "Draw",
                "srv_slots": [
                    {
                        "slot": 0,
                        "name": "root_5_descriptor_20",
                        "format": "DXGI_FORMAT_BC1_UNORM_SRGB",
                        "resource": 99,
                        "heap": 7,
                        "index": 20,
                        "root_parameter": 5,
                        "source": "initial_contents_descriptor",
                        "resource_desc": {"width": 1024, "height": 512},
                        "resource_name": "WeaponAlbedo",
                    }
                ],
                "sampler_states": [{"slot": 0, "heap": 7, "index": 21, "root_parameter": 5}],
                "constant_buffers": [{"slot": 0}],
                "pixel_shader": {"disassembly_path": "ps.asm"},
                "blend_state": {"alpha_to_coverage": False},
                "raster_state": {"cull_mode": "back"},
            }
        )

        srv = report["srv_slots"][0]
        self.assertEqual(True, srv["srgb_view"])
        self.assertEqual(99, srv["resource"])
        self.assertEqual(7, srv["heap"])
        self.assertEqual("WeaponAlbedo", srv["resource_name"])
        self.assertEqual(1024, srv["resource_desc"]["width"])
        self.assertEqual(True, report["texture_srgb_views"][0]["srgb_view"])

    def test_preserves_compute_shader_truth(self) -> None:
        report = normalize_renderdoc_truth_pass(
            {
                "material_name": "Dispatch",
                "dispatch_groups": {"x": 8, "y": 4, "z": 1, "total": 32},
                "compute_shader": {
                    "sha256": "cs-hash",
                    "blob_path": "cs.dxil",
                    "shader_ir": "DXIL",
                    "resource_bindings": [{"name": "Tex", "type": "texture"}],
                    "disassembly_path": "cs.asm",
                    "disassembly_status": "ok",
                },
                "constant_buffers": [{"slot": 50, "name": "MaterialConstantBuffer"}],
            }
        )

        self.assertEqual(32, report["dispatch_groups"]["total"])
        self.assertEqual("cs-hash", report["compute_shader"]["sha256"])
        self.assertEqual("Tex", report["compute_shader"]["resource_bindings"][0]["name"])
        self.assertNotIn("no pixel shader disassembly supplied", report["findings"])
        self.assertNotIn("blend state unresolved", report["findings"])
        self.assertNotIn("raster state unresolved", report["findings"])

    def test_cli_writes_summary_and_capture_reports(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            capture = root / "capture.json"
            capture.write_text(
                json.dumps(
                    {
                        "material_name": "Hair",
                        "shader_family": "SkinnedMeshHairStandard",
                        "srv_slots": [{"slot": 5, "parameter_name": "_ssdmHairDirectionTexture", "resource_path": "hair_dir.dds"}],
                    }
                ),
                encoding="utf-8",
            )
            out_json = root / "truth.json"

            self.assertEqual(0, main(["--capture-json", str(capture), "--out-json", str(out_json)]))
            report = json.loads(out_json.read_text(encoding="utf-8"))

        self.assertEqual(1, report["summary"]["capture_count"])
        self.assertEqual("hair", report["summary"]["shader_families"][0])
        self.assertEqual("layer_direction", report["captures"][0]["srv_slots"][0]["registry_decode"]["disposition"])

    def test_cli_accepts_repeated_capture_json_flags(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = root / "first.json"
            second = root / "second.json"
            out_json = root / "truth.json"
            first.write_text(json.dumps({"material_name": "A"}), encoding="utf-8")
            second.write_text(json.dumps({"material_name": "B"}), encoding="utf-8")

            self.assertEqual(
                0,
                main(
                    [
                        "--capture-json",
                        str(first),
                        "--capture-json",
                        str(second),
                        "--out-json",
                        str(out_json),
                    ]
                ),
            )
            report = json.loads(out_json.read_text(encoding="utf-8"))

        self.assertEqual(2, report["summary"]["capture_count"])


if __name__ == "__main__":
    unittest.main()
