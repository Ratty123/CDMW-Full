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
from cdmw.rendering.native_preview_package import (
    ISOLATED_PREVIEW_VERTEX_STRIDE_BYTES,
    _material_hex_color_rgb,
    read_isolated_d3d11_preview_manifest,
    write_isolated_d3d11_preview_package,
)
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
        self.assertIn("build_or_lookup_dotnet_preview_package_from_model(", worker_source)
        self.assertNotIn("original_reference_native_package_dir=", worker_source)

    def test_writes_empty_preview_package(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_dir = write_isolated_d3d11_preview_package(
                ModelPreviewData(path="empty.pac"),
                PreparedModelPreviewData(source_path="empty.pac"),
                output_root=Path(temp_dir) / "package",
            )
            manifest = read_isolated_d3d11_preview_manifest(package_dir)

        self.assertEqual(10, manifest["schema_version"])
        self.assertEqual("empty.pac", manifest["source_path"])
        self.assertEqual(2, manifest["material_contract_schema"])
        self.assertEqual(2, manifest["material_channel_contract_schema"])
        self.assertEqual(1, manifest["texture_quality_schema"])
        self.assertEqual("preserve", manifest["texture_quality_policy"]["technical_map_default"])
        self.assertEqual("lit", manifest["render_diagnostic_mode"])
        self.assertEqual("neutral_studio", manifest["lighting_preset"])
        self.assertEqual("replacement_only", manifest["display_mode"])
        self.assertEqual("", manifest["editor_workspace"])
        self.assertEqual([], manifest["batches"])
        self.assertEqual(0, manifest["cloth_batch_count"])
        self.assertEqual(0, manifest["cloth_particle_count"])
        self.assertEqual(0, manifest["cloth_constraint_count"])
        self.assertEqual(False, manifest["physics_overlays"]["cloth"])
        self.assertEqual("not_found", manifest["skeleton_overlay"]["status"])
        self.assertEqual([], manifest["editable_value_groups"])
        self.assertEqual("bundled", manifest["dds_encoder_matrix"]["backends"]["DirectXTex"]["status"])
        self.assertEqual("not_bundled", manifest["dds_encoder_matrix"]["backends"]["NVTT"]["bundled_feasibility"])
        self.assertEqual("MikkTSpace", manifest["tangent_basis"]["active"])
        self.assertEqual("bundled_native_helper", manifest["tangent_basis"]["paths"]["MikkTSpace"]["status"])
        self.assertEqual("green_up_asset_inverted_for_directx_preview", manifest["normal_y_policy"]["normal_y_mode"])
        self.assertEqual("checklist_only", manifest["renderdoc_truth_pass"]["status"])
        self.assertEqual(
            "ags_replay_blocked_for_current_crimson_capture",
            manifest["renderdoc_truth_pass"]["replay_status"],
        )
        self.assertEqual("registry_covered", manifest["shader_asset_fidelity_status"]["status"])
        self.assertIn("DDS preflight:", " ".join(manifest["shader_asset_fidelity_status"]["ui_summary"]))
        self.assertIn("mesh_health", manifest["asset_fidelity_preflight"])

    def test_alignment_preview_package_writes_placement_frame_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            prepared = PreparedModelPreviewData(
                source_path="sword.pac",
                normalization_center=(0.0, 2.0, 0.0),
                normalization_scale=0.5,
                preview_frame_kind="original_pac_frame",
                preview_frame_source_path="sword.pac",
                preview_grid_origin=(0.0, -1.0, 0.0),
                preview_grid_y=-1.0,
                preview_grid_mode="original_frame",
                preview_material_parity_mode="archive_preview",
                preview_original_materials_preserved=True,
                preview_reference_tint_mode="overlay_only",
            )
            package_dir = write_isolated_d3d11_preview_package(
                ModelPreviewData(path="sword.pac"),
                prepared,
                output_root=Path(temp_dir) / "package",
                display_mode="overlay",
                editor_workspace="mesh_replacement_alignment",
            )
            manifest = read_isolated_d3d11_preview_manifest(package_dir)

        self.assertEqual("preserve", manifest["reference_material_policy"])
        self.assertEqual("original_pac_frame", manifest["placement_frame"]["kind"])
        self.assertEqual("original_frame", manifest["placement_frame"]["grid_mode"])
        self.assertEqual(-1.0, manifest["placement_frame"]["grid_y"])
        self.assertEqual("archive_preview", manifest["placement_frame"]["material_parity"])
        self.assertEqual("overlay_only", manifest["placement_frame"]["reference_tint_mode"])
        self.assertTrue(manifest["placement_frame"]["preserve_original_materials"])

    def test_game_outdoor_d3d11_view_mode_writes_outdoor_lighting_preset(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_dir = write_isolated_d3d11_preview_package(
                ModelPreviewData(path="sword.pac"),
                PreparedModelPreviewData(source_path="sword.pac"),
                output_root=Path(temp_dir) / "package",
                render_settings=ModelPreviewRenderSettings(d3d11_view_mode="game_outdoor"),
            )
            manifest = read_isolated_d3d11_preview_manifest(package_dir)

        self.assertEqual("game_outdoor", manifest["d3d11_view_mode"])
        self.assertEqual("game_outdoor_approx", manifest["lighting_preset"])

    def test_native_material_manifest_overrides_survive_package_write(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            prepared = PreparedModelPreviewData(
                source_path="helmet.pac",
                batches=(
                    PreparedModelPreviewBatch(
                        material_name="helmet_mask",
                        vertex_blob=_vertex(0, 0, 0) + _vertex(1, 0, 0) + _vertex(0, 1, 0),
                        index_count=3,
                        has_texture_coordinates=True,
                        preview_native_material_overrides={
                            "alpha_cutoff": 0.37,
                            "material_category": "metal",
                            "material_category_confidence": 0.95,
                            "roughness": 0.42,
                            "metalness": 0.75,
                            "material_layers": (
                                {
                                    "layer_role": "grime",
                                    "mask_channel": "r",
                                    "diffuse_source": "C:/native/layer.dds",
                                    "mask_source": "C:/native/mask.dds",
                                    "weight": 0.5,
                                },
                            ),
                        },
                    ),
                ),
            )

            package_dir = write_isolated_d3d11_preview_package(
                ModelPreviewData(path="helmet.pac"),
                prepared,
                output_root=temp_path / "package",
                use_textures=False,
            )
            manifest = read_isolated_d3d11_preview_manifest(package_dir)
            batch = manifest["batches"][0]

        self.assertEqual("metal", batch["material_category"])
        self.assertEqual(0.37, batch["alpha_threshold"])
        self.assertNotIn("alpha_cutoff", batch)
        self.assertEqual("glossy_metal", batch["material_finish"])
        self.assertEqual(0.95, batch["material_category_confidence"])
        self.assertEqual(0.42, batch["roughness"])
        self.assertEqual(0.75, batch["metalness"])
        self.assertEqual("grime", batch["material_layers"][0]["layer_role"])
        self.assertIn("native material manifest overrides applied", batch["notes"])

    def test_archive_normal_space_is_explicit_in_native_batch_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            prepared = PreparedModelPreviewData(
                source_path="sword.pac",
                batches=(
                    PreparedModelPreviewBatch(
                        material_name="blade",
                        vertex_blob=_vertex(0, 0, 0) + _vertex(1, 0, 0) + _vertex(0, 1, 0),
                        index_count=3,
                        preview_material_texture_inputs=(
                            PreviewMaterialTextureInput(
                                slot_kind="normal",
                                semantic_type="normal",
                                normal_space="green_up",
                                confidence="resolved",
                            ),
                        ),
                    ),
                ),
            )

            package_dir = write_isolated_d3d11_preview_package(
                ModelPreviewData(path="sword.pac"),
                prepared,
                output_root=Path(temp_dir) / "package",
                use_textures=False,
            )
            manifest = read_isolated_d3d11_preview_manifest(package_dir)

        self.assertEqual("invert_green_for_directx", manifest["batches"][0]["normal_y_policy"])

    def test_cutout_package_preserves_combined_base_alpha(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            base_path = temp_path / "hair_base.png"
            base_image = QImage(2, 1, QImage.Format_RGBA8888)
            base_image.setPixelColor(0, 0, QColor(90, 70, 50, 18))
            base_image.setPixelColor(1, 0, QColor(100, 80, 60, 220))
            self.assertTrue(base_image.save(str(base_path), "PNG"))
            prepared = PreparedModelPreviewData(
                source_path="hair.pac",
                batches=(
                    PreparedModelPreviewBatch(
                        vertex_blob=_vertex(0, 0, 0) + _vertex(1, 0, 0) + _vertex(0, 1, 0),
                        index_count=3,
                        preview_texture_path=str(base_path),
                        preview_alpha_mode="cutout",
                        has_texture_coordinates=True,
                    ),
                ),
            )

            package_dir = write_isolated_d3d11_preview_package(
                ModelPreviewData(path="hair.pac"),
                prepared,
                output_root=temp_path / "package",
            )
            manifest = read_isolated_d3d11_preview_manifest(package_dir)
            batch = manifest["batches"][0]
            packaged_base = QImage(str(package_dir / batch["textures"]["base"]))

        self.assertEqual("cutout", batch["alpha_mode"])
        self.assertEqual(18, packaged_base.pixelColor(0, 0).alpha())
        self.assertEqual(220, packaged_base.pixelColor(1, 0).alpha())
        self.assertIn("base alpha preserved:cutout", batch["notes"])

    def test_writes_tool_side_pbd_cloth_runtime_payloads(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            cloth_batch = ClothPreviewBatch(
                mesh_index=0,
                source_submesh_index=2,
                simulation_material_name="LongHair",
                simulation_kind="hair",
                material_settings=PbdMaterialSettings(
                    material_name="LongHair",
                    simulation_kind="hair",
                    gravity=-8.0,
                    damping=0.25,
                    wind_response=0.7,
                    solver_iterations=9,
                    collision_enabled=True,
                ),
                positions=((0.0, 1.0, 0.0), (0.0, 0.0, 0.0), (1.0, 0.0, 0.0)),
                pin_weights=(1.0, 0.0, 0.0),
                constraints=(
                    ClothPreviewConstraint(kind="structural", a=0, b=1, rest_length=1.0, stiffness=0.6),
                    ClothPreviewConstraint(kind="structural", a=1, b=2, rest_length=1.0, stiffness=0.6),
                ),
            )
            prepared = PreparedModelPreviewData(
                source_path="hair.pac",
                batches=(
                    PreparedModelPreviewBatch(
                        material_name="hair_mat",
                        vertex_blob=_vertex(0, 1, 0) + _vertex(0, 0, 0) + _vertex(1, 0, 0),
                        index_count=3,
                        source_submesh_index=2,
                        source_vertex_indices=(0, 1, 2),
                        cloth_preview=cloth_batch,
                    ),
                ),
                cloth_preview=ClothPreviewData(batches=(cloth_batch,)),
            )
            model = ModelPreviewData(
                path="hair.pac",
                physics_overlay=HkxPhysicsOverlayData(
                    shapes=(
                        HkxPhysicsOverlayShape(
                            center=(0.0, 0.5, 0.0),
                            radius=0.2,
                        ),
                    )
                ),
            )

            package_dir = write_isolated_d3d11_preview_package(
                model,
                prepared,
                output_root=temp_path / "package",
            )
            manifest = read_isolated_d3d11_preview_manifest(package_dir)

            batch = manifest["batches"][0]
            self.assertEqual(1, manifest["cloth_batch_count"])
            self.assertEqual(3, manifest["cloth_particle_count"])
            self.assertEqual(2, manifest["cloth_constraint_count"])
            self.assertEqual(1, manifest["cloth_collider_count"])
            self.assertTrue(manifest["physics_overlays"]["cloth"])
            self.assertEqual(3, manifest["physics_overlays"]["cloth_particle_count"])
            self.assertEqual(1, manifest["physics_overlays"]["physics_shape_count"])
            self.assertEqual(1, manifest["cloth_runtime_debug"]["batch_count"])
            self.assertEqual(3, manifest["cloth_runtime_debug"]["particle_count"])
            self.assertEqual(2, manifest["cloth_runtime_debug"]["constraint_count"])
            self.assertEqual("pbd_cloth", manifest["editable_value_groups"][0]["kind"])
            self.assertTrue(batch["cloth_enabled"])
            self.assertEqual("hair", batch["cloth_kind"])
            self.assertEqual("LongHair", batch["cloth_material_name"])
            self.assertEqual(3, batch["cloth_particle_count"])
            self.assertEqual(2, batch["cloth_constraint_count"])
            self.assertAlmostEqual(-8.0, batch["cloth_gravity"])
            self.assertEqual(9, batch["cloth_solver_iterations"])
            self.assertTrue((package_dir / batch["cloth_particle_file"]).is_file())
            self.assertTrue((package_dir / batch["cloth_pin_file"]).is_file())
            self.assertTrue((package_dir / batch["cloth_constraint_file"]).is_file())
            self.assertEqual(3 * 3 * 4, (package_dir / batch["cloth_particle_file"]).stat().st_size)
            self.assertEqual(3 * 4, (package_dir / batch["cloth_pin_file"]).stat().st_size)
            self.assertEqual(2 * 16, (package_dir / batch["cloth_constraint_file"]).stat().st_size)
            self.assertEqual(11 * 4, (package_dir / manifest["cloth_collider_file"]).stat().st_size)

    def test_writes_read_only_skeleton_overlay_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            model = ModelPreviewData(
                path="body.pac",
                physics_overlay=HkxPhysicsOverlayData(
                    source_paths=("body.hkx",),
                    bones=(
                        HkxPhysicsOverlayBone(
                            name="Spine",
                            index=4,
                            parent_index=1,
                            parent_name="Root",
                            source_path="body.hkx",
                        ),
                    ),
                    skeleton_pose_enabled=True,
                    skeleton_selected_bone_index=4,
                    skeleton_pose_rotations=((4, (0.0, 12.5, 0.0)),),
                ),
            )

            package_dir = write_isolated_d3d11_preview_package(
                model,
                PreparedModelPreviewData(source_path="body.pac"),
                output_root=Path(temp_dir) / "package",
            )
            manifest = read_isolated_d3d11_preview_manifest(package_dir)

        skeleton = manifest["skeleton_overlay"]
        self.assertTrue(skeleton["enabled"])
        self.assertEqual("ok", skeleton["status"])
        self.assertTrue(skeleton["read_only"])
        self.assertEqual(1, skeleton["bone_count"])
        self.assertTrue(skeleton["pose_enabled"])
        self.assertEqual(4, skeleton["selected_bone_index"])
        self.assertEqual(1, skeleton["posed_bone_count"])
        self.assertEqual([0.0, 12.5, 0.0], skeleton["pose_rotations"][0]["rotation_degrees"])
        self.assertEqual("Spine", skeleton["bones"][0]["name"])
        self.assertEqual("hkx_physics", manifest["editable_value_groups"][0]["kind"])
        self.assertTrue(manifest["editable_value_groups"][0]["read_only"])

    def test_materializes_in_memory_base_texture_for_d3d11_package(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            image = QImage(4, 4, QImage.Format.Format_RGBA8888)
            image.fill(QColor("#884422"))
            model = ModelPreviewData(
                path="replacement.pac",
                meshes=[ModelPreviewMesh(preview_texture_image=image)],
            )
            prepared = PreparedModelPreviewData(
                source_path="replacement.pac",
                vertex_count=3,
                batches=(
                    PreparedModelPreviewBatch(
                        vertex_blob=_vertex(0, 0, 0) + _vertex(1, 0, 0) + _vertex(0, 1, 0),
                        index_count=3,
                        preview_texture_path="in_memory:0",
                        has_texture_coordinates=True,
                    ),
                ),
            )

            package_dir = write_isolated_d3d11_preview_package(
                model,
                prepared,
                output_root=temp_path / "package",
                use_textures=True,
                prefer_direct_dds=True,
            )
            manifest = read_isolated_d3d11_preview_manifest(package_dir)
            base_texture = manifest["batches"][0]["textures"]["base"]
            base_texture_exists = (package_dir / base_texture).is_file()

        self.assertTrue(base_texture)
        self.assertTrue(base_texture_exists)
        self.assertNotIn("in_memory", base_texture)

    def test_gltf_metallic_roughness_preview_generates_metal_support_maps(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            base = temp_path / "helmet_baseColor.png"
            normal = temp_path / "helmet_normal.png"
            material = temp_path / "helmet_metallicRoughness.png"
            base_image = QImage(4, 4, QImage.Format_RGBA8888)
            base_image.fill(QColor(120, 130, 140, 255))
            self.assertTrue(base_image.save(str(base), "PNG"))
            normal_image = QImage(4, 4, QImage.Format_RGBA8888)
            normal_image.fill(QColor(128, 128, 255, 255))
            self.assertTrue(normal_image.save(str(normal), "PNG"))
            material_image = QImage(4, 4, QImage.Format_RGBA8888)
            material_image.fill(QColor(240, 56, 235, 255))
            self.assertTrue(material_image.save(str(material), "PNG"))
            prepared = PreparedModelPreviewData(
                source_path="helmet.gltf",
                batches=(
                    PreparedModelPreviewBatch(
                        material_name="lambert1",
                        vertex_blob=_vertex(0, 0, 0) + _vertex(1, 0, 0) + _vertex(0, 1, 0),
                        index_count=3,
                        preview_texture_path=str(base),
                        preview_normal_texture_path=str(normal),
                        preview_material_texture_path=str(material),
                        preview_material_texture_subtype="metallic_roughness",
                        preview_material_texture_packed_channels=("roughness", "metallic"),
                        preview_material_texture_inputs=(
                            PreviewMaterialTextureInput(
                                slot_kind="base",
                                parameter_name="_baseColorTexture",
                                preview_texture_path=str(base),
                                texture_name=base.name,
                                semantic_type="color",
                                semantic_subtype="albedo",
                            ),
                            PreviewMaterialTextureInput(
                                slot_kind="normal",
                                parameter_name="_normalTexture",
                                preview_texture_path=str(normal),
                                texture_name=normal.name,
                                semantic_type="normal",
                                semantic_subtype="normal",
                            ),
                            PreviewMaterialTextureInput(
                                slot_kind="material",
                                parameter_name="_metallicRoughnessTexture",
                                preview_texture_path=str(material),
                                texture_name=material.name,
                                semantic_type="material",
                                semantic_subtype="metallic_roughness",
                                packed_channels=("roughness", "metallic"),
                            ),
                        ),
                        has_texture_coordinates=True,
                    ),
                ),
            )

            package_dir = write_isolated_d3d11_preview_package(
                ModelPreviewData(path="helmet.gltf"),
                prepared,
                output_root=temp_path / "package",
            )
            manifest = read_isolated_d3d11_preview_manifest(package_dir)
            batch = manifest["batches"][0]

        self.assertEqual("neutral_studio", manifest["lighting_preset"])
        self.assertAlmostEqual(ModelPreviewRenderSettings().specular_max, manifest["specular_max"])
        self.assertAlmostEqual(ModelPreviewRenderSettings().diffuse_wrap_bias, manifest["diffuse_wrap_bias"])
        self.assertTrue(batch["textures"]["roughness"])
        self.assertTrue(batch["textures"]["metalness"])
        self.assertTrue(batch["textures"]["specular"])
        self.assertIn("metallic_roughness", batch["material_contract"]["decode_profile"]["decode_modes"])

    def test_copies_file_url_imported_base_texture_for_d3d11_package(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            base = temp_path / "Scene_-_Root_baseColor.png"
            base.write_bytes(b"png")
            prepared = PreparedModelPreviewData(
                source_path="replacement.gltf",
                vertex_count=3,
                batches=(
                    PreparedModelPreviewBatch(
                        vertex_blob=_vertex(0, 0, 0) + _vertex(1, 0, 0) + _vertex(0, 1, 0),
                        index_count=3,
                        preview_texture_path=base.as_uri(),
                        has_texture_coordinates=True,
                    ),
                ),
            )

            package_dir = write_isolated_d3d11_preview_package(
                ModelPreviewData(path="replacement.gltf"),
                prepared,
                output_root=temp_path / "package",
                use_textures=True,
                prefer_direct_dds=True,
            )
            manifest = read_isolated_d3d11_preview_manifest(package_dir)
            base_texture = manifest["batches"][0]["textures"]["base"]

            self.assertTrue(base_texture)
            self.assertTrue((package_dir / base_texture).is_file())

    def test_writes_geometry_and_direct_texture_slots(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            base = temp_path / "base.png"
            normal = temp_path / "normal.png"
            specular = temp_path / "material_sp.png"
            packed = temp_path / "material_ma.png"
            detail = temp_path / "material_mg.png"
            height = temp_path / "height_disp.png"
            base_dds = temp_path / "base.dds"
            specular_dds = temp_path / "material_sp.dds"
            packed_dds = temp_path / "material_ma.dds"
            detail_dds = temp_path / "material_mg.dds"
            for path in (base, normal, specular, packed, detail, height):
                path.write_bytes(path.name.encode("ascii"))
            for path in (base_dds, specular_dds, packed_dds, detail_dds):
                path.write_bytes(_minimal_bc_dds(b"DXT1"))
            blob = b"".join(
                (
                    _vertex(-1.0, 0.0, 0.0, uv=(0.0, 0.0)),
                    _vertex(1.0, 0.0, 0.0, uv=(1.0, 0.0)),
                    _vertex(0.0, 1.0, 0.0, uv=(0.5, 1.0)),
                )
            )
            prepared = PreparedModelPreviewData(
                source_path="weapon.pac",
                batches=(
                    PreparedModelPreviewBatch(
                        material_name="blade",
                        texture_name="blade_base",
                        vertex_blob=blob,
                        index_count=3,
                        preview_texture_path=str(base),
                        preview_texture_dds_path=str(base_dds),
                        preview_normal_texture_path=str(normal),
                        preview_height_texture_path=str(height),
                        preview_alpha_mode="MASK",
                        preview_double_sided=True,
                        preview_material_texture_inputs=(
                            PreviewMaterialTextureInput(
                                slot_kind="material",
                                texture_name="blade_sp",
                                source_dds_path=str(specular_dds),
                                preview_texture_path=str(specular),
                                semantic_subtype="specular",
                                shader_family="SkinnedMeshStandard_Ver2",
                                material_parameters=(
                                    PreviewMaterialParameterInput(
                                        parameter_kind="byte4",
                                        parameter_name="_scratchMetallic",
                                        value="16777215",
                                    ),
                                    PreviewMaterialParameterInput(
                                        parameter_kind="byte4",
                                        parameter_name="_scratchRoughness",
                                        value="8388607",
                                    ),
                                ),
                            ),
                            PreviewMaterialTextureInput(
                                slot_kind="material",
                                texture_name="blade_ma",
                                source_dds_path=str(packed_dds),
                                preview_texture_path=str(packed),
                                semantic_subtype="material_mask",
                            ),
                            PreviewMaterialTextureInput(
                                slot_kind="material",
                                parameter_name="_detailMaskTexture",
                                texture_name="blade_mg",
                                source_dds_path=str(detail_dds),
                                preview_texture_path=str(detail),
                                semantic_subtype="detail_mask",
                                srgb_mode="linear",
                                parameter_declared_by="pac_xml",
                                material_output_quality="layer",
                                layer_role="detail_mask",
                                layer_channel="g",
                                blend_flags=("role:detail_mask", "channel:g"),
                            ),
                        ),
                        has_texture_coordinates=True,
                        source_submesh_index=7,
                        source_vertex_indices=(10, 11, 12),
                        source_face_indices=(42,),
                        editor_role="replacement",
                        editor_part_name="blade",
                    ),
                ),
            )

            package_dir = write_isolated_d3d11_preview_package(
                ModelPreviewData(path="weapon.pac"),
                prepared,
                output_root=temp_path / "package",
                display_mode="side_by_side",
                editor_workspace="mesh_alignment",
            )
            manifest = read_isolated_d3d11_preview_manifest(package_dir)

            batch = manifest["batches"][0]
            geometry_path = package_dir / batch["vertex_file"]
            textures = batch["textures"]
            dds_textures = batch["dds_textures"]
            material_contract = batch["material_contract"]
            material_channel_contract = batch["material_channel_contract"]
            texture_quality = batch["texture_quality"]
            editor_identity = batch["editor_identity"]

            self.assertEqual("side_by_side", manifest["display_mode"])
            self.assertEqual("mesh_alignment", manifest["editor_workspace"])
            self.assertEqual("shiny_metal_inspection", manifest["lighting_preset"])
            self.assertAlmostEqual(ModelPreviewRenderSettings().d3d11_tone_exposure, manifest["d3d11_tone_exposure"])
            self.assertAlmostEqual(ModelPreviewRenderSettings().d3d11_tone_contrast, manifest["d3d11_tone_contrast"])
            self.assertAlmostEqual(ModelPreviewRenderSettings().d3d11_tone_gamma, manifest["d3d11_tone_gamma"])
            self.assertAlmostEqual(ModelPreviewRenderSettings().d3d11_environment_strength, manifest["d3d11_environment_strength"])
            self.assertAlmostEqual(ModelPreviewRenderSettings().ambient_strength, manifest["ambient_strength"])
            self.assertEqual("alpha_cutout", batch["alpha_mode"])
            self.assertEqual("MASK", batch["source_alpha_mode"])
            self.assertTrue(batch["double_sided"])
            self.assertTrue(batch["two_sided"])
            self.assertEqual(3 * ISOLATED_PREVIEW_VERTEX_STRIDE_BYTES, geometry_path.stat().st_size)
            self.assertEqual(7, editor_identity["source_submesh_index"])
            self.assertEqual("replacement", editor_identity["role"])
            self.assertEqual("blade", editor_identity["part_name"])
            self.assertEqual(12, editor_identity["identity_stride_bytes"])
            identity_blob = (package_dir / editor_identity["identity_file"]).read_bytes()
            self.assertEqual((7, 10, 42, 7, 11, 42, 7, 12, 42), struct.unpack("<iiiiiiiii", identity_blob))
            self.assertTrue((package_dir / textures["base"]).is_file())
            self.assertTrue(dds_textures["base"]["direct_upload_candidate"])
            self.assertEqual("bc1", dds_textures["base"]["compressed_family"])
            self.assertNotIn("mip_levels", dds_textures["base"])
            self.assertNotIn('"mip_levels"', (package_dir / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(3, len(dds_textures["material_inputs"]))
            detail_input = next(item for item in dds_textures["material_inputs"] if item["source_path"] == str(detail_dds))
            self.assertEqual("_detailMaskTexture", detail_input["parameter_name"])
            self.assertEqual("linear", detail_input["srgb_mode"])
            self.assertEqual("pac_xml", detail_input["parameter_declared_by"])
            self.assertEqual("layer", detail_input["material_output_quality"])
            self.assertEqual("detail_mask", detail_input["layer_role"])
            self.assertEqual("g", detail_input["layer_channel"])
            self.assertIn("channel:g", detail_input["blend_flags"])
            self.assertTrue((package_dir / textures["normal"]).is_file())
            self.assertTrue((package_dir / textures["height"]).is_file())
            self.assertTrue((package_dir / textures["specular"]).is_file())
            self.assertEqual("", textures["roughness"])
            self.assertEqual("", textures["metalness"])
            self.assertTrue(batch["tangents_usable"])
            self.assertEqual("standard_v2", batch["material_shader_family"])
            self.assertEqual("standard_v2", material_contract["shader_family"])
            self.assertEqual(2, material_contract["schema_version"])
            self.assertEqual("standard_v2", material_contract["decode_policy"]["family"])
            self.assertEqual("authoritative", material_contract["decode_policy"]["authority"])
            self.assertEqual("standard_v2", material_contract["decode_profile"]["shader_family"])
            self.assertIn("registry_decodes", material_contract)
            self.assertTrue(any(item.get("source_kind") == "crimson_detail_mask" for item in material_contract["registry_decodes"]))
            self.assertGreater(material_contract["decode_policy"]["metalness_scale"], 0.0)
            self.assertEqual("direct_dds", material_contract["texture_slots"]["base"]["status"])
            self.assertEqual("high", material_contract["texture_slots"]["base"]["confidence"])
            self.assertTrue(material_contract["slot_diagnostics"])
            self.assertEqual("direct_dds", texture_quality["slots"]["base"]["status"])
            self.assertTrue(texture_quality["slots"]["base"]["safe_upscale_candidate"])
            self.assertEqual("opt-in visible/base textures only; technical maps preserved by default", texture_quality["upscale_handoff_policy"])
            self.assertGreater(batch["native_material_hints"]["metalness"], 0.0)
            self.assertGreater(batch["native_material_hints"]["specular"], 0.0)
            self.assertEqual("metal", batch["material_category"])
            self.assertGreaterEqual(batch["material_category_confidence"], 0.70)
            unresolved = material_channel_contract["unresolved"]
            self.assertTrue(
                any(item.get("parameter_name") == "_detailMaskTexture" and item.get("disposition") == "layer_only" for item in unresolved)
            )
            self.assertTrue(
                any(str(item.get("source_dds_path", "")).endswith("material_sp.dds") and item.get("disposition") == "diagnostic_only" for item in unresolved)
            )
            notes = " ".join(batch["notes"])
            self.assertIn("material output quality:layer", notes)
            self.assertIn("shader family:standard_v2", notes)
            self.assertIn("material category:metal", notes)
            self.assertIn("direct DDS slots:base", notes)
            self.assertIn("unresolved material channel maps:", notes)
            self.assertIn("direct DDS slots:base,material", notes)
            self.assertNotIn("packed material map skipped", notes)
            fidelity_status = manifest["shader_asset_fidelity_status"]
            self.assertEqual("unresolved_diagnostic", fidelity_status["unknown_crimson_map_policy"])
            self.assertGreaterEqual(fidelity_status["unknown_crimson_map_count"], 1)
            self.assertGreaterEqual(fidelity_status["diagnostic_only_count"], 1)
            self.assertIn("guess", fidelity_status["authority_counts"])

    def test_prefer_direct_dds_skips_preview_png_fallbacks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            base = temp_path / "base.png"
            specular = temp_path / "material_sp.png"
            pbr = temp_path / "legacy_pbr.png"
            base_dds = temp_path / "base.dds"
            specular_dds = temp_path / "material_sp.dds"
            material_dds = temp_path / "material_ma.dds"
            for path in (base, specular, pbr):
                path.write_bytes(path.name.encode("ascii"))
            for path in (base_dds, specular_dds, material_dds):
                path.write_bytes(_minimal_bc_dds(b"DXT1"))
            blob = b"".join(
                (
                    _vertex(-1.0, 0.0, 0.0, uv=(0.0, 0.0)),
                    _vertex(1.0, 0.0, 0.0, uv=(1.0, 0.0)),
                    _vertex(0.0, 1.0, 0.0, uv=(0.5, 1.0)),
                )
            )
            prepared = PreparedModelPreviewData(
                source_path="weapon.pac",
                batches=(
                    PreparedModelPreviewBatch(
                        material_name="blade",
                        texture_name="blade_base",
                        vertex_blob=blob,
                        index_count=3,
                        preview_texture_path=str(base),
                        preview_texture_dds_path=str(base_dds),
                        preview_material_texture_path=str(pbr),
                        preview_material_texture_dds_path=str(material_dds),
                        preview_material_texture_subtype="legacy_pbr_combined",
                        preview_material_texture_inputs=(
                            PreviewMaterialTextureInput(
                                slot_kind="material",
                                texture_name="blade_sp",
                                source_dds_path=str(specular_dds),
                                preview_texture_path=str(specular),
                                semantic_subtype="specular",
                            ),
                        ),
                        has_texture_coordinates=True,
                    ),
                ),
            )

            package_dir = write_isolated_d3d11_preview_package(
                ModelPreviewData(path="weapon.pac"),
                prepared,
                output_root=temp_path / "package",
                enable_material_combiner=False,
                prefer_direct_dds=True,
            )
            batch = read_isolated_d3d11_preview_manifest(package_dir)["batches"][0]
            textures = batch["textures"]

            self.assertEqual("", textures["base"])
            self.assertEqual("", textures["specular"])
            self.assertEqual("", textures["roughness"])
            self.assertFalse((package_dir / "textures" / "combined").exists())
            notes = " ".join(batch["notes"])
            self.assertIn("base PNG fallback skipped", notes)
            self.assertIn("specular PNG fallback skipped", notes)
            self.assertIn("legacy PBR PNG split skipped", notes)

    def test_direct_base_material_input_promotes_to_authoritative_base_slot(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            base_png = temp_path / "batch_base.png"
            base_dds = temp_path / "resolved_base.dds"
            base_png.write_bytes(b"preview")
            base_dds.write_bytes(_minimal_bc_dds(b"DXT1"))
            blob = b"".join(
                (
                    _vertex(-1.0, 0.0, 0.0, uv=(0.0, 0.0)),
                    _vertex(1.0, 0.0, 0.0, uv=(1.0, 0.0)),
                    _vertex(0.0, 1.0, 0.0, uv=(0.5, 1.0)),
                )
            )
            prepared = PreparedModelPreviewData(
                source_path="head.pac",
                batches=(
                    PreparedModelPreviewBatch(
                        material_name="head",
                        texture_name="head",
                        vertex_blob=blob,
                        index_count=3,
                        preview_texture_path=str(base_png),
                        preview_material_texture_inputs=(
                            PreviewMaterialTextureInput(
                                slot_kind="base",
                                texture_name="resolved_base",
                                source_dds_path=str(base_dds),
                                preview_texture_path=str(base_png),
                                parameter_name="_baseColorTexture",
                                semantic_type="albedo",
                                semantic_subtype="base_color",
                            ),
                        ),
                        has_texture_coordinates=True,
                    ),
                ),
            )

            package_dir = write_isolated_d3d11_preview_package(
                ModelPreviewData(path="head.pac"),
                prepared,
                output_root=temp_path / "package",
                enable_material_combiner=False,
                prefer_direct_dds=True,
            )
            batch = read_isolated_d3d11_preview_manifest(package_dir)["batches"][0]

            self.assertEqual("", batch["textures"]["base"])
            self.assertEqual(str(base_dds), batch["dds_textures"]["base"]["source_path"])
            self.assertTrue(batch["dds_textures"]["base"]["promoted_from_material_input"])
            self.assertIn("base PNG fallback skipped", " ".join(batch["notes"]))

    def test_skin_detail_diffuse_texturelayer_is_not_used_as_whole_head_base(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            detail_png = temp_path / "cd_texturelayer_003_0005.png"
            detail_dds = temp_path / "cd_texturelayer_003_0005.dds"
            detail_image = QImage(4, 4, QImage.Format.Format_RGBA8888)
            detail_image.fill(QColor(190, 162, 132, 255))
            self.assertTrue(detail_image.save(str(detail_png), "PNG"))
            detail_dds.write_bytes(_minimal_bc_dds(b"DXT1"))
            blob = b"".join(
                (
                    _vertex(-1.0, 0.0, 0.0, uv=(0.0, 0.0)),
                    _vertex(1.0, 0.0, 0.0, uv=(1.0, 0.0)),
                    _vertex(0.0, 1.0, 0.0, uv=(0.5, 1.0)),
                )
            )
            prepared = PreparedModelPreviewData(
                source_path="character/model/1_pc/2_phw/nude/cd_phw_00_nude_00_0001_damian.pac",
                batches=(
                    PreparedModelPreviewBatch(
                        material_name="CD_PHW_00_Head_00_0001_01",
                        texture_name="CD_PHW_00_Head_00_0001_01",
                        vertex_blob=blob,
                        index_count=3,
                        preview_texture_path=str(detail_png),
                        preview_texture_dds_path=str(detail_dds),
                        preview_material_texture_inputs=(
                            PreviewMaterialTextureInput(
                                slot_kind="base",
                                parameter_name="_detailDiffuseMaskB",
                                source_texture_path="character/texture/cd_texturelayer_003_0005.dds",
                                source_dds_path=str(detail_dds),
                                texture_name="cd_texturelayer_003_0005.dds",
                                preview_texture_path=str(detail_png),
                                semantic_type="color",
                                semantic_subtype="base_color",
                                material_name="CD_PHW_00_Head_00_0001_01",
                                shader_family="SkinnedMeshSkin",
                                visualized=True,
                            ),
                        ),
                        has_texture_coordinates=True,
                        editor_role="replacement_preview",
                    ),
                ),
            )

            package_dir = write_isolated_d3d11_preview_package(
                ModelPreviewData(path="head.pac"),
                prepared,
                output_root=temp_path / "package",
                enable_material_combiner=False,
                prefer_direct_dds=True,
                editor_workspace="modify_original_alignment",
            )
            batch = read_isolated_d3d11_preview_manifest(package_dir)["batches"][0]

            self.assertEqual("", batch["textures"]["base"])
            self.assertNotIn("base", batch["dds_textures"])
            self.assertIn("material_inputs", batch["dds_textures"])
            self.assertEqual("layer_only", batch["dds_textures"]["material_inputs"][0]["disposition"])
            self.assertIn("base texturelayer kept masked", " ".join(batch["notes"]))

    def test_modify_original_skin_head_uses_archive_combiner_for_layer_only_base(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            detail_png = temp_path / "cd_texturelayer_003_0005.png"
            detail_dds = temp_path / "cd_texturelayer_003_0005.dds"
            detail_image = QImage(4, 4, QImage.Format.Format_RGBA8888)
            detail_image.fill(QColor(190, 162, 132, 255))
            self.assertTrue(detail_image.save(str(detail_png), "PNG"))
            detail_dds.write_bytes(_minimal_bc_dds(b"DXT1"))
            mask_png = temp_path / "cd_phw_00_uw_00_0001_mg.png"
            mask_image = QImage(4, 4, QImage.Format.Format_RGBA8888)
            mask_image.fill(QColor(64, 128, 192, 255))
            self.assertTrue(mask_image.save(str(mask_png), "PNG"))
            blob = b"".join(
                (
                    _vertex(-1.0, 0.0, 0.0, uv=(0.0, 0.0)),
                    _vertex(1.0, 0.0, 0.0, uv=(1.0, 0.0)),
                    _vertex(0.0, 1.0, 0.0, uv=(0.5, 1.0)),
                )
            )
            prepared = PreparedModelPreviewData(
                source_path="character/model/1_pc/2_phw/nude/cd_phw_00_nude_00_0001_damian.pac",
                batches=(
                    PreparedModelPreviewBatch(
                        material_name="CD_PHW_00_Head_00_0001_01",
                        texture_name="CD_PHW_00_Head_00_0001_01",
                        vertex_blob=blob,
                        index_count=3,
                        preview_texture_path=str(detail_png),
                        preview_texture_dds_path=str(detail_dds),
                        preview_material_texture_inputs=(
                            PreviewMaterialTextureInput(
                                slot_kind="base",
                                parameter_name="_detailDiffuseMaskB",
                                source_texture_path="character/texture/cd_texturelayer_003_0005.dds",
                                source_dds_path=str(detail_dds),
                                texture_name="cd_texturelayer_003_0005.dds",
                                preview_texture_path=str(detail_png),
                                semantic_type="color",
                                semantic_subtype="base_color",
                                material_name="CD_PHW_00_Head_00_0001_01",
                                shader_family="SkinnedMeshSkin",
                                visualized=True,
                            ),
                            PreviewMaterialTextureInput(
                                slot_kind="detail",
                                parameter_name="_colorBlendingMaskTexture",
                                source_texture_path="character/texture/cd_phw_00_uw_00_0001_mg.dds",
                                texture_name="cd_phw_00_uw_00_0001_mg.dds",
                                preview_texture_path=str(mask_png),
                                semantic_type="mask",
                                semantic_subtype="detail_mask",
                                material_name="CD_PHW_00_Head_00_0001_01",
                                shader_family="SkinnedMeshSkin",
                                visualized=True,
                            ),
                        ),
                        has_texture_coordinates=True,
                        editor_role="replacement_preview",
                    ),
                ),
            )

            package_dir = write_isolated_d3d11_preview_package(
                ModelPreviewData(path="head.pac"),
                prepared,
                output_root=temp_path / "package",
                enable_material_combiner=True,
                prefer_direct_dds=True,
                editor_workspace="modify_original_alignment",
            )
            batch = read_isolated_d3d11_preview_manifest(package_dir)["batches"][0]

            self.assertEqual("modify_original_archive_parity", batch["material_combiner_policy"])
            self.assertTrue(batch["material_combiner_enabled"])
            self.assertTrue(batch["material_combiner_active"])
            self.assertIn("combined", batch["textures"]["base"])
            self.assertTrue(batch["prefer_generated_base_texture"])
            self.assertNotIn("base", batch["dds_textures"])
            joined_notes = " ".join(batch["notes"])
            self.assertIn("archive preview material combiner enabled", joined_notes)
            self.assertIn("layer-only base rejected", joined_notes)
            self.assertIn("albedo synthesized", joined_notes)
            self.assertTrue(batch["material_base_policy"]["no_reliable_full_base_albedo"])

    def test_alignment_package_uses_archive_parity_material_policy_for_original_reference_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            low_authority_base = temp_path / "cd_common_default_overlay_old.png"
            detail_diffuse = temp_path / "cd_texturelayer_003_0016.png"
            detail_mask = temp_path / "blade_mg.png"
            material_mask = temp_path / "blade_ma.png"
            replacement_base = temp_path / "replacement_base.png"
            replacement_base_dds = temp_path / "replacement_base.dds"
            for path, color in (
                (low_authority_base, QColor(24, 24, 24, 255)),
                (detail_diffuse, QColor(220, 48, 32, 255)),
                (detail_mask, QColor(255, 0, 0, 255)),
                (material_mask, QColor(70, 170, 210, 255)),
                (replacement_base, QColor(40, 140, 210, 255)),
            ):
                image = QImage(4, 4, QImage.Format_RGBA8888)
                image.fill(color)
                self.assertTrue(image.save(str(path), "PNG"))
            replacement_base_dds.write_bytes(_minimal_bc_dds(b"DXT1"))
            blob = b"".join(
                (
                    _vertex(-1.0, 0.0, 0.0, uv=(0.0, 0.0)),
                    _vertex(1.0, 0.0, 0.0, uv=(1.0, 0.0)),
                    _vertex(0.0, 1.0, 0.0, uv=(0.5, 1.0)),
                )
            )
            reference_inputs = (
                PreviewMaterialTextureInput(
                    slot_kind="base",
                    parameter_name="_overlayColorTexture",
                    source_texture_path="character/texture/cd_common_default_overlay_old.dds",
                    texture_name="cd_common_default_overlay_old.dds",
                    preview_texture_path=str(low_authority_base),
                    semantic_type="color",
                    semantic_subtype="albedo",
                    material_name="CD_PHM_02_Blade_0014",
                    shader_family="SkinnedMeshStandard_Ver2",
                    confidence="pac_xml",
                    visualized=True,
                ),
                PreviewMaterialTextureInput(
                    slot_kind="material",
                    parameter_name="_detailDiffuseMaskR",
                    source_texture_path="character/texture/cd_texturelayer_003_0016.dds",
                    texture_name="cd_texturelayer_003_0016.dds",
                    preview_texture_path=str(detail_diffuse),
                    semantic_type="color",
                    semantic_subtype="detail_diffuse",
                    material_name="CD_PHM_02_Blade_0014",
                    shader_family="SkinnedMeshStandard_Ver2",
                    material_parameters=(
                        PreviewMaterialParameterInput(
                            parameter_kind="byte4",
                            parameter_name="_dyeingGlobalOpacity",
                            value="255",
                        ),
                    ),
                    visualized=True,
                ),
                PreviewMaterialTextureInput(
                    slot_kind="material",
                    parameter_name="_detailMaskTexture",
                    source_texture_path="character/texture/cd_phm_02_blade_0014_mg.dds",
                    texture_name="cd_phm_02_blade_0014_mg.dds",
                    preview_texture_path=str(detail_mask),
                    semantic_type="mask",
                    semantic_subtype="detail_mask",
                    material_name="CD_PHM_02_Blade_0014",
                    shader_family="SkinnedMeshStandard_Ver2",
                    visualized=True,
                ),
                PreviewMaterialTextureInput(
                    slot_kind="material",
                    parameter_name="_colorBlendingMaskTexture",
                    source_texture_path="character/texture/cd_phm_02_blade_0014_ma.dds",
                    texture_name="cd_phm_02_blade_0014_ma.dds",
                    preview_texture_path=str(material_mask),
                    semantic_type="mask",
                    semantic_subtype="material_mask",
                    material_name="CD_PHM_02_Blade_0014",
                    shader_family="SkinnedMeshStandard_Ver2",
                    visualized=True,
                ),
            )
            prepared = PreparedModelPreviewData(
                source_path="weapon.pac",
                batches=(
                    PreparedModelPreviewBatch(
                        material_name="CD_PHM_02_Blade_0014",
                        texture_name="CD_PHM_02_Blade_0014",
                        vertex_blob=blob,
                        index_count=3,
                        preview_texture_path=str(low_authority_base),
                        preview_material_texture_inputs=reference_inputs,
                        has_texture_coordinates=True,
                        editor_role="original_reference",
                    ),
                    PreparedModelPreviewBatch(
                        material_name="Replacement",
                        texture_name="Replacement",
                        vertex_blob=blob,
                        index_count=3,
                        preview_texture_path=str(replacement_base),
                        preview_texture_dds_path=str(replacement_base_dds),
                        has_texture_coordinates=True,
                        editor_role="replacement_preview",
                    ),
                ),
            )

            package_dir = write_isolated_d3d11_preview_package(
                ModelPreviewData(path="weapon.pac"),
                prepared,
                output_root=temp_path / "package",
                enable_material_combiner=True,
                prefer_direct_dds=True,
                display_mode="side_by_side",
                editor_workspace="mesh_replacement_alignment",
            )
            manifest = read_isolated_d3d11_preview_manifest(package_dir)

            reference_batch, replacement_batch = manifest["batches"]
            self.assertEqual("original_reference_archive_parity", reference_batch["material_combiner_policy"])
            self.assertFalse(reference_batch["editor_identity"]["editable"])
            self.assertTrue(reference_batch["material_combiner_enabled"])
            self.assertTrue(reference_batch["prefer_direct_dds"])
            self.assertTrue(reference_batch["material_combiner_active"])
            self.assertIn("combined", reference_batch["textures"]["base"])
            self.assertTrue(any("original reference material policy" in note for note in reference_batch["notes"]))

            self.assertEqual("replacement_source_direct", replacement_batch["material_combiner_policy"])
            self.assertTrue(replacement_batch["editor_identity"]["editable"])
            self.assertFalse(replacement_batch["material_combiner_enabled"])
            self.assertTrue(replacement_batch["prefer_direct_dds"])
            self.assertFalse(replacement_batch["material_combiner_active"])
            self.assertTrue(replacement_batch["dds_textures"]["base"]["direct_upload_candidate"])
            self.assertTrue(any("base PNG fallback skipped; direct DDS available" in note for note in replacement_batch["notes"]))

            modify_original_package_dir = write_isolated_d3d11_preview_package(
                ModelPreviewData(path="weapon.pac"),
                prepared,
                output_root=temp_path / "package_modify_original",
                enable_material_combiner=True,
                prefer_direct_dds=True,
                display_mode="side_by_side",
                editor_workspace="modify_original_alignment",
            )
            _modify_reference_batch, modify_replacement_batch = read_isolated_d3d11_preview_manifest(
                modify_original_package_dir
            )["batches"]
            self.assertEqual("modify_original_archive_parity", modify_replacement_batch["material_combiner_policy"])
            self.assertTrue(modify_replacement_batch["material_combiner_enabled"])
            self.assertTrue(modify_replacement_batch["prefer_direct_dds"])
            self.assertTrue(
                any("modify-original material policy" in note for note in modify_replacement_batch["notes"])
            )

            fast_package_dir = write_isolated_d3d11_preview_package(
                ModelPreviewData(path="weapon.pac"),
                prepared,
                output_root=temp_path / "package_fast",
                high_quality_textures=False,
                enable_material_combiner=False,
                prefer_direct_dds=True,
                original_reference_material_parity=False,
                display_mode="side_by_side",
                editor_workspace="mesh_replacement_alignment",
            )
            fast_reference_batch, fast_replacement_batch = read_isolated_d3d11_preview_manifest(fast_package_dir)["batches"]
            self.assertEqual("global", fast_reference_batch["material_combiner_policy"])
            self.assertFalse(fast_reference_batch["material_combiner_enabled"])
            self.assertTrue(fast_reference_batch["prefer_direct_dds"])
            self.assertFalse(fast_reference_batch["material_combiner_active"])
            self.assertNotIn("combined", fast_reference_batch["textures"]["base"])
            self.assertFalse(any("original reference material policy" in note for note in fast_reference_batch["notes"]))
            self.assertEqual("replacement_source_direct", fast_replacement_batch["material_combiner_policy"])
            self.assertFalse(fast_replacement_batch["material_combiner_enabled"])

    def test_modify_original_archive_parity_keeps_material_inputs_visible_to_combiner(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            base_dds = temp_path / "body.dds"
            height_dds = temp_path / "body_disp.dds"
            base_dds.write_bytes(_minimal_bc_dds(b"DXT1"))
            height_dds.write_bytes(_minimal_bc_dds(b"BC4U"))
            blob = b"".join(
                (
                    _vertex(-1.0, 0.0, 0.0, uv=(0.0, 0.0)),
                    _vertex(1.0, 0.0, 0.0, uv=(1.0, 0.0)),
                    _vertex(0.0, 1.0, 0.0, uv=(0.5, 1.0)),
                )
            )
            prepared = PreparedModelPreviewData(
                source_path="character/model/body.pac",
                format="pac",
                batches=(
                    PreparedModelPreviewBatch(
                        material_name="Body",
                        texture_name="Body",
                        vertex_blob=blob,
                        index_count=3,
                        preview_texture_dds_path=str(base_dds),
                        preview_material_texture_inputs=(
                            PreviewMaterialTextureInput(
                                slot_kind="height",
                                parameter_name="_heightTexture",
                                source_texture_path="character/texture/body_disp.dds",
                                source_dds_path=str(height_dds),
                                texture_name="body_disp.dds",
                                semantic_type="height",
                                semantic_subtype="height",
                                material_name="Body",
                                shader_family="SkinnedMeshSkin",
                                visualized=True,
                            ),
                        ),
                        has_texture_coordinates=True,
                        editor_role="replacement_preview",
                    ),
                ),
            )

            package_dir = write_isolated_d3d11_preview_package(
                ModelPreviewData(path="character/model/body.pac", format="pac"),
                prepared,
                output_root=temp_path / "package",
                enable_material_combiner=True,
                prefer_direct_dds=True,
                editor_workspace="modify_original_alignment",
            )

            batch = read_isolated_d3d11_preview_manifest(package_dir)["batches"][0]
            self.assertEqual("modify_original_archive_parity", batch["material_combiner_policy"])
            self.assertTrue(batch["material_combiner_enabled"])
            self.assertIn("base", batch["dds_textures"])
            self.assertIn("height", batch["dds_textures"])
            self.assertEqual(1, len(batch["dds_textures"]["material_inputs"]))
            self.assertEqual("height", batch["dds_textures"]["material_inputs"][0]["slot"])

    def test_synthesized_albedo_overrides_direct_low_authority_base_for_d3d11(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            low_authority_base = temp_path / "cd_common_default_overlay_old.png"
            base_image = QImage(4, 4, QImage.Format.Format_RGBA8888)
            base_image.fill(QColor(245, 245, 245, 255))
            self.assertTrue(base_image.save(str(low_authority_base), "PNG"))
            low_authority_dds = temp_path / "cd_common_default_overlay_old.dds"
            low_authority_dds.write_bytes(_minimal_bc_dds(b"DXT1"))
            detail_diffuse = temp_path / "cd_texturelayer_013_0018.png"
            detail_image = QImage(4, 4, QImage.Format.Format_RGBA8888)
            detail_image.fill(QColor(95, 32, 24, 255))
            self.assertTrue(detail_image.save(str(detail_diffuse), "PNG"))
            detail_mask = temp_path / "cd_phm_02_blade_0014_mg.png"
            mask_image = QImage(4, 4, QImage.Format.Format_RGBA8888)
            mask_image.fill(QColor(0, 255, 0, 255))
            self.assertTrue(mask_image.save(str(detail_mask), "PNG"))
            blob = b"".join(
                (
                    _vertex(-1.0, 0.0, 0.0, uv=(0.0, 0.0)),
                    _vertex(1.0, 0.0, 0.0, uv=(1.0, 0.0)),
                    _vertex(0.0, 1.0, 0.0, uv=(0.5, 1.0)),
                )
            )
            prepared = PreparedModelPreviewData(
                source_path="character/model/1_pc/1_phm/weapon/2_twohandweapon/cd_phm_02_sword_0014.pac",
                batches=(
                    PreparedModelPreviewBatch(
                        material_name="CD_PHM_02_Blade_0014",
                        texture_name="CD_PHM_02_Blade_0014",
                        vertex_blob=blob,
                        index_count=3,
                        preview_texture_path=str(low_authority_base),
                        preview_texture_dds_path=str(low_authority_dds),
                        preview_material_texture_inputs=(
                            PreviewMaterialTextureInput(
                                slot_kind="base",
                                parameter_name="_overlayColorTexture",
                                source_texture_path="character/texture/cd_common_default_overlay_old.dds",
                                source_dds_path=str(low_authority_dds),
                                texture_name="cd_common_default_overlay_old.dds",
                                preview_texture_path=str(low_authority_base),
                                semantic_type="color",
                                semantic_subtype="albedo",
                                material_name="CD_PHM_02_Blade_0014",
                                shader_family="SkinnedMeshStandard_Ver2",
                                confidence="pac_xml",
                                visualized=True,
                            ),
                            PreviewMaterialTextureInput(
                                slot_kind="material",
                                parameter_name="_grimeDiffuseTextureG",
                                source_texture_path="character/texture/cd_texturelayer_013_0018.dds",
                                texture_name="cd_texturelayer_013_0018.dds",
                                preview_texture_path=str(detail_diffuse),
                                semantic_type="color",
                                semantic_subtype="detail_diffuse",
                                material_name="CD_PHM_02_Blade_0014",
                                shader_family="SkinnedMeshStandard_Ver2",
                                visualized=True,
                            ),
                            PreviewMaterialTextureInput(
                                slot_kind="material",
                                parameter_name="_detailMaskTexture",
                                source_texture_path="character/texture/cd_phm_02_blade_0014_mg.dds",
                                texture_name="cd_phm_02_blade_0014_mg.dds",
                                preview_texture_path=str(detail_mask),
                                semantic_type="mask",
                                semantic_subtype="detail_mask",
                                material_name="CD_PHM_02_Blade_0014",
                                shader_family="SkinnedMeshStandard_Ver2",
                                visualized=True,
                            ),
                        ),
                        has_texture_coordinates=True,
                    ),
                ),
            )

            package_dir = write_isolated_d3d11_preview_package(
                ModelPreviewData(path="cd_phm_02_sword_0014.pac"),
                prepared,
                output_root=temp_path / "package",
                prefer_direct_dds=True,
            )
            batch = read_isolated_d3d11_preview_manifest(package_dir)["batches"][0]
            generated_base = package_dir / batch["textures"]["base"]
            generated_image = QImage(str(generated_base))

            self.assertTrue(batch["prefer_generated_base_texture"])
            self.assertTrue(generated_base.is_file())
            self.assertFalse(generated_image.isNull())
            self.assertLess(generated_image.pixelColor(0, 0).red(), 245)
            self.assertIn("native base DDS bypassed for synthesized sidecar albedo", " ".join(batch["notes"]))
            self.assertTrue(batch["material_base_policy"]["neutral_metal_base_synthesized"])
            self.assertTrue(batch["material_base_policy"]["no_reliable_full_base_albedo"])
            diagnostic_codes = {item["code"] for item in batch["material_base_diagnostics"]}
            self.assertIn("neutral_metal_base_synthesized", diagnostic_codes)
            self.assertIn("texturelayer_kept_masked", diagnostic_codes)
            self.assertIn("no_reliable_full_base_albedo", diagnostic_codes)

    def test_weapon_metal_texturelayer_without_base_uses_neutral_base_not_full_layer(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            detail_diffuse = temp_path / "cd_texturelayer_013_0018.png"
            detail_image = QImage(4, 4, QImage.Format.Format_RGBA8888)
            detail_image.fill(QColor(0, 220, 40, 255))
            self.assertTrue(detail_image.save(str(detail_diffuse), "PNG"))
            material_mask = temp_path / "cd_phm_02_blade_0015_ma.png"
            mask_image = QImage(4, 4, QImage.Format.Format_RGBA8888)
            mask_image.fill(QColor(0, 0, 0, 255))
            self.assertTrue(mask_image.save(str(material_mask), "PNG"))
            blob = b"".join(
                (
                    _vertex(-1.0, 0.0, 0.0, uv=(0.0, 0.0)),
                    _vertex(1.0, 0.0, 0.0, uv=(1.0, 0.0)),
                    _vertex(0.0, 1.0, 0.0, uv=(0.5, 1.0)),
                )
            )
            prepared = PreparedModelPreviewData(
                source_path="character/model/1_pc/1_phm/weapon/2_twohandweapon/cd_phm_02_sword_0015.pac",
                batches=(
                    PreparedModelPreviewBatch(
                        material_name="CD_PHM_02_Blade_0015",
                        texture_name="CD_PHM_02_Blade_0015",
                        vertex_blob=blob,
                        index_count=3,
                        preview_material_texture_inputs=(
                            PreviewMaterialTextureInput(
                                slot_kind="material",
                                parameter_name="_grimeDiffuseTextureG",
                                source_texture_path="character/texture/cd_texturelayer_013_0018.dds",
                                texture_name="cd_texturelayer_013_0018.dds",
                                preview_texture_path=str(detail_diffuse),
                                semantic_type="color",
                                semantic_subtype="detail_diffuse",
                                material_name="CD_PHM_02_Blade_0015",
                                shader_family="SkinnedMeshStandard_Ver2",
                                visualized=True,
                            ),
                            PreviewMaterialTextureInput(
                                slot_kind="material",
                                parameter_name="_colorBlendingMaskTexture",
                                source_texture_path="character/texture/cd_phm_02_blade_0015_ma.dds",
                                texture_name="cd_phm_02_blade_0015_ma.dds",
                                preview_texture_path=str(material_mask),
                                semantic_type="mask",
                                semantic_subtype="material_mask",
                                material_name="CD_PHM_02_Blade_0015",
                                shader_family="SkinnedMeshStandard_Ver2",
                                visualized=True,
                            ),
                        ),
                        has_texture_coordinates=True,
                    ),
                ),
            )

            package_dir = write_isolated_d3d11_preview_package(
                ModelPreviewData(path="cd_phm_02_sword_0015.pac"),
                prepared,
                output_root=temp_path / "package",
            )
            batch = read_isolated_d3d11_preview_manifest(package_dir)["batches"][0]
            generated_image = QImage(str(package_dir / batch["textures"]["base"]))
            pixel = generated_image.pixelColor(0, 0)

        self.assertTrue(batch["prefer_generated_base_texture"])
        self.assertTrue(batch["material_base_policy"]["neutral_metal_base_synthesized"])
        self.assertLess(pixel.green(), 180)
        self.assertIn("texturelayer_kept_masked", {item["code"] for item in batch["material_base_diagnostics"]})

    def test_d3d11_manifest_honors_support_map_and_camera_settings(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            base = temp_path / "base.png"
            normal_dds = temp_path / "normal_n.dds"
            material_dds = temp_path / "material_ma.dds"
            height_dds = temp_path / "height_disp.dds"
            base.write_bytes(b"base")
            for path in (normal_dds, material_dds, height_dds):
                path.write_bytes(_minimal_bc_dds(b"DXT1"))
            blob = b"".join(
                (
                    _vertex(-1.0, 0.0, 0.0, uv=(0.0, 0.0)),
                    _vertex(1.0, 0.0, 0.0, uv=(1.0, 0.0)),
                    _vertex(0.0, 1.0, 0.0, uv=(0.5, 1.0)),
                )
            )
            prepared = PreparedModelPreviewData(
                source_path="armor.pac",
                batches=(
                    PreparedModelPreviewBatch(
                        material_name="armor",
                        texture_name="armor_base",
                        vertex_blob=blob,
                        index_count=3,
                        preview_texture_path=str(base),
                        preview_normal_texture_dds_path=str(normal_dds),
                        preview_material_texture_dds_path=str(material_dds),
                        preview_height_texture_dds_path=str(height_dds),
                        has_texture_coordinates=True,
                    ),
                ),
            )
            settings = ModelPreviewRenderSettings(
                disable_normal_map=True,
                disable_height_map=True,
                orbit_sensitivity=0.33,
                pan_sensitivity=1.25,
                invert_orbit_x=True,
                invert_pan_y=True,
            )

            package_dir = write_isolated_d3d11_preview_package(
                ModelPreviewData(path="armor.pac"),
                prepared,
                output_root=temp_path / "package",
                render_settings=settings,
                prefer_direct_dds=True,
            )
            manifest = read_isolated_d3d11_preview_manifest(package_dir)
            dds_textures = manifest["batches"][0]["dds_textures"]

            self.assertNotIn("normal", dds_textures)
            self.assertIn("material", dds_textures)
            self.assertNotIn("height", dds_textures)
            self.assertAlmostEqual(0.33, manifest["orbit_sensitivity"])
            self.assertAlmostEqual(1.25, manifest["pan_sensitivity"])
            self.assertTrue(manifest["invert_orbit_x"])
            self.assertTrue(manifest["invert_pan_y"])

    def test_d3d11_manifest_skips_color_dds_bound_as_normal(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            base_dds = temp_path / "cd_phm_00_cloak_0009.dds"
            base_dds.write_bytes(_minimal_bc_dds(b"DXT1"))
            blob = b"".join(
                (
                    _vertex(-1.0, 0.0, 0.0, uv=(0.0, 0.0)),
                    _vertex(1.0, 0.0, 0.0, uv=(1.0, 0.0)),
                    _vertex(0.0, 1.0, 0.0, uv=(0.5, 1.0)),
                )
            )
            prepared = PreparedModelPreviewData(
                source_path="cd_m0001_00_de_pdm_cloak_21009.pac",
                batches=(
                    PreparedModelPreviewBatch(
                        material_name="CD_PHM_00_Cloak_0009",
                        texture_name="cd_phm_00_cloak_0009",
                        vertex_blob=blob,
                        index_count=3,
                        preview_texture_dds_path=str(base_dds),
                        preview_normal_texture_dds_path=str(base_dds),
                        preview_normal_texture_strength=1.0,
                        has_texture_coordinates=True,
                    ),
                ),
            )

            package_dir = write_isolated_d3d11_preview_package(
                ModelPreviewData(path="cd_m0001_00_de_pdm_cloak_21009.pac"),
                prepared,
                output_root=temp_path / "package",
                enable_material_combiner=False,
                prefer_direct_dds=True,
            )
            batch = read_isolated_d3d11_preview_manifest(package_dir)["batches"][0]

            self.assertIn("base", batch["dds_textures"])
            self.assertNotIn("normal", batch["dds_textures"])
            self.assertEqual("", batch["textures"]["normal"])
            self.assertEqual(0.0, batch["normal_strength"])
            self.assertIn("normal map skipped", " ".join(batch["notes"]))

    def test_prefer_direct_dds_keeps_png_fallback_when_dds_is_not_uploadable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            specular = temp_path / "material_sp.png"
            specular_dds = temp_path / "material_sp.dds"
            direct_specular = temp_path / "other_sp.png"
            direct_specular_dds = temp_path / "other_sp.dds"
            specular.write_bytes(b"preview")
            specular_dds.write_bytes(b"not a dds")
            direct_specular.write_bytes(b"preview")
            direct_specular_dds.write_bytes(_minimal_bc_dds())
            self.assertTrue(
                write_native_texture_report_sidecar(
                    specular,
                    {
                        "source_path": str(specular_dds),
                        "slot_kind": "specular",
                        "direct_upload_candidate": False,
                    },
                )
            )
            blob = b"".join(
                (
                    _vertex(-1.0, 0.0, 0.0, uv=(0.0, 0.0)),
                    _vertex(1.0, 0.0, 0.0, uv=(1.0, 0.0)),
                    _vertex(0.0, 1.0, 0.0, uv=(0.5, 1.0)),
                )
            )
            prepared = PreparedModelPreviewData(
                source_path="weapon.pac",
                batches=(
                    PreparedModelPreviewBatch(
                        material_name="blade",
                        texture_name="blade_base",
                        vertex_blob=blob,
                        index_count=3,
                        preview_material_texture_inputs=(
                            PreviewMaterialTextureInput(
                                slot_kind="material",
                                texture_name="other_sp",
                                source_dds_path=str(direct_specular_dds),
                                preview_texture_path=str(direct_specular),
                                semantic_subtype="specular",
                            ),
                            PreviewMaterialTextureInput(
                                slot_kind="material",
                                texture_name="blade_sp",
                                preview_texture_path=str(specular),
                                semantic_subtype="specular",
                            ),
                        ),
                        has_texture_coordinates=True,
                    ),
                ),
            )

            package_dir = write_isolated_d3d11_preview_package(
                ModelPreviewData(path="weapon.pac"),
                prepared,
                output_root=temp_path / "package",
                enable_material_combiner=False,
                prefer_direct_dds=True,
            )
            batch = read_isolated_d3d11_preview_manifest(package_dir)["batches"][0]
            textures = batch["textures"]

            self.assertTrue(textures["specular"])
            self.assertTrue((package_dir / textures["specular"]).is_file())
            notes = " ".join(batch["notes"])
            self.assertEqual(1, notes.count("specular PNG fallback skipped"))

    def test_prefer_direct_dds_drops_missing_manifest_dds_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            base = temp_path / "base.png"
            specular = temp_path / "material_sp.png"
            missing_base_dds = temp_path / "missing_base.dds"
            missing_specular_dds = temp_path / "missing_sp.dds"
            base.write_bytes(b"preview")
            specular.write_bytes(b"preview")
            blob = b"".join(
                (
                    _vertex(-1.0, 0.0, 0.0, uv=(0.0, 0.0)),
                    _vertex(1.0, 0.0, 0.0, uv=(1.0, 0.0)),
                    _vertex(0.0, 1.0, 0.0, uv=(0.5, 1.0)),
                )
            )
            prepared = PreparedModelPreviewData(
                source_path="head.pac",
                batches=(
                    PreparedModelPreviewBatch(
                        material_name="head",
                        texture_name="head",
                        vertex_blob=blob,
                        index_count=3,
                        preview_texture_path=str(base),
                        preview_texture_dds_path=str(missing_base_dds),
                        preview_material_texture_inputs=(
                            PreviewMaterialTextureInput(
                                slot_kind="material",
                                texture_name="head_sp",
                                source_dds_path=str(missing_specular_dds),
                                preview_texture_path=str(specular),
                                semantic_subtype="specular",
                            ),
                        ),
                        has_texture_coordinates=True,
                    ),
                ),
            )

            package_dir = write_isolated_d3d11_preview_package(
                ModelPreviewData(path="head.pac"),
                prepared,
                output_root=temp_path / "package",
                enable_material_combiner=False,
                prefer_direct_dds=True,
            )
            batch = read_isolated_d3d11_preview_manifest(package_dir)["batches"][0]
            manifest_text = json.dumps(batch, sort_keys=True)

            self.assertNotIn("base", batch["dds_textures"])
            self.assertNotIn("material_inputs", batch["dds_textures"])
            self.assertNotIn(str(missing_base_dds), manifest_text)
            self.assertNotIn(str(missing_specular_dds), manifest_text)
            self.assertTrue(batch["textures"]["base"])
            self.assertTrue((package_dir / batch["textures"]["base"]).is_file())
            self.assertTrue(batch["textures"]["specular"])
            self.assertTrue((package_dir / batch["textures"]["specular"]).is_file())
            self.assertNotIn("base PNG fallback skipped", " ".join(batch["notes"]))

    def test_package_combiner_generates_independent_pbr_slots(self) -> None:
        from PySide6.QtGui import QColor, QImage

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            base = temp_path / "blade_o.png"
            base_image = QImage(4, 4, QImage.Format_RGBA8888)
            base_image.fill(QColor(180, 120, 70, 80))
            self.assertTrue(base_image.save(str(base), "PNG"))
            material = temp_path / "blade_ma.png"
            material_image = QImage(4, 4, QImage.Format_RGBA8888)
            material_image.fill(QColor(64, 180, 230, 255))
            self.assertTrue(material_image.save(str(material), "PNG"))
            blob = b"".join(
                (
                    _vertex(-1.0, 0.0, 0.0, uv=(0.0, 0.0)),
                    _vertex(1.0, 0.0, 0.0, uv=(1.0, 0.0)),
                    _vertex(0.0, 1.0, 0.0, uv=(0.5, 1.0)),
                )
            )
            prepared = PreparedModelPreviewData(
                source_path="weapon.pac",
                batches=(
                    PreparedModelPreviewBatch(
                        material_name="blade",
                        texture_name="blade",
                        vertex_blob=blob,
                        index_count=3,
                        preview_texture_path=str(base),
                        preview_material_texture_inputs=(
                            PreviewMaterialTextureInput(
                                slot_kind="material",
                                texture_name="blade_ma.dds",
                                preview_texture_path=str(material),
                                source_texture_path="blade_ma.dds",
                                semantic_type="mask",
                                semantic_subtype="material_mask",
                                visualized=True,
                            ),
                        ),
                        has_texture_coordinates=True,
                    ),
                ),
            )

            package_dir = write_isolated_d3d11_preview_package(
                ModelPreviewData(path="weapon.pac"),
                prepared,
                output_root=temp_path / "package",
            )
            manifest = read_isolated_d3d11_preview_manifest(package_dir)

            batch = manifest["batches"][0]
            textures = batch["textures"]
            for slot in ("base", "occlusion", "roughness", "metalness", "specular"):
                self.assertTrue((package_dir / textures[slot]).is_file(), slot)
            self.assertEqual(2, manifest["material_contract_schema"])
            self.assertEqual(2, manifest["material_channel_contract_schema"])
            self.assertEqual(2, batch["material_contract"]["schema_version"])
            self.assertEqual(2, batch["material_channel_contract"]["schema_version"])
            self.assertEqual("metallic_roughness", batch["material_channel_contract"]["workflow"])
            self.assertTrue(batch["material_channel_diagnostics"])
            self.assertEqual("generic", batch["material_contract"]["shader_family"])
            self.assertIn("decode_profile", batch["material_contract"])
            self.assertIn("pbr_scalar_hints", batch["material_contract"])
            self.assertIn("slot_diagnostics", batch["material_contract"])
            self.assertIn("resolved_texture_slots", batch["material_contract"])
            self.assertIn("material", batch["material_contract"]["resolved_texture_slots"])
            self.assertEqual("ok", batch["material_contract"]["status"])
            self.assertIn("roughness", batch)
            self.assertIn("metalness", batch)
            self.assertIn("specular", batch)
            self.assertIn("height_scale", batch)
            self.assertTrue(batch["material_diagnostics"])
            self.assertTrue(batch["material_combiner_active"])
            self.assertIn("material_mask", batch["material_combiner_decode_modes"])
            self.assertIn("occlusion", batch["material_combiner_outputs"])
            self.assertFalse(batch["texture_flip_vertical"])

    def test_material_contract_reports_normalized_input_only_source_slots(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            base = temp_path / "base.png"
            clearcoat = temp_path / "clearcoat.png"
            sheen = temp_path / "sheen.png"
            transmission = temp_path / "transmission.png"
            opacity = temp_path / "opacity.png"
            for path, color in (
                (base, QColor(180, 150, 120, 255)),
                (clearcoat, QColor(210, 210, 210, 255)),
                (sheen, QColor(80, 120, 180, 255)),
                (transmission, QColor(120, 120, 160, 128)),
                (opacity, QColor(255, 255, 255, 64)),
            ):
                image = QImage(4, 4, QImage.Format_RGBA8888)
                image.fill(color)
                self.assertTrue(image.save(str(path), "PNG"))
            blob = b"".join(
                (
                    _vertex(-1.0, 0.0, 0.0, uv=(0.0, 0.0)),
                    _vertex(1.0, 0.0, 0.0, uv=(1.0, 0.0)),
                    _vertex(0.0, 1.0, 0.0, uv=(0.5, 1.0)),
                )
            )
            prepared = PreparedModelPreviewData(
                source_path="layered.gltf",
                format="gltf",
                batches=(
                    PreparedModelPreviewBatch(
                        material_name="Layered",
                        texture_name="Layered",
                        vertex_blob=blob,
                        index_count=3,
                        preview_texture_path=str(base),
                        preview_native_material_overrides={
                            "material_shader_family": "gltf_unlit",
                            "roughness": 1.0,
                            "specular": 0.0,
                        },
                        preview_material_texture_inputs=(
                            PreviewMaterialTextureInput(
                                slot_kind="specular",
                                parameter_name="_clearcoatTexture",
                                source_texture_path=str(clearcoat),
                                preview_texture_path=str(clearcoat),
                                semantic_type="specular",
                                semantic_subtype="clearcoat",
                                packed_channels=("clearcoat",),
                                confidence="gltf",
                            ),
                            PreviewMaterialTextureInput(
                                slot_kind="specular",
                                parameter_name="_sheenColorTexture",
                                source_texture_path=str(sheen),
                                preview_texture_path=str(sheen),
                                semantic_type="specular",
                                semantic_subtype="sheen",
                                packed_channels=("sheen",),
                                confidence="gltf",
                            ),
                            PreviewMaterialTextureInput(
                                slot_kind="material",
                                parameter_name="_transmissionTexture",
                                source_texture_path=str(transmission),
                                preview_texture_path=str(transmission),
                                semantic_type="material",
                                semantic_subtype="transmission",
                                packed_channels=("transmission",),
                                confidence="gltf",
                            ),
                            PreviewMaterialTextureInput(
                                slot_kind="opacity",
                                parameter_name="_opacityTexture",
                                source_texture_path=str(opacity),
                                preview_texture_path=str(opacity),
                                semantic_type="opacity",
                                semantic_subtype="opacity",
                                packed_channels=("alpha",),
                                confidence="gltf",
                            ),
                        ),
                        has_texture_coordinates=True,
                    ),
                ),
            )

            package_dir = write_isolated_d3d11_preview_package(
                ModelPreviewData(path="layered.gltf"),
                prepared,
                output_root=temp_path / "package",
                enable_material_combiner=False,
            )
            batch = read_isolated_d3d11_preview_manifest(package_dir)["batches"][0]
            contract = batch["material_contract"]
            normalized_slots = contract["normalized_texture_slots"]
            diagnostic_slots = {item["slot"]: item for item in batch["material_diagnostics"]}

            self.assertTrue(batch["textures"]["specular"])
            self.assertEqual("input_only", normalized_slots["clearcoat"]["status"])
            self.assertEqual("input_only", normalized_slots["sheen"]["status"])
            self.assertEqual("input_only", normalized_slots["transmission"]["status"])
            self.assertEqual("input_only", normalized_slots["opacity"]["status"])
            self.assertEqual("recorded", normalized_slots["unlit"]["status"])
            for slot in ("clearcoat", "sheen", "transmission", "opacity", "unlit"):
                self.assertIn(slot, diagnostic_slots)
            self.assertIn("transmission/volume recorded", " ".join(contract["preview_divergence_reasons"]))
            self.assertIn("opacity texture recorded", " ".join(contract["preview_divergence_reasons"]))

    def test_native_material_contract_uses_textureless_scalar_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            blob = b"".join(
                (
                    _vertex(-1.0, 0.0, 0.0, uv=(0.0, 0.0)),
                    _vertex(1.0, 0.0, 0.0, uv=(1.0, 0.0)),
                    _vertex(0.0, 1.0, 0.0, uv=(0.5, 1.0)),
                )
            )
            prepared = PreparedModelPreviewData(
                source_path="scalar.gltf",
                format="gltf",
                batches=(
                    PreparedModelPreviewBatch(
                        material_name="ScalarOnly",
                        vertex_blob=blob,
                        index_count=3,
                        preview_native_material_overrides={
                            "roughness": 0.35,
                            "metalness": 0.8,
                            "specular": 0.42,
                            "emissive_intensity": 2.0,
                            "emissive_color": "#123456",
                        },
                        has_texture_coordinates=True,
                    ),
                ),
            )

            package_dir = write_isolated_d3d11_preview_package(
                ModelPreviewData(path="scalar.gltf"),
                prepared,
                output_root=temp_path / "package",
                enable_material_combiner=False,
            )
            batch = read_isolated_d3d11_preview_manifest(package_dir)["batches"][0]
            hints = batch["material_contract"]["pbr_scalar_hints"]
            profile_hints = batch["material_contract"]["decode_profile"]["pbr_scalar_hints"]

            self.assertEqual(0.35, batch["roughness"])
            self.assertEqual(0.8, batch["metalness"])
            self.assertEqual(0.42, batch["specular"])
            self.assertEqual(2.0, batch["emissive_intensity"])
            self.assertEqual([18 / 255.0, 52 / 255.0, 86 / 255.0], batch["emissive_color"])
            self.assertTrue(batch["emissive_color_authoritative"])
            self.assertFalse(batch["emissive_scalar_mask"])
            self.assertTrue(batch["roughness_hint_present"])
            self.assertTrue(batch["metalness_hint_present"])
            self.assertTrue(batch["specular_hint_present"])
            self.assertEqual(0.35, hints["roughness"])
            self.assertEqual(0.8, hints["metalness"])
            self.assertEqual(0.42, hints["specular"])
            self.assertEqual(2.0, hints["emissive_intensity"])
            self.assertEqual(2.0, profile_hints["emissive_intensity"])

    def test_material_emissive_hex_color_uses_crimson_rgba_order(self) -> None:
        self.assertEqual((1.0, 0.0, 0.0), _material_hex_color_rgb("#FF0000FF"))
        self.assertEqual((0.0, 0.0, 1.0), _material_hex_color_rgb("#0000FFFF"))
        self.assertEqual((1.0, 1.0, 0.0), _material_hex_color_rgb("#FFFF0000"))
        self.assertEqual((18 / 255.0, 52 / 255.0, 86 / 255.0), _material_hex_color_rgb("#123456"))

    def test_specular_material_combiner_promotes_blade_metal_response(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            base = temp_path / "blade_o.png"
            base_image = QImage(4, 4, QImage.Format_RGBA8888)
            base_image.fill(QColor(62, 64, 68, 255))
            self.assertTrue(base_image.save(str(base), "PNG"))
            specular = temp_path / "blade_sp.png"
            specular_image = QImage(4, 4, QImage.Format_RGBA8888)
            specular_image.fill(QColor(220, 225, 235, 255))
            self.assertTrue(specular_image.save(str(specular), "PNG"))
            blob = b"".join(
                (
                    _vertex(-1.0, 0.0, 0.0, uv=(0.0, 0.0)),
                    _vertex(1.0, 0.0, 0.0, uv=(1.0, 0.0)),
                    _vertex(0.0, 1.0, 0.0, uv=(0.5, 1.0)),
                )
            )
            prepared = PreparedModelPreviewData(
                source_path="weapon.pac",
                batches=(
                    PreparedModelPreviewBatch(
                        material_name="blade",
                        texture_name="blade",
                        vertex_blob=blob,
                        index_count=3,
                        preview_texture_path=str(base),
                        preview_material_texture_inputs=(
                            PreviewMaterialTextureInput(
                                slot_kind="material",
                                parameter_name="_materialTexture",
                                texture_name="blade_sp",
                                source_texture_path="weapon/blade_sp.dds",
                                preview_texture_path=str(specular),
                                semantic_subtype="specular",
                                shader_family="SkinnedMeshStandard_Ver2",
                                material_parameters=(
                                    PreviewMaterialParameterInput(
                                        parameter_kind="byte4",
                                        parameter_name="_scratchMetallic",
                                        value="16777215",
                                    ),
                                    PreviewMaterialParameterInput(
                                        parameter_kind="byte4",
                                        parameter_name="_scratchRoughness",
                                        value="8388607",
                                    ),
                                ),
                            ),
                        ),
                        has_texture_coordinates=True,
                    ),
                ),
            )

            package_dir = write_isolated_d3d11_preview_package(
                ModelPreviewData(path="weapon.pac"),
                prepared,
                output_root=temp_path / "package",
            )
            manifest = read_isolated_d3d11_preview_manifest(package_dir)
            batch = manifest["batches"][0]
            textures = batch["textures"]

            for slot in ("roughness", "metalness", "specular"):
                self.assertTrue((package_dir / textures[slot]).is_file(), slot)
            self.assertEqual("shiny_metal_inspection", manifest["lighting_preset"])
            self.assertEqual("metal", batch["material_category"])
            self.assertGreaterEqual(batch["material_category_confidence"], 0.90)
            self.assertIn("standard_v2_specular", batch["material_combiner_decode_modes"])
            self.assertIn("metalness", batch["material_combiner_outputs"])
            self.assertGreater(batch["native_material_hints"]["metalness"], 0.0)
            self.assertGreater(batch["native_material_hints"]["specular"], 0.0)
            self.assertIn("material category:metal", " ".join(batch["notes"]))

    def test_helmet_bucket_packed_material_map_does_not_force_metal_preview(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            base = temp_path / "cd_texturelayer_002_0003.png"
            base_image = QImage(4, 4, QImage.Format_RGBA8888)
            base_image.fill(QColor(112, 106, 96, 255))
            self.assertTrue(base_image.save(str(base), "PNG"))
            material_dds = temp_path / "cd_phm_00_hel_00_0329_ma.dds"
            material_dds.write_bytes(_minimal_bc_dds(b"DXT1"))
            blob = b"".join(
                (
                    _vertex(-1.0, 0.0, 0.0, uv=(0.0, 0.0)),
                    _vertex(1.0, 0.0, 0.0, uv=(1.0, 0.0)),
                    _vertex(0.0, 1.0, 0.0, uv=(0.5, 1.0)),
                )
            )
            prepared = PreparedModelPreviewData(
                source_path="character/model/armor/13_hel/cd_phm_00_hel_00_0329.pac",
                batches=(
                    PreparedModelPreviewBatch(
                        material_name="CD_PHM_00_Hel_00_0329",
                        texture_name="cd_texturelayer_002_0003",
                        vertex_blob=blob,
                        index_count=3,
                        preview_texture_path=str(base),
                        preview_material_texture_dds_path=str(material_dds),
                        preview_material_texture_type="material",
                        preview_material_texture_subtype="packed_material",
                        preview_material_texture_packed_channels=(
                            "r=occlusion",
                            "g=roughness",
                            "b=metalness",
                            "a=specular_response",
                        ),
                        has_texture_coordinates=True,
                    ),
                ),
            )

            package_dir = write_isolated_d3d11_preview_package(
                ModelPreviewData(path="cd_phm_00_hel_00_0329.pac"),
                prepared,
                output_root=temp_path / "package",
                prefer_direct_dds=True,
            )
            manifest = read_isolated_d3d11_preview_manifest(package_dir)
            batch = manifest["batches"][0]

        self.assertEqual("neutral_studio", manifest["lighting_preset"])
        self.assertEqual("generic", batch["material_category"])
        self.assertEqual("generic:no_strong_material_token", batch["material_category_reason"])
        self.assertFalse(batch["material_response_promoted"])
        self.assertIn("material", batch["dds_textures"])

    def test_authoritative_helmet_family_material_mask_promotes_metal_preview(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            base = temp_path / "cd_texturelayer_003_0203.png"
            base_image = QImage(4, 4, QImage.Format_RGBA8888)
            base_image.fill(QColor(184, 166, 130, 255))
            self.assertTrue(base_image.save(str(base), "PNG"))
            material_dds = temp_path / "cd_phm_00_hel_00_0369_ma.dds"
            material_dds.write_bytes(_minimal_bc_dds(b"DXT1"))
            blob = b"".join(
                (
                    _vertex(-1.0, 0.0, 0.0, uv=(0.0, 0.0)),
                    _vertex(1.0, 0.0, 0.0, uv=(1.0, 0.0)),
                    _vertex(0.0, 1.0, 0.0, uv=(0.5, 1.0)),
                )
            )
            prepared = PreparedModelPreviewData(
                source_path="character/model/1_pc/1_phm/armor/13_hel/cd_phm_00_hel_00_0369.pac",
                batches=(
                    PreparedModelPreviewBatch(
                        material_name="11_normal",
                        texture_name="cd_texturelayer_003_0203",
                        vertex_blob=blob,
                        index_count=3,
                        preview_texture_path=str(base),
                        preview_material_texture_dds_path=str(material_dds),
                        preview_material_texture_type="material",
                        preview_material_texture_subtype="packed_material",
                        preview_material_texture_packed_channels=(
                            "r=occlusion",
                            "g=roughness",
                            "b=metalness",
                            "a=specular_response",
                        ),
                        preview_material_texture_inputs=(
                            PreviewMaterialTextureInput(
                                slot_kind="material",
                                parameter_name="_colorBlendingMaskTexture",
                                source_texture_path="character/texture/1_pc/1_phm/armor/13_hel/cd_phm_00_hel_00_0369_ma.dds",
                                source_dds_path=str(material_dds),
                                texture_name="cd_phm_00_hel_00_0369_ma.dds",
                                semantic_type="material",
                                semantic_subtype="packed_material",
                                packed_channels=(
                                    "r=occlusion",
                                    "g=roughness",
                                    "b=metalness",
                                    "a=specular_response",
                                ),
                                material_name="11_normal",
                                shader_family="SkinnedMeshStandard_Ver2",
                                sidecar_kind="pac_xml",
                                sidecar_path="character/modelproperty/1_pc/1_phm/armor/13_hel/cd_phm_00_hel_00_0369.pac_xml",
                                parameter_declared_by="technique",
                                material_output_quality="exact",
                            ),
                        ),
                        has_texture_coordinates=True,
                    ),
                ),
            )

            package_dir = write_isolated_d3d11_preview_package(
                ModelPreviewData(path="character/model/1_pc/1_phm/armor/13_hel/cd_phm_00_hel_00_0369.pac"),
                prepared,
                output_root=temp_path / "package",
                prefer_direct_dds=True,
            )
            manifest = read_isolated_d3d11_preview_manifest(package_dir)
            batch = manifest["batches"][0]

        self.assertEqual("shiny_metal_inspection", manifest["lighting_preset"])
        self.assertEqual("metal", batch["material_category"])
        self.assertEqual("metal:armor_family_material_response", batch["material_category_reason"])
        self.assertTrue(batch["material_response_promoted"])
        self.assertIn("material category:metal", " ".join(batch["notes"]))

    def test_authoritative_weapon_family_material_mask_promotes_guard_metal_preview(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            base = temp_path / "cd_texturelayer_013_0018.png"
            base_image = QImage(4, 4, QImage.Format_RGBA8888)
            base_image.fill(QColor(24, 30, 34, 255))
            self.assertTrue(base_image.save(str(base), "PNG"))
            material_dds = temp_path / "cd_phm_02_guard_0013_ma.dds"
            material_dds.write_bytes(_minimal_bc_dds(b"DXT1"))
            blob = b"".join(
                (
                    _vertex(-1.0, 0.0, 0.0, uv=(0.0, 0.0)),
                    _vertex(1.0, 0.0, 0.0, uv=(1.0, 0.0)),
                    _vertex(0.0, 1.0, 0.0, uv=(0.5, 1.0)),
                )
            )
            prepared = PreparedModelPreviewData(
                source_path="character/model/1_pc/1_phm/weapon/2_twohandweapon/cd_phm_02_sword_0015.pac",
                batches=(
                    PreparedModelPreviewBatch(
                        material_name="CD_PHM_02_Guard_0013",
                        texture_name="cd_texturelayer_013_0018",
                        vertex_blob=blob,
                        index_count=3,
                        preview_texture_path=str(base),
                        preview_material_texture_dds_path=str(material_dds),
                        preview_material_texture_type="material",
                        preview_material_texture_subtype="packed_material",
                        preview_material_texture_packed_channels=(
                            "r=occlusion",
                            "g=roughness",
                            "b=metalness",
                            "a=specular_response",
                        ),
                        preview_material_texture_inputs=(
                            PreviewMaterialTextureInput(
                                slot_kind="material",
                                parameter_name="_colorBlendingMaskTexture",
                                source_texture_path="character/texture/cd_phm_02_guard_0013_ma.dds",
                                source_dds_path=str(material_dds),
                                texture_name="cd_phm_02_guard_0013_ma.dds",
                                semantic_type="material",
                                semantic_subtype="packed_material",
                                packed_channels=(
                                    "r=occlusion",
                                    "g=roughness",
                                    "b=metalness",
                                    "a=specular_response",
                                ),
                                material_name="CD_PHM_02_Guard_0013",
                                shader_family="SkinnedMeshStandard_Ver2",
                                sidecar_kind="pac_xml",
                                sidecar_path="character/modelproperty/1_pc/1_phm/weapon/2_twohandweapon/cd_phm_02_sword_0015.pac_xml",
                                parameter_declared_by="technique",
                                material_output_quality="exact",
                            ),
                            PreviewMaterialTextureInput(
                                slot_kind="base",
                                parameter_name="embedded_mesh_reference",
                                texture_name="cd_phm_02_handle_0015.dds",
                                material_name="CD_PHM_02_Handle_0015",
                            ),
                        ),
                        has_texture_coordinates=True,
                    ),
                ),
            )

            package_dir = write_isolated_d3d11_preview_package(
                ModelPreviewData(path=prepared.source_path),
                prepared,
                output_root=temp_path / "package",
                prefer_direct_dds=True,
            )
            manifest = read_isolated_d3d11_preview_manifest(package_dir)
            batch = manifest["batches"][0]

        self.assertEqual("shiny_metal_inspection", manifest["lighting_preset"])
        self.assertEqual("metal", batch["material_category"])
        self.assertEqual("metal:weapon_family_material_response", batch["material_category_reason"])
        self.assertTrue(batch["material_response_promoted"])

    def test_sidecar_weapon_flag_tint_promotes_yellow_preview_base_tint(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            base = temp_path / "cd_phm_02_flag_0001.png"
            base_image = QImage(4, 4, QImage.Format_RGBA8888)
            base_image.fill(QColor(136, 20, 12, 255))
            self.assertTrue(base_image.save(str(base), "PNG"))
            blob = b"".join(
                (
                    _vertex(-1.0, 0.0, 0.0, uv=(0.0, 0.0)),
                    _vertex(1.0, 0.0, 0.0, uv=(1.0, 0.0)),
                    _vertex(0.0, 1.0, 0.0, uv=(0.5, 1.0)),
                )
            )
            prepared = PreparedModelPreviewData(
                source_path="character/model/1_pc/1_phm/weapon/2_twohandweapon/cd_phm_02_sword_0015.pac",
                batches=(
                    PreparedModelPreviewBatch(
                        material_name="CD_PHM_02_Flag_0001",
                        texture_name="cd_phm_02_flag_0001",
                        vertex_blob=blob,
                        index_count=3,
                        preview_texture_path=str(base),
                        preview_material_texture_inputs=(
                            PreviewMaterialTextureInput(
                                slot_kind="base",
                                parameter_name="_baseColorTexture",
                                texture_name="cd_phm_02_flag_0001.dds",
                                material_name="cd_phm_02_flag_0001",
                                shader_family="SkinnedMeshStandard_Ver2",
                                material_parameters=(
                                    PreviewMaterialParameterInput(
                                        parameter_kind="color",
                                        parameter_name="_tintColorR",
                                        color_value=(0.388235, 0.262745, 0.0352941),
                                    ),
                                    PreviewMaterialParameterInput(
                                        parameter_kind="color",
                                        parameter_name="_dyeingDetailLayerColorMaskR",
                                        color_value=(0.780392, 0.694118, 0.0431373),
                                    ),
                                ),
                            ),
                        ),
                        has_texture_coordinates=True,
                    ),
                ),
            )

            package_dir = write_isolated_d3d11_preview_package(
                ModelPreviewData(path=prepared.source_path),
                prepared,
                output_root=temp_path / "package",
            )
            manifest = read_isolated_d3d11_preview_manifest(package_dir)
            batch = manifest["batches"][0]

        self.assertEqual([0.7804, 0.6941, 0.0431], [round(value, 4) for value in batch["texture_tint"]])
        self.assertEqual(0.85, batch["base_tint_strength"])
        self.assertIn("sidecar tint promoted to preview base tint", batch["notes"])

    def test_sidecar_weapon_blade_layer_tint_stays_masked_not_global(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            base = temp_path / "cd_texturelayer_013_0018.png"
            base_image = QImage(4, 4, QImage.Format_RGBA8888)
            base_image.fill(QColor(120, 124, 128, 255))
            self.assertTrue(base_image.save(str(base), "PNG"))
            blob = b"".join(
                (
                    _vertex(-1.0, 0.0, 0.0, uv=(0.0, 0.0)),
                    _vertex(1.0, 0.0, 0.0, uv=(1.0, 0.0)),
                    _vertex(0.0, 1.0, 0.0, uv=(0.5, 1.0)),
                )
            )
            prepared = PreparedModelPreviewData(
                source_path="character/model/1_pc/1_phm/weapon/2_twohandweapon/cd_phm_02_sword_0015.pac",
                batches=(
                    PreparedModelPreviewBatch(
                        material_name="CD_PHM_02_Blade_0015",
                        texture_name="cd_texturelayer_013_0018",
                        vertex_blob=blob,
                        index_count=3,
                        preview_texture_path=str(base),
                        preview_material_texture_inputs=(
                            PreviewMaterialTextureInput(
                                slot_kind="base",
                                parameter_name="_grimeDiffuseTextureG",
                                texture_name="cd_texturelayer_013_0018.dds",
                                material_name="CD_PHM_02_Blade_0015",
                                shader_family="SkinnedMeshStandard_Ver2",
                                layer_role="grime",
                                layer_channel="g",
                                material_parameters=(
                                    PreviewMaterialParameterInput(
                                        parameter_kind="color",
                                        parameter_name="_dyeingGrimeLayerColorG",
                                        color_value=(0.054902, 0.25098, 0.196078),
                                    ),
                                ),
                            ),
                        ),
                        has_texture_coordinates=True,
                    ),
                ),
            )

            package_dir = write_isolated_d3d11_preview_package(
                ModelPreviewData(path=prepared.source_path),
                prepared,
                output_root=temp_path / "package",
            )
            manifest = read_isolated_d3d11_preview_manifest(package_dir)
            batch = manifest["batches"][0]

        self.assertEqual([], batch["texture_tint"])
        self.assertEqual(0.0, batch["base_tint_strength"])
        self.assertNotIn("sidecar tint promoted to preview base tint", batch["notes"])

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

    def test_material_category_uses_standalone_tinted_metal_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            base = temp_path / "base.png"
            base_image = QImage(4, 4, QImage.Format_RGBA8888)
            base_image.fill(QColor(90, 92, 96, 255))
            self.assertTrue(base_image.save(str(base), "PNG"))
            blob = b"".join(
                (
                    _vertex(-1.0, 0.0, 0.0, uv=(0.0, 0.0)),
                    _vertex(1.0, 0.0, 0.0, uv=(1.0, 0.0)),
                    _vertex(0.0, 1.0, 0.0, uv=(0.5, 1.0)),
                )
            )
            metal_tokens = ("gold", "silver", "copper", "bronze", "brass", "chrome")
            batches = tuple(
                PreparedModelPreviewBatch(
                    material_name=f"{token}_inlay",
                    texture_name=f"{token}_plate",
                    vertex_blob=blob,
                    index_count=3,
                    preview_texture_path=str(base),
                    has_texture_coordinates=True,
                )
                for token in metal_tokens
            ) + (
                PreparedModelPreviewBatch(
                    material_name="gold leather strap",
                    texture_name="strap",
                    vertex_blob=blob,
                    index_count=3,
                    preview_texture_path=str(base),
                    has_texture_coordinates=True,
                ),
                PreparedModelPreviewBatch(
                    material_name="brassiere_trim",
                    texture_name="fabric_trim",
                    vertex_blob=blob,
                    index_count=3,
                    preview_texture_path=str(base),
                    has_texture_coordinates=True,
                ),
                PreparedModelPreviewBatch(
                    material_name="glass_panel",
                    texture_name="clear_glass",
                    vertex_blob=blob,
                    index_count=3,
                    preview_texture_path=str(base),
                    has_texture_coordinates=True,
                ),
                PreparedModelPreviewBatch(
                    material_name="ruby_gem",
                    texture_name="ruby_jewel",
                    vertex_blob=blob,
                    index_count=3,
                    preview_texture_path=str(base),
                    has_texture_coordinates=True,
                ),
                PreparedModelPreviewBatch(
                    material_name="stone_rock",
                    texture_name="ceramic_stone",
                    vertex_blob=blob,
                    index_count=3,
                    preview_texture_path=str(base),
                    has_texture_coordinates=True,
                ),
                PreparedModelPreviewBatch(
                    material_name="eye_iris",
                    texture_name="eye_cornea",
                    vertex_blob=blob,
                    index_count=3,
                    preview_texture_path=str(base),
                    has_texture_coordinates=True,
                ),
                PreparedModelPreviewBatch(
                    material_name="tooth",
                    texture_name="teeth",
                    vertex_blob=blob,
                    index_count=3,
                    preview_texture_path=str(base),
                    has_texture_coordinates=True,
                ),
                PreparedModelPreviewBatch(
                    material_name="eyebrow",
                    texture_name="brow_lash",
                    vertex_blob=blob,
                    index_count=3,
                    preview_texture_path=str(base),
                    has_texture_coordinates=True,
                ),
                PreparedModelPreviewBatch(
                    material_name="CD_PHM_02_Handle_0015",
                    texture_name="cd_phm_02_handle_0015",
                    vertex_blob=blob,
                    index_count=3,
                    preview_texture_path=str(base),
                    has_texture_coordinates=True,
                ),
                PreparedModelPreviewBatch(
                    material_name="CD_PHM_02_Blade_0015",
                    texture_name="CD_PHM_02_Handle_0015",
                    vertex_blob=blob,
                    index_count=3,
                    preview_texture_path=str(base),
                    has_texture_coordinates=True,
                ),
                PreparedModelPreviewBatch(
                    material_name="CD_PHM_02_Stick_0013",
                    texture_name="cd_phm_02_stick_0013",
                    vertex_blob=blob,
                    index_count=3,
                    preview_texture_path=str(base),
                    has_texture_coordinates=True,
                ),
                PreparedModelPreviewBatch(
                    material_name="cd_phm_02_sword_0043",
                    texture_name="CD_R0002_00_Horse_Vest_0002",
                    vertex_blob=blob,
                    index_count=3,
                    preview_texture_path=str(base),
                    has_texture_coordinates=True,
                ),
                PreparedModelPreviewBatch(
                    material_name="cd_phm_02_sword_0043",
                    texture_name="shared_texturelayer",
                    vertex_blob=blob,
                    index_count=3,
                    preview_texture_path=str(base),
                    has_texture_coordinates=True,
                ),
            )
            package_dir = write_isolated_d3d11_preview_package(
                ModelPreviewData(path="wardrobe.pac"),
                PreparedModelPreviewData(source_path="wardrobe.pac", batches=batches),
                output_root=temp_path / "package",
            )
            manifest = read_isolated_d3d11_preview_manifest(package_dir)
            manifest_batches = manifest["batches"]
            categories_by_name = {str(batch["material_name"]): batch for batch in manifest_batches}

            for index, token in enumerate(metal_tokens):
                with self.subTest(token=token):
                    self.assertEqual("metal", manifest_batches[index]["material_category"])
                    self.assertGreaterEqual(manifest_batches[index]["material_category_confidence"], 0.60)
                    self.assertEqual("metal:color_token", manifest_batches[index]["material_category_reason"])
                    self.assertEqual("metal", manifest_batches[index]["material_analysis"]["category"])
            self.assertEqual("leather", categories_by_name["gold leather strap"]["material_category"])
            self.assertEqual("cloth", categories_by_name["brassiere_trim"]["material_category"])
            self.assertEqual("glass", categories_by_name["glass_panel"]["material_category"])
            self.assertEqual("gem", categories_by_name["ruby_gem"]["material_category"])
            self.assertEqual("stone", categories_by_name["stone_rock"]["material_category"])
            self.assertEqual("eye", categories_by_name["eye_iris"]["material_category"])
            self.assertEqual("tooth", categories_by_name["tooth"]["material_category"])
            self.assertEqual("hair", categories_by_name["eyebrow"]["material_category"])
            self.assertEqual("leather", categories_by_name["CD_PHM_02_Handle_0015"]["material_category"])
            self.assertEqual("metal", categories_by_name["CD_PHM_02_Blade_0015"]["material_category"])
            self.assertEqual("wood", categories_by_name["CD_PHM_02_Stick_0013"]["material_category"])
            sword_vest_batch = next(
                batch
                for batch in manifest_batches
                if batch["material_name"] == "cd_phm_02_sword_0043" and batch["texture_name"] == "CD_R0002_00_Horse_Vest_0002"
            )
            self.assertEqual("cloth", sword_vest_batch["material_category"])
            sword_only_batch = next(
                batch
                for batch in manifest_batches
                if batch["material_name"] == "cd_phm_02_sword_0043" and batch["texture_name"] == "shared_texturelayer"
            )
            self.assertEqual("generic", sword_only_batch["material_category"])
            for material_name in ("glass_panel", "ruby_gem", "stone_rock", "eye_iris", "tooth", "eyebrow", "CD_PHM_02_Handle_0015", "CD_PHM_02_Stick_0013"):
                self.assertIn("material_category_reason", categories_by_name[material_name])
                self.assertEqual(
                    categories_by_name[material_name]["material_category"],
                    categories_by_name[material_name]["material_analysis"]["category"],
                )
            for batch in (sword_vest_batch, sword_only_batch):
                self.assertIn("material_category_reason", batch)
                self.assertEqual(batch["material_category"], batch["material_analysis"]["category"])

    def test_apparel_slot_path_overrides_metallic_mask_for_cloth_lowerbody(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            base = temp_path / "cloth_base.png"
            base_image = QImage(4, 4, QImage.Format_RGBA8888)
            base_image.fill(QColor(145, 136, 104, 255))
            self.assertTrue(base_image.save(str(base), "PNG"))
            blob = b"".join(
                (
                    _vertex(-1.0, 0.0, 0.0, uv=(0.0, 0.0)),
                    _vertex(1.0, 0.0, 0.0, uv=(1.0, 0.0)),
                    _vertex(0.0, 1.0, 0.0, uv=(0.5, 1.0)),
                )
            )
            package_dir = write_isolated_d3d11_preview_package(
                ModelPreviewData(path="character/model/1_pc/14_ptm/armor/10_lowerbody/cd_ptm_00_lb_00_0318.pac"),
                PreparedModelPreviewData(
                    source_path="character/model/1_pc/14_ptm/armor/10_lowerbody/cd_ptm_00_lb_00_0318.pac",
                    batches=(
                        PreparedModelPreviewBatch(
                            material_name="CD_PHM_00_LB_0055_00_01_01",
                            texture_name="cd_phm_00_lb_0055_00_01_01",
                            vertex_blob=blob,
                            index_count=3,
                            preview_texture_path=str(base),
                            has_texture_coordinates=True,
                            preview_native_material_overrides={
                                "roughness": 0.24,
                                "metalness": 0.68,
                                "specular": 0.68,
                            },
                        ),
                    ),
                ),
                output_root=temp_path / "package",
            )

            batch = read_isolated_d3d11_preview_manifest(package_dir)["batches"][0]

            self.assertEqual("cloth", batch["material_category"])
            self.assertEqual("nonmetal:apparel_slot_token", batch["material_category_reason"])
            self.assertEqual(0.0, batch["metalness"])
            self.assertLessEqual(batch["specular"], 0.28)
            self.assertGreaterEqual(batch["roughness"], 0.48)

    def test_emissive_texture_gets_default_glow_without_sidecar_intensity(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            base = temp_path / "rune_base.png"
            base_image = QImage(4, 4, QImage.Format_RGBA8888)
            base_image.fill(QColor(18, 20, 24, 255))
            self.assertTrue(base_image.save(str(base), "PNG"))
            emissive = temp_path / "rune_emissive.png"
            emissive_image = QImage(4, 4, QImage.Format_RGBA8888)
            emissive_image.fill(QColor(40, 190, 255, 255))
            self.assertTrue(emissive_image.save(str(emissive), "PNG"))
            blob = b"".join(
                (
                    _vertex(-1.0, 0.0, 0.0, uv=(0.0, 0.0)),
                    _vertex(1.0, 0.0, 0.0, uv=(1.0, 0.0)),
                    _vertex(0.0, 1.0, 0.0, uv=(0.5, 1.0)),
                )
            )
            prepared = PreparedModelPreviewData(
                source_path="magic.pac",
                batches=(
                    PreparedModelPreviewBatch(
                        material_name="rune_glow",
                        texture_name="rune",
                        vertex_blob=blob,
                        index_count=3,
                        preview_texture_path=str(base),
                        preview_material_texture_inputs=(
                            PreviewMaterialTextureInput(
                                slot_kind="emissive",
                                parameter_name="_emissiveTexture",
                                texture_name="rune_emissive",
                                preview_texture_path=str(emissive),
                                semantic_type="emissive",
                                semantic_subtype="emissive",
                                shader_family="SkinnedMeshEmissive_Ver2",
                            ),
                        ),
                        has_texture_coordinates=True,
                    ),
                ),
            )

            package_dir = write_isolated_d3d11_preview_package(
                ModelPreviewData(path="magic.pac"),
                prepared,
                output_root=temp_path / "package",
            )
            batch = read_isolated_d3d11_preview_manifest(package_dir)["batches"][0]
            textures = batch["textures"]
            material_contract = batch["material_contract"]

            self.assertTrue((package_dir / textures["emissive"]).is_file())
            self.assertEqual(4.0, batch["emissive_intensity"])
            self.assertFalse(batch["emissive_color_authoritative"])
            self.assertFalse(batch["emissive_scalar_mask"])
            self.assertTrue(batch["native_material_hints"]["emissive_active"])
            self.assertEqual("emissive_texture_default", batch["native_material_hints"]["source"])
            self.assertEqual(4.0, material_contract["pbr_scalar_hints"]["emissive_intensity"])
            self.assertEqual(4.0, material_contract["decode_profile"]["pbr_scalar_hints"]["emissive_intensity"])

    def test_direct_bc4_emissive_dds_preserves_scalar_mask_without_material_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            emissive_dds = temp_path / "rune_emissive.dds"
            emissive_dds.write_bytes(_minimal_bc_dds(b"BC4U"))
            prepared = PreparedModelPreviewData(
                source_path="scalar-glow.pac",
                batches=(
                    PreparedModelPreviewBatch(
                        material_name="scalar_glow",
                        vertex_blob=_vertex(0, 0, 0) + _vertex(1, 0, 0) + _vertex(0, 1, 0),
                        index_count=3,
                        preview_emissive_texture_dds_path=str(emissive_dds),
                        has_texture_coordinates=True,
                    ),
                ),
            )

            package_dir = write_isolated_d3d11_preview_package(
                ModelPreviewData(path="scalar-glow.pac"),
                prepared,
                output_root=temp_path / "package",
                prefer_direct_dds=True,
            )
            batch = read_isolated_d3d11_preview_manifest(package_dir)["batches"][0]

            self.assertEqual("bc4", batch["dds_textures"]["emissive"]["compressed_family"])
            self.assertEqual(str(emissive_dds), batch["dds_textures"]["emissive"]["source_path"])
            self.assertTrue(batch["emissive_scalar_mask"])
            self.assertEqual("", batch["textures"]["emissive"])

    def test_emissive_texture_honors_explicit_zero_sidecar_intensity(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            emissive = temp_path / "disabled_emissive.png"
            emissive_image = QImage(2, 2, QImage.Format_RGBA8888)
            emissive_image.fill(QColor(255, 80, 20, 255))
            self.assertTrue(emissive_image.save(str(emissive), "PNG"))
            prepared = PreparedModelPreviewData(
                source_path="disabled-glow.pac",
                batches=(
                    PreparedModelPreviewBatch(
                        vertex_blob=_vertex(0, 0, 0) + _vertex(1, 0, 0) + _vertex(0, 1, 0),
                        index_count=3,
                        preview_material_texture_inputs=(
                            PreviewMaterialTextureInput(
                                slot_kind="emissive",
                                parameter_name="_emissiveTexture",
                                preview_texture_path=str(emissive),
                                semantic_type="emissive",
                                material_parameters=(
                                    PreviewMaterialParameterInput(
                                        parameter_name="_EmissiveIntensity",
                                        numeric_value=0.0,
                                    ),
                                ),
                            ),
                        ),
                        has_texture_coordinates=True,
                    ),
                ),
            )

            package_dir = write_isolated_d3d11_preview_package(
                ModelPreviewData(path="disabled-glow.pac"),
                prepared,
                output_root=temp_path / "package",
            )
            batch = read_isolated_d3d11_preview_manifest(package_dir)["batches"][0]

            self.assertTrue(batch["textures"]["emissive"])
            self.assertEqual(0.0, batch["emissive_intensity"])
            self.assertFalse(batch["native_material_hints"]["emissive_active"])
            self.assertTrue(batch["native_material_hints"]["emissive_intensity_declared"])

    def test_dedicated_emissive_source_survives_package_write_without_explicit_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            emissive = temp_path / "rune_emi.png"
            emissive_image = QImage(2, 2, QImage.Format_RGBA8888)
            emissive_image.fill(QColor(120, 220, 255, 255))
            self.assertTrue(emissive_image.save(str(emissive), "PNG"))
            prepared = PreparedModelPreviewData(
                source_path="rune.pac",
                batches=(
                    PreparedModelPreviewBatch(
                        vertex_blob=_vertex(0, 0, 0) + _vertex(1, 0, 0) + _vertex(0, 1, 0),
                        index_count=3,
                        preview_emissive_texture_path=str(emissive),
                        has_texture_coordinates=True,
                    ),
                ),
            )

            package_dir = write_isolated_d3d11_preview_package(
                ModelPreviewData(path="rune.pac"),
                prepared,
                output_root=temp_path / "package",
            )
            batch = read_isolated_d3d11_preview_manifest(package_dir)["batches"][0]

        self.assertTrue(batch["textures"]["emissive"])
        self.assertEqual("emissive", batch["material_inputs"][0]["slot_kind"])

    def test_package_reuses_legacy_pbr_response_without_full_recombine(self) -> None:
        from PySide6.QtGui import QColor, QImage

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            legacy_pbr = temp_path / "legacy_pbr.png"
            image = QImage(2, 2, QImage.Format_RGBA8888)
            image.fill(QColor(220, 96, 170, 210))
            self.assertTrue(image.save(str(legacy_pbr), "PNG"))
            blob = b"".join(
                (
                    _vertex(-1.0, 0.0, 0.0, uv=(0.0, 0.0)),
                    _vertex(1.0, 0.0, 0.0, uv=(1.0, 0.0)),
                    _vertex(0.0, 1.0, 0.0, uv=(0.5, 1.0)),
                )
            )
            prepared = PreparedModelPreviewData(
                source_path="weapon.pac",
                batches=(
                    PreparedModelPreviewBatch(
                        material_name="blade",
                        vertex_blob=blob,
                        index_count=3,
                        preview_material_texture_path=str(legacy_pbr),
                        preview_material_texture_subtype="pbr_combined",
                        preview_material_texture_packed_channels=("ao", "roughness", "metallic", "specular"),
                        has_texture_coordinates=True,
                    ),
                ),
            )

            package_dir = write_isolated_d3d11_preview_package(
                ModelPreviewData(path="weapon.pac"),
                prepared,
                output_root=temp_path / "package",
            )
            manifest = read_isolated_d3d11_preview_manifest(package_dir)

            batch = manifest["batches"][0]
            textures = batch["textures"]
            for slot in ("occlusion", "roughness", "metalness", "specular"):
                self.assertTrue((package_dir / textures[slot]).is_file(), slot)
            self.assertEqual(["pbr_combined"], batch["material_combiner_decode_modes"])
            self.assertIn("legacy PBR response reused", " ".join(batch["material_combiner_notes"]))

    def test_d3d11_package_can_flip_texture_v_from_render_settings(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            base = temp_path / "base.png"
            base.write_bytes(b"png")
            prepared = PreparedModelPreviewData(
                source_path="weapon.pac",
                batches=(
                    PreparedModelPreviewBatch(
                        material_name="blade",
                        vertex_blob=_vertex(0, 0, 0) + _vertex(1, 0, 0) + _vertex(0, 1, 0),
                        index_count=3,
                        preview_texture_path=str(base),
                        preview_texture_flip_vertical=False,
                        has_texture_coordinates=True,
                    ),
                ),
            )

            package_dir = write_isolated_d3d11_preview_package(
                ModelPreviewData(path="weapon.pac"),
                prepared,
                output_root=temp_path / "package",
                render_settings=ModelPreviewRenderSettings(flip_texture_v=True),
            )
            manifest = read_isolated_d3d11_preview_manifest(package_dir)

        self.assertTrue(manifest["batches"][0]["texture_flip_vertical"])

    def test_d3d11_package_writes_material_value_preview_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            base = temp_path / "base.png"
            base.write_bytes(b"png")
            prepared = PreparedModelPreviewData(
                source_path="weapon.pac",
                batches=(
                    PreparedModelPreviewBatch(
                        material_name="blade",
                        vertex_blob=_vertex(0, 0, 0, color=(0.2, 0.4, 0.8))
                        + _vertex(1, 0, 0, color=(0.2, 0.4, 0.8))
                        + _vertex(0, 1, 0, color=(0.2, 0.4, 0.8)),
                        index_count=3,
                        preview_texture_path=str(base),
                        preview_texture_brightness=1.75,
                        preview_texture_tint=(0.2, 0.4, 0.8),
                        preview_texture_uv_scale=(2.5, 3.5),
                        has_texture_coordinates=True,
                    ),
                ),
            )

            package_dir = write_isolated_d3d11_preview_package(
                ModelPreviewData(path="weapon.pac"),
                prepared,
                output_root=temp_path / "package",
            )
            manifest = read_isolated_d3d11_preview_manifest(package_dir)

        batch = manifest["batches"][0]
        self.assertEqual([0.2, 0.4, 0.8], [round(value, 4) for value in batch["base_color"]])
        self.assertEqual(1.75, batch["texture_brightness"])
        self.assertEqual([2.5, 3.5], batch["texture_uv_scale"])
        self.assertEqual([0.2, 0.4, 0.8], batch["texture_tint"])
        self.assertEqual(0.85, batch["base_tint_strength"])

    def test_scene_import_package_defaults_to_unflipped_texture_v(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            base = temp_path / "base.png"
            base.write_bytes(b"png")
            prepared = PreparedModelPreviewData(
                source_path="triangle.gltf",
                format="gltf",
                batches=(
                    PreparedModelPreviewBatch(
                        material_name="body",
                        vertex_blob=_vertex(0, 0, 0) + _vertex(1, 0, 0) + _vertex(0, 1, 0),
                        index_count=3,
                        preview_texture_path=str(base),
                        preview_texture_flip_vertical=None,
                        has_texture_coordinates=True,
                    ),
                ),
            )

            package_dir = write_isolated_d3d11_preview_package(
                ModelPreviewData(path="triangle.gltf", format="gltf"),
                prepared,
                output_root=temp_path / "package",
            )
            manifest = read_isolated_d3d11_preview_manifest(package_dir)

        self.assertFalse(manifest["batches"][0]["texture_flip_vertical"])
    def test_scene_import_explicit_unflipped_texture_v_stays_unflipped(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            base = temp_path / "base.png"
            base.write_bytes(b"png")
            prepared = PreparedModelPreviewData(
                source_path="triangle.gltf",
                format="gltf",
                batches=(
                    PreparedModelPreviewBatch(
                        material_name="body",
                        vertex_blob=_vertex(0, 0, 0) + _vertex(1, 0, 0) + _vertex(0, 1, 0),
                        index_count=3,
                        preview_texture_path=str(base),
                        preview_texture_flip_vertical=False,
                        has_texture_coordinates=True,
                    ),
                ),
            )

            package_dir = write_isolated_d3d11_preview_package(
                ModelPreviewData(path="triangle.gltf", format="gltf"),
                prepared,
                output_root=temp_path / "package",
            )
            manifest = read_isolated_d3d11_preview_manifest(package_dir)

        self.assertFalse(manifest["batches"][0]["texture_flip_vertical"])

    def test_scene_import_package_flip_texture_v_toggles_once(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            base = temp_path / "base.png"
            base.write_bytes(b"png")
            prepared = PreparedModelPreviewData(
                source_path="triangle.glb",
                format="glb",
                batches=(
                    PreparedModelPreviewBatch(
                        material_name="body",
                        vertex_blob=_vertex(0, 0, 0) + _vertex(1, 0, 0) + _vertex(0, 1, 0),
                        index_count=3,
                        preview_texture_path=str(base),
                        preview_texture_flip_vertical=None,
                        has_texture_coordinates=True,
                    ),
                ),
            )

            package_dir = write_isolated_d3d11_preview_package(
                ModelPreviewData(path="triangle.glb", format="glb"),
                prepared,
                output_root=temp_path / "package",
                render_settings=ModelPreviewRenderSettings(flip_texture_v=True),
            )
            manifest = read_isolated_d3d11_preview_manifest(package_dir)

        self.assertTrue(manifest["batches"][0]["texture_flip_vertical"])

    def test_archive_explicit_unflipped_texture_v_stays_unflipped(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            base = temp_path / "base.dds"
            base.write_bytes(_minimal_bc_dds())
            prepared = PreparedModelPreviewData(
                source_path="weapon.pac",
                format="pac",
                batches=(
                    PreparedModelPreviewBatch(
                        material_name="blade",
                        vertex_blob=_vertex(0, 0, 0) + _vertex(1, 0, 0) + _vertex(0, 1, 0),
                        index_count=3,
                        preview_texture_path=str(base),
                        preview_texture_dds_path=str(base),
                        preview_texture_flip_vertical=False,
                        has_texture_coordinates=True,
                    ),
                ),
            )

            package_dir = write_isolated_d3d11_preview_package(
                ModelPreviewData(path="weapon.pac", format="pac"),
                prepared,
                output_root=temp_path / "package",
            )
            manifest = read_isolated_d3d11_preview_manifest(package_dir)

        self.assertFalse(manifest["batches"][0]["texture_flip_vertical"])
