from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools.export_renderdoc_candidate_truth import candidate_to_truth_input, main


class RenderDocCandidateTruthExportTests(unittest.TestCase):
    def test_exports_candidate_pso_state_to_truth_input(self) -> None:
        report = {
            "capture_xml": "frame.zip.xml",
            "candidates": [
                {
                    "rank": 1,
                    "chunk_index": 99,
                    "command_list": 10,
                    "index_count": 1200,
                    "state": {
                        "pipeline_state": 22,
                        "graphics_root_signature": 33,
                        "primitive_topology": "D3D_PRIMITIVE_TOPOLOGY_TRIANGLELIST",
                        "root_cbvs": {"1": {"resource": 44, "offset": 256}},
                    },
                    "pipeline_description": {
                        "shaders": {
                            "VS": {"blob_id": 7, "byte_length": 128},
                            "PS": {"blob_id": 8, "byte_length": 256},
                        },
                        "blend_state": {"rt0": {"blend_enable": False}},
                        "raster_state": {"cull_mode": "D3D12_CULL_MODE_BACK"},
                        "depth_stencil_state": {"depth_enable": True},
                        "rtv_formats": ["DXGI_FORMAT_R16G16B16A16_FLOAT"],
                        "dsv_format": "DXGI_FORMAT_D32_FLOAT",
                    },
                    "root_signature_description": {"blob_length": 64},
                }
            ],
        }

        truth = candidate_to_truth_input(report, rank=1, capture_path="frame.rdc")

        self.assertEqual("draw_99", truth["material_name"])
        self.assertEqual(22, truth["pipeline_state"])
        self.assertEqual(8, truth["pixel_shader"]["blob_id"])
        self.assertEqual(256, truth["pixel_shader"]["bytecode_length"])
        self.assertEqual("DXGI_FORMAT_R16G16B16A16_FLOAT", truth["render_target_formats"][0])
        self.assertEqual(44, truth["constant_buffers"][0]["resource"])
        self.assertTrue(truth["normal_y_mode_unresolved"])

    def test_exports_shader_blob_manifest_metadata(self) -> None:
        report = {
            "candidates": [
                {
                    "rank": 1,
                    "chunk_index": 99,
                    "state": {},
                    "pipeline_description": {
                        "shaders": {
                            "VS": {"blob_id": 7, "byte_length": 128},
                            "PS": {"blob_id": 8, "byte_length": 256},
                        }
                    },
                }
            ],
        }
        manifest = {
            "blobs": [
                {
                    "rank": 1,
                    "chunk_index": 99,
                    "stage": "PS",
                    "blob_id": 8,
                    "sha256": "abc123",
                    "path": "shader.dxil",
                    "container_kind": "DXBC",
                    "shader_ir": "DXIL",
                    "parts": [{"tag": "DXIL", "size": 12}],
                    "resource_bindings": [
                        {
                            "name": "__x__BaseTexture",
                            "type": "texture",
                            "format": "f32",
                            "dim": "2d",
                            "id": "T0",
                            "hlsl_bind": "t15,space36",
                            "register": 15,
                            "space": 36,
                            "count": 1,
                        },
                        {
                            "name": "__x__Sampler",
                            "type": "sampler",
                            "format": "NA",
                            "dim": "NA",
                            "id": "S0",
                            "hlsl_bind": "s8,space95",
                            "register": 8,
                            "space": 95,
                            "count": 1,
                        },
                        {
                            "name": "__x__Material",
                            "type": "cbuffer",
                            "format": "NA",
                            "dim": "NA",
                            "id": "CB0",
                            "hlsl_bind": "cb20,space35",
                            "register": 20,
                            "space": 35,
                            "count": 1,
                        },
                    ],
                    "handle_creates": [{"space": 7, "class": "srv", "is_unbounded": True}],
                    "disassembly_path": "shader.asm",
                    "disassembly_status": "ok",
                }
            ]
        }

        truth = candidate_to_truth_input(report, rank=1, shader_blob_manifest=manifest)

        self.assertEqual("abc123", truth["pixel_shader"]["sha256"])
        self.assertEqual("shader.dxil", truth["pixel_shader"]["blob_path"])
        self.assertEqual("DXIL", truth["pixel_shader"]["dxbc_parts"][0]["tag"])
        self.assertEqual(7, truth["pixel_shader"]["handle_creates"][0]["space"])
        self.assertEqual("t15,space36", truth["srv_slots"][0]["hlsl_bind"])
        self.assertEqual("s8,space95", truth["sampler_states"][0]["hlsl_bind"])
        self.assertEqual("cb20,space35", truth["constant_buffers"][0]["hlsl_bind"])
        self.assertEqual("", truth["vertex_shader"].get("sha256", ""))

    def test_exports_compute_shader_manifest_metadata(self) -> None:
        report = {
            "candidates": [
                {
                    "rank": 1,
                    "chunk_index": 77,
                    "dispatch_groups": {"x": 8, "y": 4, "z": 1, "total": 32},
                    "state": {"pipeline_state": 22, "compute_root_signature": 33},
                    "pipeline_description": {"shaders": {"CS": {"blob_id": 9, "byte_length": 512}}},
                }
            ],
        }
        manifest = {
            "blobs": [
                {
                    "rank": 1,
                    "chunk_index": 77,
                    "stage": "CS",
                    "blob_id": 9,
                    "sha256": "cs-hash",
                    "path": "cs.dxil",
                    "shader_ir": "DXIL",
                    "resource_bindings": [
                        {"name": "Tex", "type": "texture", "format": "f32", "dim": "2d", "id": "T0", "hlsl_bind": "t1,space2", "register": 1, "space": 2, "count": 1}
                    ],
                    "disassembly_path": "cs.asm",
                    "disassembly_status": "ok",
                }
            ]
        }

        truth = candidate_to_truth_input(report, rank=1, shader_blob_manifest=manifest)

        self.assertEqual("cs-hash", truth["compute_shader"]["sha256"])
        self.assertEqual(32, truth["dispatch_groups"]["total"])
        self.assertEqual(33, truth["root_signature"])
        self.assertEqual("t1,space2", truth["srv_slots"][0]["hlsl_bind"])

    def test_exports_resolved_descriptor_heap_srvs_and_samplers(self) -> None:
        report = {
            "candidates": [
                {
                    "rank": 1,
                    "chunk_index": 42,
                    "state": {
                        "root_descriptor_tables": {
                            "5": {
                                "descriptors": [
                                    {
                                        "type": "SRV",
                                        "resource": 99,
                                        "heap": 7,
                                        "index": 20,
                                        "format": "DXGI_FORMAT_BC1_UNORM_SRGB",
                                        "view_dimension": "D3D12_SRV_DIMENSION_TEXTURE2D",
                                        "source": "initial_contents_descriptor",
                                        "resource_desc": {"width": 1024, "height": 512, "name": "WeaponAlbedo"},
                                    },
                                    {
                                        "type": "Sampler",
                                        "heap": 7,
                                        "index": 21,
                                        "filter": "D3D12_FILTER_ANISOTROPIC",
                                        "address_u": "D3D12_TEXTURE_ADDRESS_MODE_WRAP",
                                        "address_v": "D3D12_TEXTURE_ADDRESS_MODE_WRAP",
                                        "source": "initial_contents_descriptor",
                                    },
                                    {
                                        "type": "CBV",
                                        "heap": 7,
                                        "index": 22,
                                        "buffer_resource": 44,
                                        "buffer_offset": 128,
                                        "size_in_bytes": 256,
                                        "source": "initial_contents_descriptor",
                                    },
                                ]
                            }
                        }
                    },
                    "pipeline_description": {"shaders": {"VS": {}, "PS": {}}},
                }
            ],
        }

        truth = candidate_to_truth_input(report, rank=1)

        self.assertEqual(99, truth["srv_slots"][0]["resource"])
        self.assertEqual("WeaponAlbedo", truth["srv_slots"][0]["resource_name"])
        self.assertEqual("DXGI_FORMAT_BC1_UNORM_SRGB", truth["srv_slots"][0]["format"])
        self.assertEqual("initial_contents_descriptor", truth["srv_slots"][0]["source"])
        self.assertEqual("D3D12_FILTER_ANISOTROPIC", truth["sampler_states"][0]["filter"])
        self.assertEqual(5, truth["sampler_states"][0]["root_parameter"])
        self.assertEqual(44, truth["constant_buffers"][0]["resource"])
        self.assertEqual(256, truth["constant_buffers"][0]["size_in_bytes"])

    def test_cli_writes_truth_input(self) -> None:
        report = {
            "candidates": [
                {
                    "rank": 1,
                    "chunk_index": 11,
                    "state": {},
                    "pipeline_description": {"shaders": {"VS": {}, "PS": {}}},
                }
            ]
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "candidates.json"
            out = root / "truth_input.json"
            source.write_text(json.dumps(report), encoding="utf-8")

            self.assertEqual(0, main(["--draw-candidates-json", str(source), "--rank", "1", "--out-json", str(out)]))
            payload = json.loads(out.read_text(encoding="utf-8"))

        self.assertEqual("chunk_11", payload["drawcall"])


if __name__ == "__main__":
    unittest.main()
