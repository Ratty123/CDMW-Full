from __future__ import annotations

import json
from pathlib import Path
import struct
import tempfile
import unittest

from PySide6.QtGui import QColor, QImage

from tests.native_source_text import texture_dx_source

from cdmw.models import (
    ClothPreviewBatch,
    ClothPreviewConstraint,
    ClothPreviewData,
    HkxPhysicsOverlayData,
    HkxPhysicsOverlayBone,
    HkxPhysicsOverlayShape,
    ModelPreviewData,
    ModelPreviewMesh,
    ModelPreviewRenderSettings,
    PbdMaterialSettings,
    PreparedModelPreviewBatch,
    PreparedModelPreviewData,
    PreviewMaterialParameterInput,
    PreviewMaterialTextureInput,
)
from cdmw.core.texture_native import write_native_texture_report_sidecar
from cdmw.rendering.native_preview_payloads import ISOLATED_PREVIEW_VERTEX_STRIDE_BYTES
from cdmw.rendering.native_preview_material_contract import _material_hex_color_rgb
from cdmw.rendering.native_preview_material_contract import (
    sidecar_preview_texture_tint_for_batch,
)
from cdmw.workers.d3d11_package_workers import AlignmentD3D11PackageWorker


def _archive_d3d11_ui_source() -> str:
    return "\n".join(
        (
            Path("cdmw/ui/shell/app_window.py").read_text(encoding="utf-8"),
            Path("cdmw/ui/shell/settings_persistence.py").read_text(encoding="utf-8"),
            Path("cdmw/ui/shell/window_runtime_state.py").read_text(encoding="utf-8"),
            Path("cdmw/ui/archive_browser/preview_layout.py").read_text(encoding="utf-8"),
            Path("cdmw/ui/archive_browser/preview_result.py").read_text(encoding="utf-8"),
            Path("cdmw/ui/archive_browser/preview_cache.py").read_text(encoding="utf-8"),
            Path("cdmw/ui/archive_browser/preview_d3d11_parts.py").read_text(encoding="utf-8"),
            Path("cdmw/ui/archive_browser/preview_d3d11_process.py").read_text(encoding="utf-8"),
            Path("cdmw/ui/archive_browser/preview_d3d11_runtime.py").read_text(encoding="utf-8"),
            Path("cdmw/ui/archive_browser/preview_d3d11_worker.py").read_text(encoding="utf-8"),
            Path("cdmw/ui/archive_browser/preview_settings.py").read_text(encoding="utf-8"),
            Path("cdmw/workers/d3d11_package_workers.py").read_text(encoding="utf-8"),
        )
    )


def _vertex(
    x: float,
    y: float,
    z: float,
    *,
    color: tuple[float, float, float] = (0.25, 0.50, 0.75),
    uv: tuple[float, float] = (0.0, 0.0),
) -> bytes:
    return struct.pack(
        "<23f",
        x,
        y,
        z,
        0.0,
        0.0,
        1.0,
        color[0],
        color[1],
        color[2],
        uv[0],
        uv[1],
        1.0,
        0.0,
        0.0,
        0.0,
        1.0,
        0.0,
        0.0,
        0.0,
        1.0,
        1.0,
        0.0,
        0.0,
    )


def _minimal_bc_dds(fourcc: bytes = b"DXT1") -> bytes:
    header = bytearray(124)
    header[0:4] = (124).to_bytes(4, "little")
    header[4:8] = (0x0002100F).to_bytes(4, "little")
    header[8:12] = (4).to_bytes(4, "little")
    header[12:16] = (4).to_bytes(4, "little")
    header[24:28] = (1).to_bytes(4, "little")
    header[72:76] = (32).to_bytes(4, "little")
    header[76:80] = (0x4).to_bytes(4, "little")
    header[80:84] = fourcc
    block_size = 8 if fourcc == b"DXT1" else 16
    return b"DDS " + bytes(header) + (b"\0" * block_size)


class IsolatedD3D11PreviewPackageTests(unittest.TestCase):
    def test_alignment_worker_splices_native_archive_reference_batches(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target_dir = root / "target"
            native_dir = root / "native"
            (target_dir / "geometry").mkdir(parents=True)
            (native_dir / "geometry").mkdir(parents=True)
            (native_dir / "textures").mkdir(parents=True)
            (target_dir / "geometry" / "old.bin").write_bytes(b"old")
            (target_dir / "geometry" / "replacement.bin").write_bytes(b"replacement")
            (native_dir / "geometry" / "native.bin").write_bytes(b"native")
            (native_dir / "geometry" / "native_identity.bin").write_bytes(b"identity")
            (native_dir / "textures" / "native_base.png").write_bytes(b"png")
            (native_dir / "textures" / "native_base.dds").write_bytes(_minimal_bc_dds())
            (native_dir / "textures" / "native_layer.dds").write_bytes(_minimal_bc_dds())
            (native_dir / "textures" / "native_mask.dds").write_bytes(_minimal_bc_dds())
            (native_dir / "textures" / "native_layer_ma.dds").write_bytes(_minimal_bc_dds())
            (target_dir / "manifest.json").write_text(
                json.dumps(
                    {
                        "batches": [
                            {
                                "vertex_file": "geometry/old.bin",
                                "editor_role": "original_reference",
                                "material_name": "Old",
                                "vertex_count": 1,
                                "face_count": 1,
                            },
                            {
                                "vertex_file": "geometry/replacement.bin",
                                "editor_role": "replacement_preview",
                                "material_name": "Replacement",
                                "vertex_count": 2,
                                "face_count": 1,
                            },
                        ],
                        "batch_count": 2,
                        "mesh_count": 2,
                    }
                ),
                encoding="utf-8",
            )
            (native_dir / "manifest.json").write_text(
                json.dumps(
                    {
                        "batches": [
                            {
                                "vertex_file": "geometry/native.bin",
                                "editor_identity": {"identity_file": "geometry/native_identity.bin"},
                                "textures": {"base": "textures/native_base.png"},
                                "dds_textures": {"base": {"source_path": "textures/native_base.dds"}},
                                "material_layers": [
                                    {
                                        "layer_role": "detail",
                                        "diffuse_source": "textures/native_layer.dds",
                                        "mask_source": "textures/native_mask.dds",
                                        "material_source": "textures/native_layer_ma.dds",
                                    }
                                ],
                                "primary_material_layer": {
                                    "layer_role": "detail",
                                    "diffuse_source": "textures/native_layer.dds",
                                },
                                "material_name": "NativeBlade",
                                "texture_name": "NativeTexture",
                                "vertex_count": 3,
                                "face_count": 1,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            replaced = AlignmentD3D11PackageWorker._replace_original_reference_with_native_package(
                target_dir,
                native_dir,
            )
            manifest = json.loads((target_dir / "manifest.json").read_text(encoding="utf-8"))
            mirror_dir = root / "mirror"
            (mirror_dir / "geometry").mkdir(parents=True)
            (mirror_dir / "geometry" / "old.bin").write_bytes(b"old")
            (mirror_dir / "geometry" / "replacement.bin").write_bytes(b"replacement")
            (mirror_dir / "manifest.json").write_text(
                json.dumps(
                    {
                        "batches": [
                            {
                                "vertex_file": "geometry/old.bin",
                                "editor_role": "original_reference",
                                "material_name": "Old",
                                "vertex_count": 1,
                                "face_count": 1,
                            },
                            {
                                "vertex_file": "geometry/replacement.bin",
                                "editor_role": "replacement_preview",
                                "material_name": "FallbackReplacement",
                                "vertex_count": 2,
                                "face_count": 1,
                            },
                        ],
                        "batch_count": 2,
                        "mesh_count": 2,
                    }
                ),
                encoding="utf-8",
            )
            mirrored = AlignmentD3D11PackageWorker._replace_original_reference_with_native_package(
                mirror_dir,
                native_dir,
                mirror_replacement_batches=True,
            )
            mirror_manifest = json.loads((mirror_dir / "manifest.json").read_text(encoding="utf-8"))

        self.assertTrue(replaced)
        self.assertEqual("native_preview_core", manifest["original_reference_package_source"])
        self.assertEqual(2, manifest["batch_count"])
        reference_batch, replacement_batch = manifest["batches"]
        self.assertEqual("original_reference", reference_batch["editor_role"])
        self.assertEqual("original_reference", reference_batch["editor_identity"]["role"])
        self.assertFalse(reference_batch["editor_identity"]["editable"])
        self.assertEqual("NativeBlade", reference_batch["material_name"])
        self.assertEqual(str(native_dir / "textures" / "native_base.png"), reference_batch["textures"]["base"])
        self.assertEqual(
            str(native_dir / "textures" / "native_base.dds"),
            reference_batch["dds_textures"]["base"]["source_path"],
        )
        self.assertEqual(
            str(native_dir / "geometry" / "native_identity.bin"),
            reference_batch["editor_identity"]["identity_file"],
        )
        self.assertEqual(
            str(native_dir / "textures" / "native_layer.dds"),
            reference_batch["material_layers"][0]["diffuse_source"],
        )
        self.assertEqual(
            str(native_dir / "textures" / "native_mask.dds"),
            reference_batch["material_layers"][0]["mask_source"],
        )
        self.assertEqual(
            str(native_dir / "textures" / "native_layer_ma.dds"),
            reference_batch["material_layers"][0]["material_source"],
        )
        self.assertEqual(
            str(native_dir / "textures" / "native_layer.dds"),
            reference_batch["primary_material_layer"]["diffuse_source"],
        )
        self.assertEqual("replacement_preview", replacement_batch["editor_role"])
        self.assertEqual("Replacement", replacement_batch["material_name"])
        self.assertTrue(mirrored)
        mirror_reference_batch, mirror_replacement_batch = mirror_manifest["batches"]
        self.assertEqual("NativeBlade", mirror_reference_batch["material_name"])
        self.assertEqual("NativeBlade", mirror_replacement_batch["material_name"])
        self.assertEqual("original_reference", mirror_reference_batch["editor_identity"]["role"])
        self.assertEqual("replacement_preview", mirror_replacement_batch["editor_identity"]["role"])
        self.assertFalse(mirror_reference_batch["editor_identity"]["editable"])
        self.assertTrue(mirror_replacement_batch["editor_identity"]["editable"])
        self.assertEqual(0, mirror_replacement_batch["editor_identity"]["source_submesh_index"])
        self.assertEqual(
            str(native_dir / "textures" / "native_base.dds"),
            mirror_replacement_batch["dds_textures"]["base"]["source_path"],
        )
        worker_source = Path("cdmw/workers/d3d11_package_workers.py").read_text(encoding="utf-8")
        self.assertIn("build_or_lookup_rust_preview_package_from_model(", worker_source)
        self.assertNotIn("original_reference_native_package_dir=", worker_source)




























    def test_material_emissive_hex_color_uses_crimson_rgba_order(self) -> None:
        self.assertEqual((1.0, 0.0, 0.0), _material_hex_color_rgb("#FF0000FF"))
        self.assertEqual((0.0, 0.0, 1.0), _material_hex_color_rgb("#0000FFFF"))
        self.assertEqual((1.0, 1.0, 0.0), _material_hex_color_rgb("#FFFF0000"))
        self.assertEqual((18 / 255.0, 52 / 255.0, 86 / 255.0), _material_hex_color_rgb("#123456"))







    def test_authoritative_pac_handle_layer_dye_tint_stays_masked_not_global(self) -> None:
        batch = PreparedModelPreviewBatch(
            material_name="CD_PHM_02_Handle_0014",
            texture_name="CD_PHM_02_Sword_Handle_0014",
            preview_material_texture_inputs=(
                PreviewMaterialTextureInput(
                    slot_kind="base",
                    parameter_name="_detailDiffuseMaskG",
                    material_name="CD_PHM_02_Handle_0014",
                    shader_family="SkinnedMeshStandard_Ver2",
                    sidecar_kind="pac_xml",
                    owner_slot_index=2,
                    owner_wrapper_item_id="1191",
                    binding_authority="authoritative",
                    binding_disposition="layer_only",
                    source_kind="crimson_layer_color",
                    layer_role="detail",
                    layer_channel="g",
                    material_parameters=(
                        PreviewMaterialParameterInput(
                            parameter_kind="color",
                            parameter_name="_tintColorR",
                            color_value=(0.301961, 0.231373, 0.172549),
                        ),
                        PreviewMaterialParameterInput(
                            parameter_kind="color",
                            parameter_name="_dyeingDetailLayerColorMaskG",
                            color_value=(1.0, 0.733333, 0.501961),
                        ),
                    ),
                ),
            ),
        )

        self.assertEqual(
            (),
            sidecar_preview_texture_tint_for_batch(
                batch,
                source_path="character/model/1_pc/1_phm/weapon/2_twohandweapon/cd_phm_02_sword_0014.pac",
            ),
        )
